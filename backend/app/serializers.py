"""Turns database rows into API responses (adds ratings, reliability, distance, and who-sees-what)."""
import hashlib
import math

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from . import schemas
from .config import get_settings
from .models import Booking, BookingStatus, Charger, ExtraCharge, Review, User


def charger_ratings(db: Session, charger_ids: list[int]) -> dict[int, tuple[float, int]]:
    if not charger_ids:
        return {}
    rows = db.execute(
        select(Review.charger_id, func.avg(Review.rating), func.count(Review.id))
        .where(Review.charger_id.in_(charger_ids))
        .group_by(Review.charger_id)
    ).all()
    return {cid: (round(float(avg), 1), int(n)) for cid, avg, n in rows}


def charger_stats(db: Session, charger_ids: list[int]) -> dict[int, tuple[int, int]]:
    """(successful sessions, 'not working' reports) per charger."""
    if not charger_ids:
        return {}
    ok = case((Booking.status == BookingStatus.COMPLETED, case((Booking.no_show.is_(False), 1), else_=0)), else_=0)
    bad = case((Booking.charger_failed.is_(True), 1), else_=0)
    rows = db.execute(
        select(Booking.charger_id, func.sum(ok), func.sum(bad)).where(Booking.charger_id.in_(charger_ids)).group_by(Booking.charger_id)
    ).all()
    return {cid: (int(a or 0), int(b or 0)) for cid, a, b in rows}


def fuzz(c: Charger) -> tuple[float, float]:
    """Stable approximate position about `location_fuzz_meters` away, so the exact home isn't on a public map."""
    h = hashlib.sha256(f"charger-{c.id}-{c.created_at}".encode()).digest()
    angle = h[0] / 255 * 2 * math.pi
    dist_m = get_settings().location_fuzz_meters * (0.6 + 0.4 * h[1] / 255)
    dlat = dist_m * math.cos(angle) / 111_000
    dlng = dist_m * math.sin(angle) / (111_000 * max(math.cos(math.radians(c.lat)), 0.01))
    return round(c.lat + dlat, 5), round(c.lng + dlng, 5)


def charger_out(
    c: Charger,
    ratings: dict | None = None,
    distance_km: float | None = None,
    for_host: bool = False,
    stats: dict | None = None,
    exact: bool = False,
) -> schemas.ChargerOut:
    avg, n = (ratings or {}).get(c.id, (None, 0))
    model = schemas.ChargerHostOut if for_host else schemas.ChargerOut
    out = model.model_validate(c)
    out.rating_avg, out.rating_count = avg, n
    out.distance_km = round(distance_km, 2) if distance_km is not None else None
    out.host_name = (c.host.name or "Host") if c.host else "Host"
    out.community_name = c.community.name if c.community else ""
    ok, bad = (stats or {}).get(c.id, (0, 0))
    out.sessions_completed, out.failed_reports = ok, bad
    out.reliability_pct = round(100 * ok / (ok + bad)) if ok + bad >= 3 else None
    if not (for_host or exact):
        out.lat, out.lng = fuzz(c)
        out.address = c.area or "Exact address shown after booking"
        out.location_approximate = True
    return out


def has_confirmed_booking(db: Session, user: User, charger_id: int) -> bool:
    return db.scalar(
        select(Booking.id).where(
            Booking.charger_id == charger_id,
            Booking.driver_id == user.id,
            Booking.status.in_((BookingStatus.CONFIRMED, BookingStatus.ACTIVE)),
        )
    ) is not None


def booking_out(db: Session, b: Booking, viewer: User) -> schemas.BookingOut:
    out = schemas.BookingOut.model_validate(b)
    is_driver = viewer.id == b.driver_id
    other = b.host if is_driver else b.driver
    out.other_party_name = (other.name or ("Host" if is_driver else "Driver")) if other else ""
    shared = b.status in (BookingStatus.CONFIRMED, BookingStatus.ACTIVE)
    # contact details, exact location and access instructions are shared only while a booking is confirmed or active
    if shared or viewer.is_admin or viewer.id == b.host_id:
        out.other_party_phone = other.phone if other and shared and not other.deleted_at else ""
        out.access_notes = b.charger.access_notes if shared else ""
    else:
        lat, lng = fuzz(b.charger)
        out.charger.lat, out.charger.lng = lat, lng
        out.charger.address = b.charger.area or "Exact address shown after the host confirms"
    if viewer.is_admin:
        out.other_party_phone = other.phone if other else ""
    if b.status == BookingStatus.COMPLETED and not b.no_show:
        already = db.scalar(select(Review.id).where(Review.booking_id == b.id, Review.author_id == viewer.id))
        out.can_review = already is None and (is_driver or viewer.id == b.host_id)
    if b.payment:
        out.payment_order_id = b.payment.order_id
    out.extras = [schemas.ExtraOut.model_validate(x) for x in b.extras if x.status != "cancelled"]
    return out


def dues_total(db: Session, user: User) -> int:
    return int(
        db.scalar(select(func.coalesce(func.sum(ExtraCharge.amount_paise), 0)).where(ExtraCharge.user_id == user.id, ExtraCharge.status == "due"))
        or 0
    )
