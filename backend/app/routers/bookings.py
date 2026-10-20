from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..config import get_settings
from ..db import get_db
from ..models import Booking, BookingStatus, Charger, Payment, User
from ..security import get_current_user
from ..serializers import booking_out
from ..services import booking_logic, payments
from ..services.timeutil import to_utc_naive
from .payments import make_pay_token

router = APIRouter(prefix="/bookings", tags=["bookings"])


def _times(body: schemas.QuoteIn):
    start, end = to_utc_naive(body.start_at), to_utc_naive(body.end_at)
    if end <= start:
        raise HTTPException(400, "End time must be after start time")
    return start, end


@router.post("/quote", response_model=schemas.QuoteOut)
def quote(body: schemas.QuoteIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    charger = db.get(Charger, body.charger_id)
    if charger is None:
        raise HTTPException(404, "Charger not found")
    start, end = _times(body)
    minutes = int((end - start).total_seconds() // 60)
    amount = booking_logic.estimate_amount(charger, minutes)
    note = (
        "You pay the maximum upfront. Unused units are refunded after charging."
        if charger.pricing_mode == "kwh"
        else "Fixed price for the time slot."
    )
    return schemas.QuoteOut(amount_paise=amount, minutes=minutes, pricing_mode=charger.pricing_mode, note=note)


@router.post("", response_model=schemas.CheckoutOut, status_code=201)
def create(body: schemas.BookingCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.name:
        raise HTTPException(400, "Add your name in Profile before booking")
    charger = db.get(Charger, body.charger_id)
    if charger is None:
        raise HTTPException(404, "Charger not found")
    start, end = _times(body)
    minutes = booking_logic.validate_new_booking(db, charger, user, start, end, body.vehicle_type)
    amount = booking_logic.estimate_amount(charger, minutes)

    b = Booking(
        charger_id=charger.id,
        driver_id=user.id,
        host_id=charger.host_id,
        start_at=start,
        end_at=end,
        vehicle_type=body.vehicle_type,
        vehicle_note=body.vehicle_note,
        pricing_mode=charger.pricing_mode,
        unit_price_paise=charger.price_paise,
        amount_paise=amount,
    )
    db.add(b)
    db.flush()
    try:
        order_id = payments.create_order(amount, receipt=f"booking_{b.id}", notes={"booking_id": str(b.id)})
    except payments.PaymentError as e:
        db.rollback()
        raise HTTPException(502, str(e))
    db.add(Payment(booking_id=b.id, provider=payments.provider(), order_id=order_id, amount_paise=amount))
    db.commit()
    db.refresh(b)

    checkout_url = ""
    if payments.provider() == "razorpay":
        checkout_url = f"{get_settings().public_base_url}/pay/{b.id}?t={make_pay_token(b.id)}"
    return schemas.CheckoutOut(booking=booking_out(db, b, user), provider=payments.provider(), checkout_url=checkout_url)


@router.get("", response_model=list[schemas.BookingOut])
def list_mine(
    role: str = Query("driver", pattern="^(driver|host)$"),
    scope: str = Query("all", pattern="^(all|upcoming|past)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    col = Booking.driver_id if role == "driver" else Booking.host_id
    q = select(Booking).where(col == user.id)
    if role == "host":
        q = q.where(Booking.status != BookingStatus.PENDING_PAYMENT)
    if scope == "upcoming":
        q = q.where(Booking.status.in_(BookingStatus.BLOCKING)).order_by(Booking.start_at)
    elif scope == "past":
        q = q.where(Booking.status.not_in(BookingStatus.BLOCKING)).order_by(Booking.start_at.desc())
    else:
        q = q.order_by(Booking.start_at.desc())
    return [booking_out(db, b, user) for b in db.scalars(q.limit(200)).all()]


@router.get("/{booking_id}", response_model=schemas.BookingOut)
def get_one(booking_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return booking_out(db, _visible(db, booking_id, user), user)


@router.post("/{booking_id}/accept", response_model=schemas.BookingOut)
def accept(booking_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    b = _as_host(db, booking_id, user)
    return booking_out(db, booking_logic.host_respond(db, b, accept=True), user)


@router.post("/{booking_id}/decline", response_model=schemas.BookingOut)
def decline(booking_id: int, body: schemas.CancelIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    b = _as_host(db, booking_id, user)
    return booking_out(db, booking_logic.host_respond(db, b, accept=False, reason=body.reason), user)


@router.post("/{booking_id}/cancel", response_model=schemas.BookingOut)
def cancel(booking_id: int, body: schemas.CancelIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    b = _visible(db, booking_id, user)
    by = "driver" if b.driver_id == user.id else "host" if b.host_id == user.id else "admin"
    return booking_out(db, booking_logic.cancel(db, b, by=by, reason=body.reason), user)


@router.post("/{booking_id}/check-in", response_model=schemas.BookingOut)
def check_in(booking_id: int, body: schemas.CheckInIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    b = _visible(db, booking_id, user)
    if b.driver_id != user.id:
        raise HTTPException(403, "Only the driver can check in")
    return booking_out(db, booking_logic.check_in(db, b, body.qr_token), user)


@router.post("/{booking_id}/complete", response_model=schemas.BookingOut)
def complete(booking_id: int, body: schemas.CompleteIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    b = _visible(db, booking_id, user)
    if b.status != BookingStatus.ACTIVE:
        raise HTTPException(400, "Charging hasn't started yet. Scan the charger's QR code first.")
    return booking_out(db, booking_logic.complete(db, b, kwh_used=body.kwh_used), user)


def _visible(db: Session, booking_id: int, user: User) -> Booking:
    b = db.get(Booking, booking_id)
    if b is None or (user.id not in (b.driver_id, b.host_id) and not user.is_admin):
        raise HTTPException(404, "Booking not found")
    return b


def _as_host(db: Session, booking_id: int, user: User) -> Booking:
    b = db.get(Booking, booking_id)
    if b is None or b.host_id != user.id:
        raise HTTPException(404, "Booking not found")
    return b
