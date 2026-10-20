from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import Booking, BookingStatus, Charger, ChargerStatus, HostStatus, Payout, User, utcnow
from ..security import get_current_user
from ..services import booking_logic
from ..services.timeutil import to_utc_naive, tz

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=schemas.UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("", response_model=schemas.UserOut)
def update_me(body: schemas.UserUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(user, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    return user


@router.post("/host-application", response_model=schemas.UserOut)
def apply_as_host(body: schemas.HostApplication, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Driver sends ID proof + UPI ID. Admin reviews and approves in the admin panel."""
    if not user.name:
        raise HTTPException(400, "Add your full name in your profile first")
    user.id_doc_keys = body.id_doc_keys
    user.payout_upi = body.payout_upi
    if user.host_status != HostStatus.APPROVED:
        user.host_status = HostStatus.PENDING
        user.host_note = ""
    db.commit()
    return user


@router.get("/earnings", response_model=schemas.EarningsOut)
def earnings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    earned_q = select(Booking).where(Booking.host_id == user.id, Booking.host_earning_paise > 0)
    rows = db.scalars(earned_q).all()
    local_now = datetime.now(tz())
    month_start_local = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start = to_utc_naive(month_start_local)
    paid_out = db.scalar(
        select(func.coalesce(func.sum(Payout.amount_paise), 0)).where(Payout.host_id == user.id, Payout.status == "paid")
    )
    upcoming = db.scalar(
        select(func.count()).select_from(Booking).where(
            Booking.host_id == user.id,
            Booking.status.in_((BookingStatus.REQUESTED, BookingStatus.CONFIRMED, BookingStatus.ACTIVE)),
        )
    )
    return schemas.EarningsOut(
        completed_sessions=sum(1 for b in rows if b.status == BookingStatus.COMPLETED),
        total_earned_paise=sum(b.host_earning_paise for b in rows),
        this_month_paise=sum(b.host_earning_paise for b in rows if (b.completed_at or b.created_at) >= month_start),
        pending_payout_paise=sum(
            b.host_earning_paise for b in rows if b.payout_id is None or _payout_pending(db, b.payout_id)
        ),
        paid_out_paise=int(paid_out or 0),
        upcoming_bookings=int(upcoming or 0),
    )


def _payout_pending(db: Session, payout_id: int) -> bool:
    p = db.get(Payout, payout_id)
    return p is not None and p.status != "paid"


@router.get("/payouts", response_model=list[schemas.PayoutOut])
def my_payouts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Payout).where(Payout.host_id == user.id).order_by(Payout.created_at.desc())).all()


@router.delete("")
def delete_account(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Required by both app stores. Cancels open bookings (with refunds) and anonymises the account."""
    open_bookings = db.scalars(
        select(Booking).where(
            (Booking.driver_id == user.id) | (Booking.host_id == user.id),
            Booking.status.in_(BookingStatus.BLOCKING),
        )
    ).all()
    for b in open_bookings:
        if b.status == BookingStatus.ACTIVE:
            booking_logic.complete(db, b, charge_full=True)
        else:
            booking_logic.cancel(db, b, by="host" if b.host_id == user.id else "admin", reason="Account deleted")
    for c in db.scalars(select(Charger).where(Charger.host_id == user.id)).all():
        c.status = ChargerStatus.PAUSED
    user.phone = f"deleted-{user.id}-{int(utcnow().timestamp())}"
    user.name, user.email, user.push_token = "Deleted user", "", ""
    user.id_doc_keys = []  # payout_upi is kept so any money still owed can be paid out
    user.is_host = False
    user.deleted_at = utcnow()
    db.commit()
    return {"ok": True}
