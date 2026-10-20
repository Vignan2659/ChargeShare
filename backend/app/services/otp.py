"""Phone OTP login.

OTP_PROVIDER=console -> the code is printed in the server log (for development).
OTP_PROVIDER=msg91   -> the code is sent by SMS through MSG91 (needs a DLT-approved template in India).
"""
import hashlib
import logging
import re
import secrets
from datetime import timedelta

import httpx
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import OtpCode, utcnow

log = logging.getLogger("otp")
OTP_TTL_MINUTES = 10
MAX_ATTEMPTS = 5
MAX_REQUESTS_PER_HOUR = 5


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        digits = "91" + digits
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return "+" + digits
    raise HTTPException(400, "Enter a valid 10-digit Indian mobile number")


def _hash(phone: str, code: str) -> str:
    return hashlib.sha256(f"{phone}:{code}:{get_settings().jwt_secret}".encode()).hexdigest()


def request_otp(db: Session, phone: str) -> None:
    s = get_settings()
    if s.demo_phone and phone == s.demo_phone:
        return  # reviewers use the fixed demo OTP
    hour_ago = utcnow() - timedelta(hours=1)
    recent = db.scalar(
        select(func.count()).select_from(OtpCode).where(OtpCode.phone == phone, OtpCode.created_at > hour_ago)
    )
    if recent >= MAX_REQUESTS_PER_HOUR:
        raise HTTPException(429, "Too many OTP requests. Try again in an hour.")

    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(OtpCode(phone=phone, code_hash=_hash(phone, code), expires_at=utcnow() + timedelta(minutes=OTP_TTL_MINUTES)))
    db.commit()
    _send(phone, code)


def verify_otp(db: Session, phone: str, code: str) -> None:
    s = get_settings()
    if s.demo_phone and s.demo_otp and phone == s.demo_phone:
        if code == s.demo_otp:
            return
        raise HTTPException(400, "Wrong OTP")

    otp = db.scalars(
        select(OtpCode)
        .where(OtpCode.phone == phone, OtpCode.used.is_(False))
        .order_by(OtpCode.created_at.desc())
    ).first()
    if otp is None or otp.expires_at < utcnow():
        raise HTTPException(400, "OTP expired. Request a new one.")
    if otp.attempts >= MAX_ATTEMPTS:
        raise HTTPException(400, "Too many wrong attempts. Request a new OTP.")
    if otp.code_hash != _hash(phone, code.strip()):
        otp.attempts += 1
        db.commit()
        raise HTTPException(400, "Wrong OTP")
    otp.used = True
    db.commit()


def _send(phone: str, code: str) -> None:
    s = get_settings()
    if s.otp_provider == "msg91":
        # MSG91 OTP API v5: we generate the code ourselves and pass it in.
        r = httpx.post(
            "https://control.msg91.com/api/v5/otp",
            params={"template_id": s.msg91_template_id, "mobile": phone.lstrip("+"), "otp": code},
            headers={"authkey": s.msg91_auth_key, "accept": "application/json"},
            timeout=15,
        )
        if r.status_code >= 300 or r.json().get("type") == "error":
            log.error("MSG91 failed: %s %s", r.status_code, r.text)
            raise HTTPException(502, "Could not send OTP. Please try again.")
        return
    # console provider: development only
    log.warning("OTP for %s is %s", phone, code)
    print(f"\n*** OTP for {phone}: {code} ***\n", flush=True)
