"""Turns database rows into API responses (adds ratings, distance, and who-sees-what)."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import schemas
from .models import Booking, BookingStatus, Charger, Review, User


def charger_ratings(db: Session, charger_ids: list[int]) -> dict[int, tuple[float, int]]:
    if not charger_ids:
        return {}
    rows = db.execute(
        select(Review.charger_id, func.avg(Review.rating), func.count(Review.id))
        .where(Review.charger_id.in_(charger_ids))
        .group_by(Review.charger_id)
    ).all()
    return {cid: (round(float(avg), 1), int(n)) for cid, avg, n in rows}


def charger_out(
    c: Charger, ratings: dict | None = None, distance_km: float | None = None, for_host: bool = False
) -> schemas.ChargerOut:
    avg, n = (ratings or {}).get(c.id, (None, 0))
    model = schemas.ChargerHostOut if for_host else schemas.ChargerOut
    out = model.model_validate(c)
    out.rating_avg, out.rating_count = avg, n
    out.distance_km = round(distance_km, 2) if distance_km is not None else None
    out.host_name = (c.host.name or "Host") if c.host else "Host"
    return out


def booking_out(db: Session, b: Booking, viewer: User) -> schemas.BookingOut:
    out = schemas.BookingOut.model_validate(b)
    is_driver = viewer.id == b.driver_id
    other = b.host if is_driver else b.driver
    out.other_party_name = (other.name or ("Host" if is_driver else "Driver")) if other else ""
    shared = b.status in (BookingStatus.CONFIRMED, BookingStatus.ACTIVE)
    # contact details and access instructions are shared only while a booking is confirmed or active
    if shared or viewer.is_admin:
        out.other_party_phone = other.phone if other and not other.deleted_at else ""
        out.access_notes = b.charger.access_notes
    if b.status == BookingStatus.COMPLETED and not b.no_show:
        already = db.scalar(select(Review.id).where(Review.booking_id == b.id, Review.author_id == viewer.id))
        out.can_review = already is None and (is_driver or viewer.id == b.host_id)
    if b.payment:
        out.payment_order_id = b.payment.order_id
    return out
