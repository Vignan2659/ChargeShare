from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import schemas
from ..db import get_db
from ..models import (
    Booking,
    BookingStatus,
    Charger,
    ChargerStatus,
    Community,
    CommunityMember,
    HostStatus,
    Review,
    User,
    WaitlistEntry,
    new_qr_token,
    utcnow,
)
from ..security import get_current_user
from ..serializers import charger_out, charger_ratings, charger_stats, has_confirmed_booking
from ..services.booking_logic import is_member, overlapping
from ..services.timeutil import bounding_box, haversine_km, tz, within_open_hours

router = APIRouter(prefix="/chargers", tags=["chargers"])

# editing any of these sends an approved listing back for admin review
_REVIEWED_FIELDS = {"lat", "lng", "address", "connector_type", "power_kw", "photo_urls", "title"}


def _member_community_ids(db: Session, user: User) -> set[int]:
    ids = set(
        db.scalars(
            select(CommunityMember.community_id).where(CommunityMember.user_id == user.id, CommunityMember.status == "approved")
        ).all()
    )
    ids |= set(db.scalars(select(Community.id).where(Community.manager_id == user.id, Community.status == "approved")).all())
    return ids


def _free_now(db: Session, c: Charger, minutes: int = 60) -> bool:
    now = utcnow()
    if c.offline:
        return False
    if not within_open_hours(now, now + timedelta(minutes=minutes), c.open_time, c.close_time):
        return False
    return not overlapping(db, c.id, now, now + timedelta(minutes=minutes))


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
    available_now: bool = False,  # "I need to charge right now": open, online and free for the next hour
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
    # society chargers are visible only to approved residents (and their host)
    mine = _member_community_ids(db, user)
    rows = [c for c in rows if c.community_id is None or c.community_id in mine or c.host_id == user.id]

    with_dist = [(c, haversine_km(lat, lng, c.lat, c.lng)) for c in rows]
    with_dist = sorted([x for x in with_dist if x[1] <= radius_km], key=lambda x: x[1])
    free = {c.id: _free_now(db, c) for c, _ in with_dist}
    if available_now:
        with_dist = [x for x in with_dist if free[x[0].id]]
    with_dist = with_dist[:limit]
    ids = [c.id for c, _ in with_dist]
    ratings, stats = charger_ratings(db, ids), charger_stats(db, ids)
    out = []
    for c, d in with_dist:
        o = charger_out(c, ratings, d, stats=stats, exact=c.host_id == user.id)
        o.available_now = free[c.id]
        out.append(o)
    return out


@router.get("/mine", response_model=list[schemas.ChargerHostOut])
def my_chargers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Charger)
        .where(Charger.host_id == user.id, Charger.status != ChargerStatus.REMOVED)
        .order_by(Charger.created_at.desc())
    ).all()
    ids = [c.id for c in rows]
    ratings, stats = charger_ratings(db, ids), charger_stats(db, ids)
    return [charger_out(c, ratings, for_host=True, stats=stats) for c in rows]


@router.get("/waitlist/mine", response_model=list[schemas.WaitlistOut])
def my_waitlist(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today = datetime.now(tz()).strftime("%Y-%m-%d")
    rows = db.scalars(
        select(WaitlistEntry).where(WaitlistEntry.user_id == user.id, WaitlistEntry.day >= today).order_by(WaitlistEntry.day)
    ).all()
    out = []
    for w in rows:
        o = schemas.WaitlistOut.model_validate(w)
        c = db.get(Charger, w.charger_id)
        o.charger_title = c.title if c else ""
        out.append(o)
    return out


@router.get("/{charger_id}", response_model=schemas.ChargerDetail)
def detail(charger_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.get(Charger, charger_id)
    if c is None or (c.status != ChargerStatus.APPROVED and c.host_id != user.id and not user.is_admin):
        raise HTTPException(404, "Charger not found")
    if c.host_id != user.id and not user.is_admin and not is_member(db, user, c.community_id):
        raise HTTPException(404, "Charger not found")
    exact = c.host_id == user.id or user.is_admin or has_confirmed_booking(db, user, c.id)
    base = charger_out(c, charger_ratings(db, [c.id]), stats=charger_stats(db, [c.id]), exact=exact)
    base.available_now = _free_now(db, c)
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
    return charger_out(c, charger_ratings(db, [c.id]), for_host=True, stats=charger_stats(db, [c.id]))


def _check_community(db: Session, user: User, community_id: int | None) -> int | None:
    if not community_id:
        return None
    com = db.get(Community, community_id)
    if com is None or com.status != "approved":
        raise HTTPException(400, "That housing society isn't approved yet")
    if com.manager_id != user.id and not is_member(db, user, com.id):
        raise HTTPException(403, "Join the housing society (as an approved resident) before listing a charger in it")
    return com.id


@router.post("", response_model=schemas.ChargerHostOut, status_code=201)
def create(body: schemas.ChargerCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.host_status not in (HostStatus.PENDING, HostStatus.APPROVED):
        raise HTTPException(403, "Apply to become a host first (Profile → Become a host)")
    data = body.model_dump()
    data["community_id"] = _check_community(db, user, data.get("community_id"))
    if not data.get("offpeak_price_paise"):
        data["offpeak_price_paise"] = None
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
    if "community_id" in data:
        data["community_id"] = _check_community(db, user, data["community_id"])
    if data.get("offpeak_price_paise") == 0:
        data["offpeak_price_paise"] = None
        c.offpeak_price_paise = None
    if data.get("offline") is False:
        data["offline_reason"] = ""
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
    return charger_out(c, charger_ratings(db, [c.id]), for_host=True, stats=charger_stats(db, [c.id]))


@router.post("/{charger_id}/regenerate-qr", response_model=schemas.ChargerHostOut)
def regenerate_qr(charger_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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


# ---------- waitlist: "notify me if a slot opens" ----------
@router.post("/{charger_id}/waitlist", response_model=schemas.WaitlistOut, status_code=201)
def join_waitlist(charger_id: int, body: schemas.WaitlistIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.get(Charger, charger_id)
    if c is None or c.status != ChargerStatus.APPROVED or not is_member(db, user, c.community_id):
        raise HTTPException(404, "Charger not found")
    today = datetime.now(tz()).strftime("%Y-%m-%d")
    if body.day < today:
        raise HTTPException(400, "Pick today or a later day")
    w = db.scalar(select(WaitlistEntry).where(WaitlistEntry.user_id == user.id, WaitlistEntry.charger_id == c.id, WaitlistEntry.day == body.day))
    if w is None:
        w = WaitlistEntry(user_id=user.id, charger_id=c.id, day=body.day)
        db.add(w)
    else:
        w.notified_at = None
    db.commit()
    out = schemas.WaitlistOut.model_validate(w)
    out.charger_title = c.title
    return out


@router.delete("/{charger_id}/waitlist/{day}")
def leave_waitlist(charger_id: int, day: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    w = db.scalar(select(WaitlistEntry).where(WaitlistEntry.user_id == user.id, WaitlistEntry.charger_id == charger_id, WaitlistEntry.day == day))
    if w:
        db.delete(w)
        db.commit()
    return {"ok": True}


def _own(db: Session, charger_id: int, user: User) -> Charger:
    c = db.get(Charger, charger_id)
    if c is None or c.host_id != user.id or c.status == ChargerStatus.REMOVED:
        raise HTTPException(404, "Charger not found")
    return c
