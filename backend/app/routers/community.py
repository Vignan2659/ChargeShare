"""Reviews, problem reports and file uploads."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import Booking, BookingStatus, Report, Review, User
from ..security import get_current_user
from ..services import push, storage

router = APIRouter(tags=["community"])


@router.post("/reviews", status_code=201)
def add_review(body: schemas.ReviewIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    b = db.get(Booking, body.booking_id)
    if b is None or user.id not in (b.driver_id, b.host_id):
        raise HTTPException(404, "Booking not found")
    if b.status != BookingStatus.COMPLETED or b.no_show:
        raise HTTPException(400, "You can review only after a completed session")
    if db.scalar(select(Review.id).where(Review.booking_id == b.id, Review.author_id == user.id)):
        raise HTTPException(400, "You already reviewed this booking")
    is_driver = user.id == b.driver_id
    r = Review(
        booking_id=b.id,
        author_id=user.id,
        target_user_id=b.host_id if is_driver else b.driver_id,
        charger_id=b.charger_id if is_driver else None,  # only driver reviews count toward the charger rating
        rating=body.rating,
        comment=body.comment.strip(),
    )
    db.add(r)
    db.commit()
    return {"ok": True, "id": r.id}


@router.get("/users/{user_id}/rating")
def user_rating(user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Review.rating).where(Review.target_user_id == user_id)).all()
    return {"rating_avg": round(sum(rows) / len(rows), 1) if rows else None, "rating_count": len(rows)}


@router.post("/reports", response_model=schemas.ReportOut, status_code=201)
def report_problem(body: schemas.ReportIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.booking_id:
        b = db.get(Booking, body.booking_id)
        if b is None or user.id not in (b.driver_id, b.host_id):
            raise HTTPException(404, "Booking not found")
    r = Report(reporter_id=user.id, **body.model_dump())
    db.add(r)
    db.commit()
    for admin in db.scalars(select(User).where(User.is_admin.is_(True))).all():
        push.notify(admin, "New problem report", body.message[:100])
    return r


@router.get("/reports/mine", response_model=list[schemas.ReportOut])
def my_reports(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Report).where(Report.reporter_id == user.id).order_by(Report.created_at.desc())).all()


@router.post("/uploads", response_model=schemas.UploadOut)
async def upload(
    file: UploadFile = File(...),
    kind: str = Form("photo"),  # photo (public) | id_doc (private)
    user: User = Depends(get_current_user),
):
    if kind not in ("photo", "id_doc"):
        raise HTTPException(400, "kind must be photo or id_doc")
    data = await file.read()
    saved = storage.save(data, file.content_type or "", private=kind == "id_doc")
    return schemas.UploadOut(**saved)
