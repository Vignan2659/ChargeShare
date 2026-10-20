from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import schemas
from ..db import get_db
from ..models import Booking, BookingStatus, Charger, ChargerStatus, HostStatus, Review, User, utcnow
from ..security import get_current_user
from ..serializers import charger_out, charger_ratings
from ..services.timeutil import bounding_box, haversine_km

router = APIRouter(prefix="/chargers", tags=["chargers"])

# editing any of these sends an approved listing back for admin review
_REVIEWED_FIELDS = {"lat", "lng", "address", "connector_type", "power_kw", "photo_urls", "title"}


@router.get("/meta")
def meta():
    """Lists the app uses for pickers."""
    return {"connector_types": schemas.CONNECTOR_TYPES, "vehicle_types": schemas.VEHICLE_TYPES}


@router.get("", response_model=list[schemas.ChargerOut])
def search(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(5, gt=0, le=50),
    vehicle: str | None = None,
    connector: str | None = None,
    max_price_paise: int | None = None,
    pricing_mode: str | None = None,
    limit: int = Query(50, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    min_lat, max_lat, min_lng, max_lng = bounding_box(lat, lng, radius_km)
    q = (
        select(Charger)
        .join(User, Charger.host_id == User.id)
        .options(joinedload(Charger.host))
        .where(
            Charger.status == ChargerStatus.APPROVED,
            User.is_host.is_(True),
            User.deleted_at.is_(None),
            Charger.lat.between(min_lat, max_lat),
            Charger.lng.between(min_lng, max_lng),
        )
    )
    if connector:
        q = q.where(Charger.connector_type == connector)
    if max_price_paise:
        q = q.where(Charger.price_paise <= max_price_paise)
    if pricing_mode in ("hour", "kwh"):
        q = q.where(Charger.pricing_mode == pricing_mode)
    rows = db.scalars(q).unique().all()
    if vehicle:
        rows = [c for c in rows if vehicle in (c.vehicle_types or [])]

    with_dist = [(c, haversine_km(lat, lng, c.lat, c.lng)) for c in rows]
    with_dist = sorted([x for x in with_dist if x[1] <= radius_km], key=lambda x: x[1])[:limit]
    ratings = charger_ratings(db, [c.id for c, _ in with_dist])
    return [charger_out(c, ratings, d) for c, d in with_dist]


@router.get("/mine", response_model=list[schemas.ChargerHostOut])
def my_chargers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Charger)
        .where(Charger.host_id == user.id, Charger.status != ChargerStatus.REMOVED)
        .order_by(Charger.created_at.desc())
    ).all()
    ratings = charger_ratings(db, [c.id for c in rows])
    return [charger_out(c, ratings, for_host=True) for c in rows]


@router.get("/{charger_id}", response_model=schemas.ChargerDetail)
def detail(charger_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.get(Charger, charger_id)
    if c is None or (c.status != ChargerStatus.APPROVED and c.host_id != user.id and not user.is_admin):
        raise HTTPException(404, "Charger not found")
    base = charger_out(c, charger_ratings(db, [c.id]))
    now = utcnow()
    busy = db.scalars(
        select(Booking)
        .where(
            Booking.charger_id == c.id,
            Booking.status.in_(BookingStatus.BLOCKING),
            Booking.end_at > now,
            Booking.start_at < now + timedelta(days=14),
        )
        .order_by(Booking.start_at)
    ).all()
    reviews = db.scalars(
        select(Review).where(Review.charger_id == c.id).order_by(Review.created_at.desc()).limit(20)
    ).all()
    out = schemas.ChargerDetail(**base.model_dump())
    out.busy = [schemas.BusySlot(start_at=b.start_at, end_at=b.end_at) for b in busy]
    out.reviews = [
        schemas.ReviewOut(id=r.id, rating=r.rating, comment=r.comment, created_at=r.created_at, author_name=r.author.name or "Driver")
        for r in reviews
    ]
    return out


@router.get("/{charger_id}/manage", response_model=schemas.ChargerHostOut)
def manage_detail(charger_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _own(db, charger_id, user)
    return charger_out(c, charger_ratings(db, [c.id]), for_host=True)


@router.post("", response_model=schemas.ChargerHostOut, status_code=201)
def create(body: schemas.ChargerCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.host_status not in (HostStatus.PENDING, HostStatus.APPROVED):
        raise HTTPException(403, "Apply to become a host first (Profile → Become a host)")
    data = body.model_dump()
    if data["society_only"]:
        data["auto_accept"] = False  # host must confirm the driver is a resident
    c = Charger(host_id=user.id, status=ChargerStatus.PENDING, **data)
    db.add(c)
    db.commit()
    db.refresh(c)
    return charger_out(c, for_host=True)


@router.patch("/{charger_id}", response_model=schemas.ChargerHostOut)
def update(
    charger_id: int, body: schemas.ChargerUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    c = _own(db, charger_id, user)
    data = body.model_dump(exclude_none=True)
    paused = data.pop("paused", None)
    changed_reviewed = any(k in _REVIEWED_FIELDS and getattr(c, k) != v for k, v in data.items())
    for k, v in data.items():
        setattr(c, k, v)
    if c.society_only:
        c.auto_accept = False
    if changed_reviewed and c.status in (ChargerStatus.APPROVED, ChargerStatus.PAUSED, ChargerStatus.REJECTED):
        c.status = ChargerStatus.PENDING
        c.admin_note = "Changes waiting for review"
    if paused is True and c.status == ChargerStatus.APPROVED:
        c.status = ChargerStatus.PAUSED
    elif paused is False and c.status == ChargerStatus.PAUSED:
        c.status = ChargerStatus.APPROVED
    db.commit()
    return charger_out(c, charger_ratings(db, [c.id]), for_host=True)


@router.post("/{charger_id}/regenerate-qr", response_model=schemas.ChargerHostOut)
def regenerate_qr(charger_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..models import new_qr_token

    c = _own(db, charger_id, user)
    c.qr_token = new_qr_token()
    db.commit()
    return charger_out(c, for_host=True)


@router.delete("/{charger_id}")
def remove(charger_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _own(db, charger_id, user)
    open_count = db.scalar(
        select(Booking.id).where(Booking.charger_id == c.id, Booking.status.in_(BookingStatus.OPEN)).limit(1)
    )
    if open_count:
        raise HTTPException(400, "This charger has upcoming bookings. Cancel or finish them first.")
    c.status = ChargerStatus.REMOVED
    db.commit()
    return {"ok": True}


def _own(db: Session, charger_id: int, user: User) -> Charger:
    c = db.get(Charger, charger_id)
    if c is None or c.host_id != user.id or c.status == ChargerStatus.REMOVED:
        raise HTTPException(404, "Charger not found")
    return c
