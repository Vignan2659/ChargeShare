"""All the money and status rules for bookings live here, so the routes stay thin."""
import logging
import math
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    Booking,
    BookingStatus,
    Charger,
    ChargerStatus,
    Payment,
    PaymentStatus,
    User,
    utcnow,
)
from . import payments, push
from .timeutil import within_open_hours

log = logging.getLogger("bookings")


# ---------- pricing ----------
def estimate_amount(charger: Charger, minutes: int) -> int:
    hours = minutes / 60
    if charger.pricing_mode == "kwh":
        # charge the maximum the charger could deliver; the unused part is refunded at the end
        return max(100, math.ceil(charger.price_paise * charger.power_kw * hours))
    return max(100, math.ceil(charger.price_paise * hours))


def split_commission(final_paise: int) -> tuple[int, int]:
    commission = round(final_paise * get_settings().commission_percent / 100)
    return commission, final_paise - commission


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
    if charger.host_id == driver.id:
        raise HTTPException(400, "You can't book your own charger")
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
        raise HTTPException(409, "That time slot is already booked. Pick another time.")
    return minutes


# ---------- state changes ----------
def _refund(db: Session, booking: Booking, amount: int) -> int:
    """Refund up to `amount` paise of what the driver paid. Returns the amount refunded."""
    pay: Payment | None = booking.payment
    if pay is None or pay.status not in (PaymentStatus.PAID, PaymentStatus.PARTIALLY_REFUNDED):
        return 0
    amount = max(0, min(amount, pay.amount_paise - pay.refunded_paise))
    if amount == 0:
        return 0
    refund_id = payments.refund(pay.provider_payment_id or pay.order_id, amount)
    pay.refunded_paise += amount
    pay.refund_ids = [*pay.refund_ids, refund_id]
    pay.status = PaymentStatus.REFUNDED if pay.refunded_paise >= pay.amount_paise else PaymentStatus.PARTIALLY_REFUNDED
    booking.refund_paise += amount
    return amount


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
    if charger.auto_accept:
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
    return booking


def cancel(db: Session, booking: Booking, by: str, reason: str = "") -> Booking:
    s = get_settings()
    if booking.status == BookingStatus.PENDING_PAYMENT:
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_by = by
        db.commit()
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
    return booking


def check_in(db: Session, booking: Booking, qr_token: str) -> Booking:
    s = get_settings()
    if booking.status != BookingStatus.CONFIRMED:
        raise HTTPException(400, "Booking is not confirmed")
    if qr_token.strip() != booking.charger.qr_token:
        raise HTTPException(400, "This QR code belongs to a different charger")
    now = utcnow()
    if now < booking.start_at - timedelta(minutes=s.checkin_early_minutes):
        raise HTTPException(400, f"You can check in from {s.checkin_early_minutes} minutes before your slot")
    if now > booking.end_at:
        raise HTTPException(400, "Your slot has already ended")
    booking.status = BookingStatus.ACTIVE
    booking.checked_in_at = now
    db.commit()
    push.notify(booking.host, "Driver arrived", f"Charging started at {booking.charger.title}.", {"bookingId": booking.id})
    return booking


def complete(
    db: Session, booking: Booking, kwh_used: float | None = None, no_show: bool = False, charge_full: bool = False
) -> Booking:
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
    booking.completed_at = utcnow()
    db.commit()
    push.notify(booking.driver, "Charging complete", "Thanks for charging! Rate your host in the app.", {"bookingId": booking.id})
    push.notify(booking.host, "Session complete", f"You earned ₹{booking.host_earning_paise / 100:.0f}.", {"bookingId": booking.id})
    return booking


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
