from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..config import get_settings
from ..db import get_db
from ..models import User
from ..security import create_token
from ..services import otp

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/otp/request")
def request_code(body: schemas.OtpRequest, db: Session = Depends(get_db)):
    phone = otp.normalize_phone(body.phone)
    otp.request_otp(db, phone)
    return {"ok": True, "phone": phone}


@router.post("/otp/verify", response_model=schemas.TokenOut)
def verify_code(body: schemas.OtpVerify, db: Session = Depends(get_db)):
    phone = otp.normalize_phone(body.phone)
    otp.verify_otp(db, phone, body.code)

    user = db.scalar(select(User).where(User.phone == phone, User.deleted_at.is_(None)))
    is_new = user is None
    if user is None:
        user = User(phone=phone)
        db.add(user)
    if phone in get_settings().admin_phone_list:
        user.is_admin = True
    db.commit()
    db.refresh(user)
    return schemas.TokenOut(token=create_token(user.id), user=schemas.UserOut.model_validate(user), is_new=is_new)
