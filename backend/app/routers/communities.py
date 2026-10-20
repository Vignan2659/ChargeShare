"""Housing societies: residents-only chargers and a fair monthly usage statement per flat.

Fills a real gap: many societies block EV charging or fight over who pays for power from the common meter.
A society manager creates the community (admin approves it), residents join with a code + their flat number,
the manager approves them, and chargers listed "in" the community are visible and bookable only by residents.
"""
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import Booking, BookingStatus, Charger, Community, CommunityMember, User
from ..security import get_current_user
from ..services import push
from ..services.timeutil import to_utc_naive, tz

router = APIRouter(prefix="/communities", tags=["communities"])


def _code() -> str:
    return "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))


def community_out(db: Session, c: Community, user: User | None = None) -> schemas.CommunityOut:
    out = schemas.CommunityOut.model_validate(c)
    out.members_count = db.scalar(
        select(func.count()).select_from(CommunityMember).where(CommunityMember.community_id == c.id, CommunityMember.status == "approved")
    ) or 0
    out.chargers_count = db.scalar(select(func.count()).select_from(Charger).where(Charger.community_id == c.id)) or 0
    if user is not None:
        out.role = "manager" if c.manager_id == user.id else "member"
        m = db.scalar(select(CommunityMember).where(CommunityMember.community_id == c.id, CommunityMember.user_id == user.id))
        out.my_status = m.status if m else ("approved" if c.manager_id == user.id else "")
    if user is not None and c.manager_id != user.id:
        out.code = ""  # only the manager shares the join code
    return out


def _managed(db: Session, community_id: int, user: User) -> Community:
    c = db.get(Community, community_id)
    if c is None or (c.manager_id != user.id and not user.is_admin):
        raise HTTPException(404, "Society not found")
    return c


@router.post("", response_model=schemas.CommunityOut, status_code=201)
def create(body: schemas.CommunityCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Usually created by the RWA secretary or facility manager. Goes live after admin approval."""
    code = _code()
    while db.scalar(select(Community.id).where(Community.code == code)):
        code = _code()
    c = Community(name=body.name.strip(), address=body.address.strip(), code=code, manager_id=user.id)
    db.add(c)
    db.flush()
    db.add(CommunityMember(community_id=c.id, user_id=user.id, flat=body.manager_flat.strip(), status="approved"))
    db.commit()
    for admin in db.scalars(select(User).where(User.is_admin.is_(True))).all():
        push.notify(admin, "New housing society", f"{c.name} wants to join ChargeShare")
    return community_out(db, c, user)


@router.get("/mine", response_model=list[schemas.CommunityOut])
def mine(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ids = set(db.scalars(select(CommunityMember.community_id).where(CommunityMember.user_id == user.id)).all())
    ids |= set(db.scalars(select(Community.id).where(Community.manager_id == user.id)).all())
    rows = db.scalars(select(Community).where(Community.id.in_(ids)).order_by(Community.name)).all() if ids else []
    return [community_out(db, c, user) for c in rows]


@router.post("/join", response_model=schemas.CommunityOut)
def join(body: schemas.JoinIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.scalar(select(Community).where(Community.code == body.code.strip().upper()))
    if c is None or c.status != "approved":
        raise HTTPException(404, "No approved society with that code. Ask your society manager for it.")
    m = db.scalar(select(CommunityMember).where(CommunityMember.community_id == c.id, CommunityMember.user_id == user.id))
    if m is None:
        m = CommunityMember(community_id=c.id, user_id=user.id, flat=body.flat.strip())
        db.add(m)
    elif m.status == "rejected":
        m.status, m.flat = "pending", body.flat.strip()
    db.commit()
    push.notify(c.manager, "New resident request", f"{user.name or user.phone} (flat {m.flat}) wants to join {c.name}")
    return community_out(db, c, user)


@router.get("/{community_id}/members", response_model=list[schemas.MemberOut])
def members(community_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _managed(db, community_id, user)
    rows = db.scalars(select(CommunityMember).where(CommunityMember.community_id == c.id).order_by(CommunityMember.status, CommunityMember.flat)).all()
    out = []
    for m in rows:
        o = schemas.MemberOut.model_validate(m)
        o.name, o.phone = m.user.name, m.user.phone
        out.append(o)
    return out


@router.post("/{community_id}/members/{member_id}/{action}", response_model=schemas.MemberOut)
def decide(community_id: int, member_id: int, action: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = _managed(db, community_id, user)
    m = db.get(CommunityMember, member_id)
    if m is None or m.community_id != c.id:
        raise HTTPException(404, "Resident not found")
    if action not in ("approve", "reject", "remove"):
        raise HTTPException(400, "Action must be approve, reject or remove")
    if m.user_id == c.manager_id:
        raise HTTPException(400, "The manager can't be removed")
    m.status = "approved" if action == "approve" else "rejected"
    db.commit()
    push.notify(m.user, c.name, "You're in! Society chargers now show up on your map." if action == "approve" else "Your request to join was not approved.")
    o = schemas.MemberOut.model_validate(m)
    o.name, o.phone = m.user.name, m.user.phone
    return o


@router.get("/{community_id}/statement", response_model=schemas.StatementOut)
def statement(
    community_id: int,
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Per-flat usage for one month across the society's chargers: who used how much, for fair cost-sharing."""
    c = _managed(db, community_id, user)
    month = month or datetime.now(tz()).strftime("%Y-%m")
    y, mo = map(int, month.split("-"))
    start = to_utc_naive(datetime(y, mo, 1, tzinfo=tz()))
    end = to_utc_naive(datetime(y + (mo == 12), 1 if mo == 12 else mo + 1, 1, tzinfo=tz()))
    flats = {m.user_id: m for m in db.scalars(select(CommunityMember).where(CommunityMember.community_id == c.id)).all()}
    rows = db.scalars(
        select(Booking)
        .join(Charger, Booking.charger_id == Charger.id)
        .where(Charger.community_id == c.id, Booking.status == BookingStatus.COMPLETED, Booking.start_at >= start, Booking.start_at < end)
    ).all()
    agg: dict[int, dict] = {}
    for b in rows:
        a = agg.setdefault(b.driver_id, {"sessions": 0, "kwh": 0.0, "minutes": 0, "amount": 0})
        minutes = int((b.end_at - b.start_at).total_seconds() // 60)
        a["sessions"] += 1
        a["minutes"] += minutes
        # hourly sessions have no meter reading: estimate energy from charger power × time
        a["kwh"] += b.kwh_used if b.kwh_used is not None else round(b.charger.power_kw * minutes / 60, 2)
        a["amount"] += b.final_amount_paise or 0
    out_rows = []
    for uid, a in sorted(agg.items(), key=lambda kv: flats.get(kv[0]).flat if flats.get(kv[0]) else "zzz"):
        m = flats.get(uid)
        out_rows.append(
            schemas.StatementRow(
                flat=m.flat if m else "Not a resident", name=m.user.name if m else "", sessions=a["sessions"],
                kwh=round(a["kwh"], 2), minutes=a["minutes"], amount_paise=a["amount"],
            )
        )
    return schemas.StatementOut(
        community=c.name, month=month, rows=out_rows,
        total_kwh=round(sum(r.kwh for r in out_rows), 2), total_amount_paise=sum(r.amount_paise for r in out_rows),
    )
