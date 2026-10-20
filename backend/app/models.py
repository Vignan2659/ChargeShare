"""Database tables. Money is always stored in paise (1 rupee = 100 paise) as integers."""
import secrets
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Naive UTC timestamp (stored the same way in SQLite and Postgres)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_qr_token() -> str:
    return secrets.token_urlsafe(12)


# ---------- status values ----------
class HostStatus:
    NONE = "none"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ChargerStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAUSED = "paused"
    REMOVED = "removed"


class BookingStatus:
    PENDING_PAYMENT = "pending_payment"  # created, driver has not paid yet
    REQUESTED = "requested"  # paid, waiting for host to accept
    CONFIRMED = "confirmed"  # host accepted (or auto-accept)
    ACTIVE = "active"  # driver checked in at the charger
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    DECLINED = "declined"
    EXPIRED = "expired"

    BLOCKING = (PENDING_PAYMENT, REQUESTED, CONFIRMED, ACTIVE)  # these hold the time slot
    OPEN = (REQUESTED, CONFIRMED, ACTIVE)


class PaymentStatus:
    CREATED = "created"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


# ---------- tables ----------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_host: Mapped[bool] = mapped_column(Boolean, default=False)
    host_status: Mapped[str] = mapped_column(String(16), default=HostStatus.NONE)
    host_note: Mapped[str] = mapped_column(Text, default="")  # admin's reason when rejecting
    id_doc_keys: Mapped[list] = mapped_column(JSON, default=list)  # private file keys
    payout_upi: Mapped[str] = mapped_column(String(100), default="")
    vehicle_type: Mapped[str] = mapped_column(String(8), default="")  # 2W | 3W | 4W
    push_token: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    chargers: Mapped[list["Charger"]] = relationship(back_populates="host")


class Charger(Base):
    __tablename__ = "chargers"

    id: Mapped[int] = mapped_column(primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    address: Mapped[str] = mapped_column(String(300))
    access_notes: Mapped[str] = mapped_column(Text, default="")  # shown only after booking is confirmed
    lat: Mapped[float] = mapped_column(Float, index=True)
    lng: Mapped[float] = mapped_column(Float, index=True)
    vehicle_types: Mapped[list] = mapped_column(JSON, default=list)  # ["2W", "4W"]
    connector_type: Mapped[str] = mapped_column(String(40))
    power_kw: Mapped[float] = mapped_column(Float)
    pricing_mode: Mapped[str] = mapped_column(String(8), default="hour")  # hour | kwh
    price_paise: Mapped[int] = mapped_column(Integer)  # per hour or per kWh
    photo_urls: Mapped[list] = mapped_column(JSON, default=list)
    open_time: Mapped[str] = mapped_column(String(5), default="00:00")  # local HH:MM
    close_time: Mapped[str] = mapped_column(String(5), default="00:00")  # equal to open = 24 hours
    auto_accept: Mapped[bool] = mapped_column(Boolean, default=False)
    society_only: Mapped[bool] = mapped_column(Boolean, default=False)
    society_name: Mapped[str] = mapped_column(String(160), default="")
    has_society_noc: Mapped[bool] = mapped_column(Boolean, default=False)
    safety_checked: Mapped[bool] = mapped_column(Boolean, default=False)  # set by admin
    status: Mapped[str] = mapped_column(String(16), default=ChargerStatus.PENDING, index=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    qr_token: Mapped[str] = mapped_column(String(40), default=new_qr_token, unique=True)
    # --- added: gap-filling features ---
    area: Mapped[str] = mapped_column(String(120), default="")  # locality shown publicly instead of the full address
    offpeak_price_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)  # cheaper rate in a time window
    offpeak_start: Mapped[str] = mapped_column(String(5), default="22:00")
    offpeak_end: Mapped[str] = mapped_column(String(5), default="06:00")
    idle_fee_paise: Mapped[int] = mapped_column(Integer, default=0)  # per 15 min of overstay after the grace period
    offline: Mapped[bool] = mapped_column(Boolean, default=False)  # "temporarily unavailable"
    offline_reason: Mapped[str] = mapped_column(String(200), default="")
    community_id: Mapped[int | None] = mapped_column(ForeignKey("communities.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    host: Mapped[User] = relationship(back_populates="chargers")
    community: Mapped[Optional["Community"]] = relationship()


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    charger_id: Mapped[int] = mapped_column(ForeignKey("chargers.id"), index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    end_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    vehicle_type: Mapped[str] = mapped_column(String(8), default="")
    vehicle_note: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(20), default=BookingStatus.PENDING_PAYMENT, index=True)

    pricing_mode: Mapped[str] = mapped_column(String(8))
    unit_price_paise: Mapped[int] = mapped_column(Integer)
    amount_paise: Mapped[int] = mapped_column(Integer)  # charged upfront
    final_amount_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    refund_paise: Mapped[int] = mapped_column(Integer, default=0)
    commission_paise: Mapped[int] = mapped_column(Integer, default=0)
    host_earning_paise: Mapped[int] = mapped_column(Integer, default=0)
    kwh_used: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_show: Mapped[bool] = mapped_column(Boolean, default=False)

    cancel_reason: Mapped[str] = mapped_column(String(300), default="")
    cancelled_by: Mapped[str] = mapped_column(String(16), default="")  # driver | host | admin | system
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    payout_id: Mapped[int | None] = mapped_column(ForeignKey("payouts.id"), nullable=True, index=True)
    # --- added ---
    checklist: Mapped[dict] = mapped_column(JSON, default=dict)  # safety checklist ticked at check-in
    charger_failed: Mapped[bool] = mapped_column(Boolean, default=False)  # driver reported "charger not working"
    extended_minutes: Mapped[int] = mapped_column(Integer, default=0)
    overstay_minutes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    charger: Mapped[Charger] = relationship()
    driver: Mapped[User] = relationship(foreign_keys=[driver_id])
    host: Mapped[User] = relationship(foreign_keys=[host_id])
    payment: Mapped[Optional["Payment"]] = relationship(back_populates="booking", uselist=False)
    extras: Mapped[list["ExtraCharge"]] = relationship(back_populates="booking", order_by="ExtraCharge.id")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), unique=True)
    provider: Mapped[str] = mapped_column(String(16))
    order_id: Mapped[str] = mapped_column(String(80), index=True)
    provider_payment_id: Mapped[str] = mapped_column(String(80), default="")
    amount_paise: Mapped[int] = mapped_column(Integer)
    refunded_paise: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default=PaymentStatus.CREATED)
    refund_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    booking: Mapped[Booking] = relationship(back_populates="payment")


class ExtraCharge(Base):
    """Money collected after the main booking payment: slot extensions and overstay fees."""

    __tablename__ = "extra_charges"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)  # who pays (the driver)
    host_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # extension | overstay
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    amount_paise: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="created")  # created | due | paid | refunded | partially_refunded | cancelled
    provider: Mapped[str] = mapped_column(String(16), default="")
    order_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    provider_payment_id: Mapped[str] = mapped_column(String(80), default="")
    refunded_paise: Mapped[int] = mapped_column(Integer, default=0)
    refund_ids: Mapped[list] = mapped_column(JSON, default=list)
    commission_paise: Mapped[int] = mapped_column(Integer, default=0)  # overstay only (extensions roll into the booking)
    host_earning_paise: Mapped[int] = mapped_column(Integer, default=0)
    payout_id: Mapped[int | None] = mapped_column(ForeignKey("payouts.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    booking: Mapped[Booking] = relationship(back_populates="extras")


class Community(Base):
    """A housing society / apartment complex. Its chargers are visible only to approved residents."""

    __tablename__ = "communities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    address: Mapped[str] = mapped_column(String(300))
    code: Mapped[str] = mapped_column(String(12), unique=True, index=True)  # residents join with this
    manager_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | rejected (by admin)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    manager: Mapped[User] = relationship()


class CommunityMember(Base):
    __tablename__ = "community_members"
    __table_args__ = (UniqueConstraint("community_id", "user_id", name="uq_member_once"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    flat: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship()
    community: Mapped[Community] = relationship()


class WaitlistEntry(Base):
    """'Notify me if a slot opens' for one charger on one local day."""

    __tablename__ = "waitlist"
    __table_args__ = (UniqueConstraint("user_id", "charger_id", "day", name="uq_wait_once"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    charger_id: Mapped[int] = mapped_column(ForeignKey("chargers.id"), index=True)
    day: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD, local
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship()


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("booking_id", "author_id", name="uq_review_once"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    target_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    charger_id: Mapped[int | None] = mapped_column(ForeignKey("chargers.id"), nullable=True, index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    author: Mapped[User] = relationship(foreign_keys=[author_id])


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), nullable=True)
    charger_id: Mapped[int | None] = mapped_column(ForeignKey("chargers.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(40), default="other")
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | resolved
    admin_reply: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    reporter: Mapped[User] = relationship()


class Payout(Base):
    __tablename__ = "payouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount_paise: Mapped[int] = mapped_column(Integer)
    booking_count: Mapped[int] = mapped_column(Integer, default=0)
    upi_id: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | paid
    reference: Mapped[str] = mapped_column(String(120), default="")  # UTR / transaction id
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    host: Mapped[User] = relationship()


class OtpCode(Base):
    __tablename__ = "otp_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
