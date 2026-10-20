from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import (
    Booking,
    BookingStatus,
    Charger,
    ChargerStatus,
    Community,
    ExtraCharge,
    HostStatus,
    Payout,
    Report,
    User,
    utcnow,
)
from ..security import require_admin
from ..serializers import booking_out, charger_out, charger_ratings, charger_stats
from ..services import booking_logic, push, storage
from ..services.booking_logic import _refund

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class AdminUserOut(schemas.UserOut):
    id_doc_keys: list[str]
    deleted_at: datetime | None = None


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=1000)


class ApproveChargerIn(BaseModel):
    safety_checked: bool = False
    note: str = Field(default="", max_length=1000)


class RefundIn(BaseModel):
    amount_paise: int = Field(gt=0)
    reason: str = Field(default="", max_length=300)


class MarkPaidIn(BaseModel):
    reference: str = Field(min_length=3, max_length=120)


class ReplyIn(BaseModel):
    reply: str = Field(default="", max_length=3000)


# ---------- dashboard ----------
@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    now = utcnow()
    week = now - timedelta(days=7)

    def count(q):
        return db.scalar(select(func.count()).select_from(q.subquery())) or 0

    completed = select(Booking).where(Booking.status == BookingStatus.COMPLETED)
    return {
        "users": count(select(User).where(User.deleted_at.is_(None))),
        "hosts_approved": count(select(User).where(User.host_status == HostStatus.APPROVED)),
        "hosts_pending": count(select(User).where(User.host_status == HostStatus.PENDING)),
        "chargers_live": count(select(Charger).where(Charger.status == ChargerStatus.APPROVED)),
        "chargers_pending": count(select(Charger).where(Charger.status == ChargerStatus.PENDING)),
        "bookings_open": count(select(Booking).where(Booking.status.in_(BookingStatus.OPEN))),
        "bookings_completed": count(completed),
        "bookings_last_7_days": count(select(Booking).where(Booking.created_at >= week, Booking.paid_at.is_not(None))),
        "gross_paise": db.scalar(select(func.coalesce(func.sum(Booking.final_amount_paise), 0))) or 0,
        "commission_paise": db.scalar(select(func.coalesce(func.sum(Booking.commission_paise), 0))) or 0,
        "reports_open": count(select(Report).where(Report.status == "open")),
        "chargers_offline": count(select(Charger).where(Charger.status == ChargerStatus.APPROVED, Charger.offline.is_(True))),
        "not_working_reports_7d": count(select(Booking).where(Booking.charger_failed.is_(True), Booking.start_at >= week)),
        "communities_pending": count(select(Community).where(Community.status == "pending")),
        "dues_outstanding_paise": db.scalar(select(func.coalesce(func.sum(ExtraCharge.amount_paise), 0)).where(ExtraCharge.status == "due")) or 0,
        "commission_overstay_paise": db.scalar(select(func.coalesce(func.sum(ExtraCharge.commission_paise), 0))) or 0,
        "payouts_pending_paise": db.scalar(
            select(func.coalesce(func.sum(Payout.amount_paise), 0)).where(Payout.status == "pending")
        )
        or 0,
    }


# ---------- users & hosts ----------
@router.get("/users", response_model=list[AdminUserOut])
def users(
    host_status: str | None = None, q: str | None = None, db: Session = Depends(get_db), limit: int = Query(100, le=500)
):
    stmt = select(User).order_by(User.created_at.desc())
    if host_status:
        stmt = stmt.where(User.host_status == host_status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.phone.ilike(like), User.name.ilike(like), User.email.ilike(like)))
    return db.scalars(stmt.limit(limit)).all()


@router.post("/hosts/{user_id}/approve", response_model=AdminUserOut)
def approve_host(user_id: int, db: Session = Depends(get_db)):
    u = _user(db, user_id)
    u.host_status, u.is_host, u.host_note = HostStatus.APPROVED, True, ""
    db.commit()
    push.notify(u, "You're a host now!", "Your verification is approved. Your chargers go live once reviewed.")
    return u


@router.post("/hosts/{user_id}/reject", response_model=AdminUserOut)
def reject_host(user_id: int, body: NoteIn, db: Session = Depends(get_db)):
    u = _user(db, user_id)
    u.host_status, u.is_host, u.host_note = HostStatus.REJECTED, False, body.note
    for c in db.scalars(select(Charger).where(Charger.host_id == u.id, Charger.status == ChargerStatus.APPROVED)).all():
        c.status = ChargerStatus.PAUSED
    db.commit()
    push.notify(u, "Host verification", body.note or "We couldn't verify your documents. Please re-upload.")
    return u


@router.get("/files/{key}")
def private_file(key: str):
    data, ctype = storage.read_private(key)
    return Response(content=data, media_type=ctype, headers={"cache-control": "private, no-store"})


# ---------- chargers ----------
@router.get("/chargers", response_model=list[schemas.ChargerHostOut])
def chargers(status: str | None = None, db: Session = Depends(get_db), limit: int = Query(200, le=500)):
    stmt = select(Charger).order_by(Charger.created_at.desc())
    if status:
        stmt = stmt.where(Charger.status == status)
    rows = db.scalars(stmt.limit(limit)).all()
    ids = [c.id for c in rows]
    ratings, st = charger_ratings(db, ids), charger_stats(db, ids)
    return [charger_out(c, ratings, for_host=True, stats=st) for c in rows]


class OfflineIn(BaseModel):
    offline: bool
    reason: str = Field(default="", max_length=200)


@router.post("/chargers/{charger_id}/offline", response_model=schemas.ChargerHostOut)
def set_offline(charger_id: int, body: OfflineIn, db: Session = Depends(get_db)):
    c = _charger(db, charger_id)
    c.offline, c.offline_reason = body.offline, (body.reason if body.offline else "")
    db.commit()
    push.notify(c.host, "Charger status changed", f"{c.title} is now {'offline' if body.offline else 'back online'}. {body.reason}".strip())
    return charger_out(c, for_host=True, stats=charger_stats(db, [c.id]))


@router.get("/flags")
def flags(db: Session = Depends(get_db)):
    """Things to look at: unreliable chargers and drivers who report 'not working' unusually often."""
    month = utcnow() - timedelta(days=30)
    chargers_all = db.scalars(select(Charger).where(Charger.status.in_((ChargerStatus.APPROVED, ChargerStatus.PAUSED)))).all()
    st = charger_stats(db, [c.id for c in chargers_all])
    weak = []
    for c in chargers_all:
        ok, bad = st.get(c.id, (0, 0))
        if bad and (ok + bad < 3 or ok / (ok + bad) < 0.8):
            weak.append({"charger_id": c.id, "title": c.title, "host": c.host.name, "successful": ok, "not_working": bad, "offline": c.offline})
    claims = db.execute(
        select(Booking.driver_id, func.count()).where(Booking.charger_failed.is_(True), Booking.start_at >= month).group_by(Booking.driver_id)
    ).all()
    drivers = [
        {"user_id": uid, "name": db.get(User, uid).name, "phone": db.get(User, uid).phone, "claims_30d": n}
        for uid, n in claims if n >= 3
    ]
    return {"unreliable_chargers": weak, "frequent_claimers": drivers}


# ---------- housing societies ----------
@router.get("/communities", response_model=list[schemas.CommunityOut])
def communities(status: str | None = None, db: Session = Depends(get_db)):
    from .communities import community_out

    stmt = select(Community).order_by(Community.created_at.desc())
    if status:
        stmt = stmt.where(Community.status == status)
    return [community_out(db, c) for c in db.scalars(stmt).all()]


@router.post("/communities/{community_id}/{action}", response_model=schemas.CommunityOut)
def decide_community(community_id: int, action: str, body: NoteIn, db: Session = Depends(get_db)):
    from .communities import community_out

    c = db.get(Community, community_id)
    if c is None:
        raise HTTPException(404, "Society not found")
    if action not in ("approve", "reject"):
        raise HTTPException(400, "Action must be approve or reject")
    c.status, c.admin_note = ("approved" if action == "approve" else "rejected"), body.note
    db.commit()
    push.notify(
        c.manager, c.name,
        f"Approved! Share join code {c.code} with residents." if action == "approve" else (body.note or "Your society was not approved."),
    )
    return community_out(db, c)


@router.post("/chargers/{charger_id}/approve", response_model=schemas.ChargerHostOut)
def approve_charger(charger_id: int, body: ApproveChargerIn, db: Session = Depends(get_db)):
    c = _charger(db, charger_id)
    c.status, c.safety_checked, c.admin_note = ChargerStatus.APPROVED, body.safety_checked, body.note
    db.commit()
    msg = "is live now." if c.host.is_host else "is approved. It goes live once your host verification is approved."
    push.notify(c.host, "Charger approved", f"{c.title} {msg}")
    return charger_out(c, for_host=True)


@router.post("/chargers/{charger_id}/reject", response_model=schemas.ChargerHostOut)
def reject_charger(charger_id: int, body: NoteIn, db: Session = Depends(get_db)):
    c = _charger(db, charger_id)
    c.status, c.admin_note = ChargerStatus.REJECTED, body.note
    db.commit()
    push.notify(c.host, "Charger needs changes", body.note or f"{c.title} was not approved.")
    return charger_out(c, for_host=True)


# ---------- bookings ----------
@router.get("/bookings", response_model=list[schemas.BookingOut])
def bookings(
    status: str | None = None,
    user_id: int | None = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int = Query(200, le=500),
):
    stmt = select(Booking).order_by(Booking.created_at.desc())
    if status:
        stmt = stmt.where(Booking.status == status)
    if user_id:
        stmt = stmt.where(or_(Booking.driver_id == user_id, Booking.host_id == user_id))
    return [booking_out(db, b, admin) for b in db.scalars(stmt.limit(limit)).all()]


@router.post("/bookings/{booking_id}/cancel", response_model=schemas.BookingOut)
def cancel_booking(booking_id: int, body: NoteIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    b = _booking(db, booking_id)
    return booking_out(db, booking_logic.cancel(db, b, by="admin", reason=body.note), admin)


@router.post("/bookings/{booking_id}/refund", response_model=schemas.BookingOut)
def refund_booking(booking_id: int, body: RefundIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Goodwill / dispute refund. If the booking was already completed, the host's earning is reduced too."""
    b = _booking(db, booking_id)
    if b.payout_id and db.get(Payout, b.payout_id).status == "paid":
        raise HTTPException(400, "Host was already paid for this booking; settle the difference manually")
    refunded = _refund(db, b, body.amount_paise)
    if refunded == 0:
        raise HTTPException(400, "Nothing left to refund on this booking")
    if b.final_amount_paise is not None:
        b.final_amount_paise = max(0, b.final_amount_paise - refunded)
        b.commission_paise, b.host_earning_paise = booking_logic.split_commission(b.final_amount_paise)
        if b.payout_id:  # keep a pending payout in sync
            p = db.get(Payout, b.payout_id)
            p.amount_paise = sum(x.host_earning_paise for x in db.scalars(select(Booking).where(Booking.payout_id == p.id))) + sum(
                x.host_earning_paise for x in db.scalars(select(ExtraCharge).where(ExtraCharge.payout_id == p.id))
            )
    b.cancel_reason = (b.cancel_reason + f" | Admin refund: {body.reason}").strip(" |")
    db.commit()
    push.notify(b.driver, "Refund issued", f"₹{refunded / 100:.0f} is on its way back to you.")
    return booking_out(db, b, admin)


# ---------- reports ----------
@router.get("/reports", response_model=list[schemas.ReportOut])
def reports(status: str | None = "open", db: Session = Depends(get_db)):
    stmt = select(Report).order_by(Report.created_at.desc())
    if status:
        stmt = stmt.where(Report.status == status)
    return db.scalars(stmt.limit(300)).all()


@router.post("/reports/{report_id}/resolve", response_model=schemas.ReportOut)
def resolve_report(report_id: int, body: ReplyIn, db: Session = Depends(get_db)):
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "Report not found")
    r.status, r.admin_reply = "resolved", body.reply
    db.commit()
    if body.reply:
        push.notify(r.reporter, "Update on your report", body.reply[:120])
    return r


# ---------- payouts ----------
@router.post("/payouts/generate", response_model=list[schemas.PayoutOut])
def generate_payouts(db: Session = Depends(get_db)):
    """Groups every unpaid host earning into one payout per host. Run weekly, then pay each by UPI."""
    rows = db.scalars(
        select(Booking).where(Booking.payout_id.is_(None), Booking.host_earning_paise > 0)
    ).all()
    extras = db.scalars(
        select(ExtraCharge).where(ExtraCharge.payout_id.is_(None), ExtraCharge.kind == "overstay", ExtraCharge.host_earning_paise > 0)
    ).all()
    by_host: dict[int, list] = {}
    for item in [*rows, *extras]:
        by_host.setdefault(item.host_id, []).append(item)
    created = []
    for host_id, items in by_host.items():
        host = db.get(User, host_id)
        p = Payout(
            host_id=host_id,
            amount_paise=sum(x.host_earning_paise for x in items),
            booking_count=sum(1 for x in items if isinstance(x, Booking)),
            upi_id=host.payout_upi if host else "",
        )
        db.add(p)
        db.flush()
        for x in items:
            x.payout_id = p.id
        created.append(p)
    db.commit()
    return [_payout_out(p) for p in created]


@router.get("/payouts", response_model=list[schemas.PayoutOut])
def payouts(status: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Payout).order_by(Payout.created_at.desc())
    if status:
        stmt = stmt.where(Payout.status == status)
    return [_payout_out(p) for p in db.scalars(stmt.limit(300)).all()]


@router.post("/payouts/{payout_id}/mark-paid", response_model=schemas.PayoutOut)
def mark_paid(payout_id: int, body: MarkPaidIn, db: Session = Depends(get_db)):
    p = db.get(Payout, payout_id)
    if p is None:
        raise HTTPException(404, "Payout not found")
    p.status, p.reference, p.paid_at = "paid", body.reference, utcnow()
    db.commit()
    push.notify(p.host, "Payout sent", f"₹{p.amount_paise / 100:.0f} sent to {p.upi_id}. Ref: {body.reference}")
    return _payout_out(p)


# ---------- helpers ----------
def _payout_out(p: Payout) -> schemas.PayoutOut:
    out = schemas.PayoutOut.model_validate(p)
    out.host_name, out.host_phone = (p.host.name, p.host.phone) if p.host else ("", "")
    return out


def _user(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    return u


def _charger(db: Session, charger_id: int) -> Charger:
    c = db.get(Charger, charger_id)
    if c is None:
        raise HTTPException(404, "Charger not found")
    return c


def _booking(db: Session, booking_id: int) -> Booking:
    b = db.get(Booking, booking_id)
    if b is None:
        raise HTTPException(404, "Booking not found")
    return b
