"""All the money and status rules for bookings live here, so the routes stay thin."""
import logging
import math
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    Booking,
    BookingStatus,
    Charger,
    ChargerStatus,
    CommunityMember,
    ExtraCharge,
    PaymentStatus,
    User,
    WaitlistEntry,
    utcnow,
)
from . import payments, push
from .timeutil import parse_hhmm, tz, utc_naive_to_aware, within_open_hours

log = logging.getLogger("bookings")
PAID_STATES = (PaymentStatus.PAID, PaymentStatus.PARTIALLY_REFUNDED)


# ---------- pricing ----------
def _in_offpeak(local_dt: datetime, charger: Charger) -> bool:
    if not charger.offpeak_price_paise:
        return False
    t, a, b = local_dt.time(), parse_hhmm(charger.offpeak_start), parse_hhmm(charger.offpeak_end)
    if a == b:
        return True
    return a <= t < b if a < b else (t >= a or t < b)


def window_price(charger: Charger, start: datetime | None, minutes: int) -> int:
    """Price (paise) for `minutes` starting at `start` (naive UTC), honouring the off-peak rate in 15-minute steps.
    Per-kWh chargers are priced at the maximum energy the charger can deliver in that time."""
    if start is None or not charger.offpeak_price_paise:
        rate_minutes = [(charger.price_paise, minutes)]
    else:
        rate_minutes, cur, left = [], utc_naive_to_aware(start).astimezone(tz()), minutes
        while left > 0:
            step = min(15, left)
            rate_minutes.append((charger.offpeak_price_paise if _in_offpeak(cur, charger) else charger.price_paise, step))
            cur += timedelta(minutes=step)
            left -= step
    factor = charger.power_kw if charger.pricing_mode == "kwh" else 1.0
    return math.ceil(sum(rate * factor * m / 60 for rate, m in rate_minutes))


def estimate_amount(charger: Charger, minutes: int, start: datetime | None = None) -> int:
    return max(100, window_price(charger, start, minutes))


def blended_unit_price(charger: Charger, amount: int, minutes: int) -> int:
    """For per-kWh bookings: the average price per kWh across the slot (off-peak and normal mixed)."""
    if charger.pricing_mode != "kwh" or minutes <= 0:
        return charger.price_paise
    return max(1, round(amount / (charger.power_kw * minutes / 60)))


def split_commission(final_paise: int) -> tuple[int, int]:
    commission = round(final_paise * get_settings().commission_percent / 100)
    return commission, final_paise - commission


# ---------- visibility ----------
def is_member(db: Session, user: User, community_id: int | None) -> bool:
    if community_id is None:
        return True
    return db.scalar(
        select(CommunityMember.id).where(
            CommunityMember.community_id == community_id,
            CommunityMember.user_id == user.id,
            CommunityMember.status == "approved",
        )
    ) is not None


def outstanding_dues(db: Session, user: User) -> list[ExtraCharge]:
    return db.scalars(select(ExtraCharge).where(ExtraCharge.user_id == user.id, ExtraCharge.status == "due")).all()


# ---------- validation ----------
def overlapping(
    db: Session,
    charger_id: int,
    start: datetime,
    end: datetime,
    exclude_id: int | None = None,
    statuses: tuple = BookingStatus.BLOCKING,
):
    q = select(Booking).where(
        Booking.charger_id == charger_id,
        Booking.status.in_(statuses),
        Booking.start_at < end,
        Booking.end_at > start,
    )
    if exclude_id:
        q = q.where(Booking.id != exclude_id)
    return db.scalars(q).all()


def validate_new_booking(db: Session, charger: Charger, driver: User, start: datetime, end: datetime, vehicle: str):
    s = get_settings()
    now = utcnow()
    if charger.status != ChargerStatus.APPROVED or not charger.host.is_host or charger.host.deleted_at:
        raise HTTPException(400, "This charger is not available right now")
    if charger.offline:
        raise HTTPException(400, f"The host marked this charger temporarily unavailable{': ' + charger.offline_reason if charger.offline_reason else ''}")
    if charger.host_id == driver.id:
        raise HTTPException(400, "You can't book your own charger")
    if not is_member(db, driver, charger.community_id):
        raise HTTPException(403, "This charger is only for residents of its housing society")
    dues = outstanding_dues(db, driver)
    if dues:
        raise HTTPException(402, f"Please clear your pending dues of ₹{sum(d.amount_paise for d in dues) / 100:.0f} first (Bookings → Dues)")
    if vehicle and charger.vehicle_types and vehicle not in charger.vehicle_types:
        raise HTTPException(400, f"This charger does not support {vehicle} vehicles")
    minutes = int((end - start).total_seconds() // 60)
    if minutes < s.min_booking_minutes:
        raise HTTPException(400, f"Book at least {s.min_booking_minutes} minutes")
    if minutes > s.max_booking_minutes:
        raise HTTPException(400, f"Bookings can be at most {s.max_booking_minutes // 60} hours")
    if start < now - timedelta(minutes=5):
        raise HTTPException(400, "Start time is in the past")
    if start > now + timedelta(days=s.max_days_ahead):
        raise HTTPException(400, f"You can book up to {s.max_days_ahead} days ahead")
    if not within_open_hours(start, end, charger.open_time, charger.close_time):
        raise HTTPException(400, f"Charger is open {charger.open_time}–{charger.close_time} only")
    release_stale_unpaid(db)
    if overlapping(db, charger.id, start, end):
        raise HTTPException(409, "That time slot is already booked. Pick another time, or join the waitlist.")
    return minutes


# ---------- refunds (main payment + paid extensions) ----------
def _refund(db: Session, booking: Booking, amount: int) -> int:
    """Refund up to `amount` paise of what the driver prepaid (booking + extensions). Returns the amount refunded."""
    sources = [x for x in reversed(booking.extras) if x.kind == "extension" and x.status in PAID_STATES]
    if booking.payment is not None and booking.payment.status in PAID_STATES:
        sources.append(booking.payment)
    refunded = 0
    for src in sources:  # newest extension first, then the main payment
        if refunded >= amount:
            break
        part = max(0, min(amount - refunded, src.amount_paise - src.refunded_paise))
        if part == 0:
            continue
        refund_id = payments.refund(src.provider_payment_id or src.order_id, part)
        src.refunded_paise += part
        src.refund_ids = [*src.refund_ids, refund_id]
        src.status = PaymentStatus.REFUNDED if src.refunded_paise >= src.amount_paise else PaymentStatus.PARTIALLY_REFUNDED
        refunded += part
    booking.refund_paise += refunded
    return refunded


# ---------- main state changes ----------
def mark_paid(db: Session, booking: Booking, provider_payment_id: str) -> Booking:
    """Called once the gateway confirms payment. Safe to call twice (webhook + app)."""
    pay = booking.payment
    if pay and pay.status == PaymentStatus.PAID:
        return booking
    if pay:
        pay.status = PaymentStatus.PAID
        pay.provider_payment_id = provider_payment_id
    booking.paid_at = utcnow()

    if booking.status != BookingStatus.PENDING_PAYMENT:
        # Paid after the slot was released (very late payment): give the money back.
        db.flush()
        _refund(db, booking, booking.amount_paise)
        db.commit()
        return booking

    # another booking may have grabbed the slot while this one was unpaid for too long
    if overlapping(db, booking.charger_id, booking.start_at, booking.end_at, exclude_id=booking.id, statuses=BookingStatus.OPEN):
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_by = "system"
        booking.cancel_reason = "Slot was taken before payment finished"
        db.flush()
        _refund(db, booking, booking.amount_paise)
        db.commit()
        push.notify(booking.driver, "Booking cancelled", "The slot was taken before your payment went through. Full refund issued.")
        return booking

    charger = booking.charger
    if charger.auto_accept and not charger.society_only:
        booking.status = BookingStatus.CONFIRMED
        db.commit()
        push.notify(booking.driver, "Booking confirmed", f"{charger.title} is booked for you.", {"bookingId": booking.id})
        push.notify(booking.host, "New booking", f"Your charger {charger.title} was booked.", {"bookingId": booking.id})
    else:
        booking.status = BookingStatus.REQUESTED
        db.commit()
        push.notify(booking.host, "New booking request", f"Someone wants to charge at {charger.title}. Accept it in the app.", {"bookingId": booking.id})
        push.notify(booking.driver, "Request sent", "Payment received. Waiting for the host to accept.", {"bookingId": booking.id})
    return booking


def host_respond(db: Session, booking: Booking, accept: bool, reason: str = "") -> Booking:
    if booking.status != BookingStatus.REQUESTED:
        raise HTTPException(400, "This booking is not waiting for a response")
    if accept:
        booking.status = BookingStatus.CONFIRMED
        db.commit()
        push.notify(booking.driver, "Booking confirmed", f"{booking.charger.title} accepted your booking.", {"bookingId": booking.id})
    else:
        booking.status = BookingStatus.DECLINED
        booking.cancelled_by = "host"
        booking.cancel_reason = reason
        _refund(db, booking, booking.amount_paise)
        db.commit()
        push.notify(booking.driver, "Booking declined", "The host couldn't take this booking. Full refund issued.", {"bookingId": booking.id})
        notify_waitlist(db, booking)
    return booking


def cancel(db: Session, booking: Booking, by: str, reason: str = "") -> Booking:
    s = get_settings()
    if booking.status == BookingStatus.PENDING_PAYMENT:
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_by = by
        db.commit()
        notify_waitlist(db, booking)
        return booking
    if booking.status not in (BookingStatus.REQUESTED, BookingStatus.CONFIRMED):
        raise HTTPException(400, "This booking can't be cancelled now")

    if by == "driver" and booking.status == BookingStatus.CONFIRMED:
        minutes_left = (booking.start_at - utcnow()).total_seconds() / 60
        refund_amount = (
            booking.amount_paise
            if minutes_left >= s.free_cancel_minutes
            else booking.amount_paise * s.late_cancel_refund_percent // 100
        )
    else:
        refund_amount = booking.amount_paise  # host/admin/system cancel, or host never accepted

    booking.status = BookingStatus.CANCELLED
    booking.cancelled_by = by
    booking.cancel_reason = reason
    refunded = _refund(db, booking, refund_amount)
    kept = booking.amount_paise - refunded if booking.paid_at else 0
    if kept > 0:  # late cancellation fee goes to the host, minus commission
        booking.final_amount_paise = kept
        booking.commission_paise, booking.host_earning_paise = split_commission(kept)
    db.commit()

    other = booking.host if by == "driver" else booking.driver
    push.notify(other, "Booking cancelled", f"Booking #{booking.id} at {booking.charger.title} was cancelled.", {"bookingId": booking.id})
    if by != "driver":
        push.notify(booking.driver, "Refund issued", f"₹{refunded / 100:.0f} is on its way back to you.", {"bookingId": booking.id})
    notify_waitlist(db, booking)
    return booking


REQUIRED_CHECKS = ("cable_ok", "connector_matches", "area_dry")


def check_in(db: Session, booking: Booking, qr_token: str, checklist: dict | None = None) -> Booking:
    s = get_settings()
    if booking.status != BookingStatus.CONFIRMED:
        raise HTTPException(400, "Booking is not confirmed")
    if qr_token.strip() != booking.charger.qr_token:
        raise HTTPException(400, "This QR code belongs to a different charger")
    checklist = checklist or {}
    missing = [k for k in REQUIRED_CHECKS if not checklist.get(k)]
    if missing:
        raise HTTPException(
            400, "Complete the safety checklist first. If something looks unsafe, tap 'Charger not working' for a full refund."
        )
    now = utcnow()
    if now < booking.start_at - timedelta(minutes=s.checkin_early_minutes):
        raise HTTPException(400, f"You can check in from {s.checkin_early_minutes} minutes before your slot")
    if now > booking.end_at:
        raise HTTPException(400, "Your slot has already ended")
    booking.status = BookingStatus.ACTIVE
    booking.checked_in_at = now
    booking.checklist = {**{k: bool(checklist.get(k)) for k in REQUIRED_CHECKS}, "at": now.isoformat(), "note": str(checklist.get("note", ""))[:300]}
    db.commit()
    push.notify(booking.host, "Driver arrived", f"Charging started at {booking.charger.title}.", {"bookingId": booking.id})
    return booking


def report_not_working(db: Session, booking: Booking, reason: str) -> Booking:
    """Driver at the charger says it doesn't work: full refund now; repeated reports take the charger offline."""
    s = get_settings()
    if booking.status not in (BookingStatus.CONFIRMED, BookingStatus.ACTIVE):
        raise HTTPException(400, "You can report this only for a confirmed or active booking")
    now = utcnow()
    if now < booking.start_at - timedelta(minutes=s.checkin_early_minutes) or now > booking.end_at + timedelta(minutes=30):
        raise HTTPException(400, "You can report this only around your slot time. Otherwise use Report a problem.")
    if booking.status == BookingStatus.ACTIVE and booking.checked_in_at and now - booking.checked_in_at > timedelta(minutes=20):
        raise HTTPException(400, "Charging has been running for a while. Finish the session, or use Report a problem.")
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_by = "system"
    booking.cancel_reason = f"Charger not working: {reason}"[:300]
    booking.charger_failed = True
    refunded = _refund(db, booking, booking.amount_paise)
    db.commit()

    charger = booking.charger
    week_ago = now - timedelta(days=7)
    last_success = db.scalar(
        select(func.max(Booking.completed_at)).where(
            Booking.charger_id == charger.id, Booking.status == BookingStatus.COMPLETED, Booking.no_show.is_(False)
        )
    )
    since = max(week_ago, last_success) if last_success else week_ago
    # failures since the last successful session (looking back at most 7 days)
    fails = db.scalar(
        select(func.count()).select_from(Booking).where(
            Booking.charger_id == charger.id, Booking.charger_failed.is_(True), Booking.start_at >= since - timedelta(hours=1)
        )
    )
    if fails >= s.not_working_auto_offline and not charger.offline:
        charger.offline = True
        charger.offline_reason = "Reported not working. The host is checking it."
        db.commit()
        push.notify(charger.host, "Charger taken offline", f"{charger.title} was reported not working {fails} times. Fix it, then switch it back on.")
    push.notify(booking.host, "Driver reported a problem", f"Your charger didn't work for booking #{booking.id}: {reason}", {"bookingId": booking.id})
    push.notify(booking.driver, "Full refund issued", f"Sorry about that. ₹{refunded / 100:.0f} is on its way back.", {"bookingId": booking.id})
    notify_waitlist(db, booking)
    return booking


def complete(
    db: Session,
    booking: Booking,
    kwh_used: float | None = None,
    no_show: bool = False,
    charge_full: bool = False,
    by: str = "system",
) -> Booking:
    s = get_settings()
    if booking.status not in (BookingStatus.ACTIVE, BookingStatus.CONFIRMED):
        raise HTTPException(400, "Only an active booking can be completed")
    final = booking.amount_paise
    if booking.pricing_mode == "kwh" and not no_show and not charge_full:
        if kwh_used is None:
            raise HTTPException(400, "Enter the units (kWh) used, from the charger or meter display")
        if kwh_used < 0 or kwh_used > 200:
            raise HTTPException(400, "kWh value looks wrong")
        booking.kwh_used = kwh_used
        final = min(booking.amount_paise, max(0, math.ceil(kwh_used * booking.unit_price_paise)))
        _refund(db, booking, booking.amount_paise - final)
    booking.final_amount_paise = final
    booking.commission_paise, booking.host_earning_paise = split_commission(final)
    booking.status = BookingStatus.COMPLETED
    booking.no_show = no_show
    now = utcnow()
    booking.completed_at = now

    # overstay: only when a person closes the session late (never for automatic completion)
    fee = 0
    charger = booking.charger
    over = (now - booking.end_at).total_seconds() / 60 - s.overstay_grace_minutes
    if by in ("driver", "host") and not no_show and charger.idle_fee_paise > 0 and over > 0:
        blocks = min(s.overstay_max_blocks, math.ceil(over / 15))
        fee = blocks * charger.idle_fee_paise
        booking.overstay_minutes = int(over + s.overstay_grace_minutes)
        db.add(
            ExtraCharge(
                booking_id=booking.id, user_id=booking.driver_id, host_id=booking.host_id, kind="overstay",
                minutes=booking.overstay_minutes, amount_paise=fee, status="due",
            )
        )
    db.commit()
    msg = "Thanks for charging! Rate your host in the app."
    if fee:
        msg = f"You stayed {booking.overstay_minutes} min past your slot. An overstay fee of ₹{fee / 100:.0f} is due."
    push.notify(booking.driver, "Charging complete", msg, {"bookingId": booking.id})
    push.notify(booking.host, "Session complete", f"You earned ₹{booking.host_earning_paise / 100:.0f}.", {"bookingId": booking.id})
    return booking


# ---------- extensions & dues ----------
def request_extension(db: Session, booking: Booking, minutes: int) -> ExtraCharge:
    s = get_settings()
    if minutes not in (15, 30, 45, 60, 90, 120):
        raise HTTPException(400, "Extend by 15, 30, 45, 60, 90 or 120 minutes")
    if booking.status not in (BookingStatus.CONFIRMED, BookingStatus.ACTIVE):
        raise HTTPException(400, "Only a confirmed or active booking can be extended")
    now = utcnow()
    if now > booking.end_at:
        raise HTTPException(400, "Your slot has already ended")
    total = int((booking.end_at - booking.start_at).total_seconds() // 60) + minutes
    if total > s.max_booking_minutes:
        raise HTTPException(400, f"A booking can be at most {s.max_booking_minutes // 60} hours in total")
    new_end = booking.end_at + timedelta(minutes=minutes)
    charger = booking.charger
    if not within_open_hours(booking.end_at, new_end, charger.open_time, charger.close_time):
        raise HTTPException(400, f"The charger closes at {charger.close_time}")
    if overlapping(db, charger.id, booking.end_at, new_end, exclude_id=booking.id):
        raise HTTPException(409, "Someone has booked the next slot, so this booking can't be extended")
    for x in booking.extras:  # drop older unpaid extension attempts
        if x.kind == "extension" and x.status == "created":
            x.status = "cancelled"
    amount = max(100, window_price(charger, booking.end_at, minutes))
    extra = ExtraCharge(
        booking_id=booking.id, user_id=booking.driver_id, host_id=booking.host_id, kind="extension",
        minutes=minutes, amount_paise=amount, status="created", provider=payments.provider(),
    )
    db.add(extra)
    db.flush()
    try:
        extra.order_id = payments.create_order(amount, receipt=f"extra_{extra.id}", notes={"extra_id": str(extra.id)})
    except payments.PaymentError as e:
        db.rollback()
        raise HTTPException(502, str(e))
    db.commit()
    return extra


def start_dues_payment(db: Session, extra: ExtraCharge) -> ExtraCharge:
    if extra.status != "due":
        raise HTTPException(400, "Nothing to pay here")
    extra.provider = payments.provider()
    try:
        extra.order_id = payments.create_order(extra.amount_paise, receipt=f"extra_{extra.id}", notes={"extra_id": str(extra.id)})
    except payments.PaymentError as e:
        raise HTTPException(502, str(e))
    db.commit()
    return extra


def mark_extra_paid(db: Session, extra: ExtraCharge, provider_payment_id: str) -> ExtraCharge:
    if extra.status in PAID_STATES:
        return extra
    booking = extra.booking
    extra.provider_payment_id = provider_payment_id
    extra.paid_at = utcnow()
    if extra.kind == "overstay":
        extra.status = PaymentStatus.PAID
        extra.commission_paise, extra.host_earning_paise = split_commission(extra.amount_paise)
        db.commit()
        push.notify(booking.host, "Overstay fee received", f"You earned ₹{extra.host_earning_paise / 100:.0f} extra for booking #{booking.id}.")
        return extra

    # extension: re-check the slot is still free, then lengthen the booking
    new_end = booking.end_at + timedelta(minutes=extra.minutes)
    still_ok = (
        booking.status in (BookingStatus.CONFIRMED, BookingStatus.ACTIVE)
        and extra.status == "created"
        and not overlapping(db, booking.charger_id, booking.end_at, new_end, exclude_id=booking.id)
    )
    extra.status = PaymentStatus.PAID
    if not still_ok:
        db.flush()
        part = payments.refund(provider_payment_id or extra.order_id, extra.amount_paise)
        extra.refunded_paise, extra.refund_ids, extra.status = extra.amount_paise, [part], PaymentStatus.REFUNDED
        db.commit()
        push.notify(booking.driver, "Extension not possible", "The next slot was taken. Your payment has been refunded.", {"bookingId": booking.id})
        return extra
    booking.end_at = new_end
    booking.amount_paise += extra.amount_paise
    booking.extended_minutes += extra.minutes
    if booking.pricing_mode == "kwh":
        minutes = int((booking.end_at - booking.start_at).total_seconds() // 60)
        booking.unit_price_paise = blended_unit_price(booking.charger, booking.amount_paise, minutes)
    db.commit()
    push.notify(booking.host, "Booking extended", f"Booking #{booking.id} now ends {extra.minutes} minutes later.", {"bookingId": booking.id})
    return extra


# ---------- waitlist ----------
def notify_waitlist(db: Session, booking: Booking) -> int:
    """A slot opened up: tell everyone waiting for that charger on that day."""
    day = utc_naive_to_aware(booking.start_at).astimezone(tz()).strftime("%Y-%m-%d")
    entries = db.scalars(
        select(WaitlistEntry).where(
            WaitlistEntry.charger_id == booking.charger_id, WaitlistEntry.day == day, WaitlistEntry.notified_at.is_(None)
        )
    ).all()
    for e in entries:
        if e.user_id == booking.driver_id:
            continue
        e.notified_at = utcnow()
        push.notify(e.user, "A slot just opened", f"{booking.charger.title} has a free slot on {day}. Book it before someone else does.", {"chargerId": booking.charger_id})
    if entries:
        db.commit()
    return len(entries)


# ---------- background clean-up ----------
def release_stale_unpaid(db: Session) -> int:
    cutoff = utcnow() - timedelta(minutes=get_settings().payment_window_minutes)
    stale = db.scalars(
        select(Booking).where(Booking.status == BookingStatus.PENDING_PAYMENT, Booking.created_at < cutoff)
    ).all()
    for b in stale:
        b.status = BookingStatus.EXPIRED
        b.cancel_reason = "Payment not completed in time"
        b.cancelled_by = "system"
    if stale:
        db.commit()
    return len(stale)


def sweep(db: Session) -> dict:
    """Runs every minute: expires unpaid/unanswered bookings and auto-completes finished ones."""
    s = get_settings()
    now = utcnow()
    counts = {"unpaid": release_stale_unpaid(db), "unanswered": 0, "completed": 0}

    unanswered = db.scalars(
        select(Booking).where(Booking.status == BookingStatus.REQUESTED, Booking.start_at <= now)
    ).all()
    for b in unanswered:
        b.status = BookingStatus.EXPIRED
        b.cancelled_by = "system"
        b.cancel_reason = "Host did not respond before the start time"
        _refund(db, b, b.amount_paise)
        db.commit()
        push.notify(b.driver, "Booking expired", "The host didn't respond in time. Full refund issued.", {"bookingId": b.id})
        counts["unanswered"] += 1

    done_cutoff = now - timedelta(minutes=s.auto_complete_after_minutes)
    finished = db.scalars(
        select(Booking).where(
            Booking.end_at <= done_cutoff,
            or_(
                Booking.status == BookingStatus.CONFIRMED,
                and_(Booking.status == BookingStatus.ACTIVE, Booking.pricing_mode == "hour"),
            ),
        )
    ).all()
    for b in finished:
        try:
            complete(db, b, no_show=b.status == BookingStatus.CONFIRMED)
            counts["completed"] += 1
        except HTTPException:
            db.rollback()

    # per-kWh sessions nobody closed within 12 hours: settle at the prepaid amount
    forgotten = db.scalars(
        select(Booking).where(
            Booking.status == BookingStatus.ACTIVE,
            Booking.pricing_mode == "kwh",
            Booking.end_at <= now - timedelta(hours=12),
        )
    ).all()
    for b in forgotten:
        complete(db, b, charge_full=True)
        counts["completed"] += 1
    return counts
