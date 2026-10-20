"""Request and response shapes. Money fields ending in _paise are integers (₹1 = 100 paise)."""
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

CONNECTOR_TYPES = [
    "15A socket",
    "Type 2 (AC)",
    "CCS2 (DC)",
    "Bharat AC-001",
    "Bharat DC-001",
    "LECCS (2W)",
    "Ather connector",
    "Other",
]
VEHICLE_TYPES = ["2W", "3W", "4W"]
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _check_vehicle_types(v):
    bad = [x for x in v if x not in VEHICLE_TYPES]
    if bad:
        raise ValueError(f"Unknown vehicle types: {bad}")
    if not v:
        raise ValueError("Pick at least one vehicle type")
    return sorted(set(v))


def _check_connector(v):
    if v not in CONNECTOR_TYPES:
        raise ValueError(f"connector_type must be one of {CONNECTOR_TYPES}")
    return v


def _check_pricing_mode(v):
    if v not in ("hour", "kwh"):
        raise ValueError("pricing_mode must be hour or kwh")
    return v


def _check_hhmm(v):
    if not _HHMM.match(v):
        raise ValueError("Use 24-hour HH:MM, e.g. 07:30")
    return v


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------
class OtpRequest(BaseModel):
    phone: str


class OtpVerify(BaseModel):
    phone: str
    code: str = Field(min_length=4, max_length=8)


class TokenOut(BaseModel):
    token: str
    user: "UserOut"
    is_new: bool


# ---------- users ----------
class UserOut(ORM):
    id: int
    phone: str
    name: str
    email: str
    is_admin: bool
    is_host: bool
    host_status: str
    host_note: str
    payout_upi: str
    vehicle_type: str
    created_at: datetime


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=200)
    vehicle_type: str | None = None
    push_token: str | None = Field(default=None, max_length=200)

    @field_validator("vehicle_type")
    @classmethod
    def _vt(cls, v):
        if v not in (None, "", *VEHICLE_TYPES):
            raise ValueError("vehicle_type must be 2W, 3W or 4W")
        return v


class HostApplication(BaseModel):
    id_doc_keys: list[str] = Field(min_length=1, max_length=4)
    payout_upi: str = Field(min_length=5, max_length=100)

    @field_validator("payout_upi")
    @classmethod
    def _upi(cls, v: str):
        if not re.match(r"^[\w.\-]{2,}@[a-zA-Z]{2,}$", v.strip()):
            raise ValueError("Enter a valid UPI ID, like name@okaxis")
        return v.strip()


class PublicUser(ORM):
    id: int
    name: str


# ---------- chargers ----------
class ChargerBase(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=2000)
    address: str = Field(min_length=5, max_length=300)
    access_notes: str = Field(default="", max_length=1000)
    lat: float = Field(ge=6, le=37)  # India bounds
    lng: float = Field(ge=68, le=98)
    vehicle_types: list[str] = Field(min_length=1)
    connector_type: str
    power_kw: float = Field(gt=0, le=350)
    pricing_mode: str = "hour"
    price_paise: int = Field(gt=0, le=1_000_000)
    photo_urls: list[str] = Field(default_factory=list, max_length=6)
    open_time: str = "00:00"
    close_time: str = "00:00"
    auto_accept: bool = False
    society_only: bool = False
    society_name: str = Field(default="", max_length=160)
    has_society_noc: bool = False

    @field_validator("vehicle_types")
    @classmethod
    def _vts(cls, v):
        return _check_vehicle_types(v)

    @field_validator("connector_type")
    @classmethod
    def _ct(cls, v):
        return _check_connector(v)

    @field_validator("pricing_mode")
    @classmethod
    def _pm(cls, v):
        return _check_pricing_mode(v)

    @field_validator("open_time", "close_time")
    @classmethod
    def _hhmm(cls, v):
        return _check_hhmm(v)


class ChargerCreate(ChargerBase):
    pass


class ChargerUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    address: str | None = Field(default=None, min_length=5, max_length=300)
    access_notes: str | None = Field(default=None, max_length=1000)
    lat: float | None = Field(default=None, ge=6, le=37)
    lng: float | None = Field(default=None, ge=68, le=98)
    vehicle_types: list[str] | None = None
    connector_type: str | None = None
    power_kw: float | None = Field(default=None, gt=0, le=350)
    pricing_mode: str | None = None
    price_paise: int | None = Field(default=None, gt=0, le=1_000_000)
    photo_urls: list[str] | None = Field(default=None, max_length=6)
    open_time: str | None = None
    close_time: str | None = None
    auto_accept: bool | None = None
    society_only: bool | None = None
    society_name: str | None = Field(default=None, max_length=160)
    has_society_noc: bool | None = None
    paused: bool | None = None

    @field_validator("vehicle_types")
    @classmethod
    def _vts(cls, v):
        return v if v is None else _check_vehicle_types(v)

    @field_validator("connector_type")
    @classmethod
    def _ct(cls, v):
        return v if v is None else _check_connector(v)

    @field_validator("pricing_mode")
    @classmethod
    def _pm(cls, v):
        return v if v is None else _check_pricing_mode(v)

    @field_validator("open_time", "close_time")
    @classmethod
    def _hhmm(cls, v):
        return v if v is None else _check_hhmm(v)


class ChargerOut(ORM):
    id: int
    host_id: int
    title: str
    description: str
    address: str
    lat: float
    lng: float
    vehicle_types: list[str]
    connector_type: str
    power_kw: float
    pricing_mode: str
    price_paise: int
    photo_urls: list[str]
    open_time: str
    close_time: str
    auto_accept: bool
    society_only: bool
    society_name: str
    safety_checked: bool
    status: str
    distance_km: float | None = None
    rating_avg: float | None = None
    rating_count: int = 0
    host_name: str = ""


class ChargerHostOut(ChargerOut):
    access_notes: str
    has_society_noc: bool
    admin_note: str
    qr_token: str
    created_at: datetime


class BusySlot(BaseModel):
    start_at: datetime
    end_at: datetime


class ReviewOut(ORM):
    id: int
    rating: int
    comment: str
    created_at: datetime
    author_name: str = ""


class ChargerDetail(ChargerOut):
    busy: list[BusySlot] = []
    reviews: list[ReviewOut] = []


# ---------- bookings ----------
class QuoteIn(BaseModel):
    charger_id: int
    start_at: datetime
    end_at: datetime


class QuoteOut(BaseModel):
    amount_paise: int
    minutes: int
    pricing_mode: str
    note: str


class BookingCreate(QuoteIn):
    vehicle_type: str = ""
    vehicle_note: str = Field(default="", max_length=120)


class ChargerSummary(ORM):
    id: int
    title: str
    address: str
    lat: float
    lng: float
    connector_type: str
    power_kw: float
    photo_urls: list[str]


class BookingOut(ORM):
    id: int
    charger_id: int
    driver_id: int
    host_id: int
    start_at: datetime
    end_at: datetime
    vehicle_type: str
    vehicle_note: str
    status: str
    pricing_mode: str
    unit_price_paise: int
    amount_paise: int
    final_amount_paise: int | None
    refund_paise: int
    commission_paise: int
    host_earning_paise: int
    kwh_used: float | None
    no_show: bool
    cancel_reason: str
    cancelled_by: str
    created_at: datetime
    checked_in_at: datetime | None
    completed_at: datetime | None
    charger: ChargerSummary
    # filled in by the API depending on who is asking:
    other_party_name: str = ""
    other_party_phone: str = ""
    access_notes: str = ""
    can_review: bool = False
    payment_order_id: str = ""


class CheckoutOut(BaseModel):
    booking: BookingOut
    provider: str  # mock | razorpay
    checkout_url: str  # open in a WebView (razorpay) — empty for mock


class CancelIn(BaseModel):
    reason: str = Field(default="", max_length=300)


class CheckInIn(BaseModel):
    qr_token: str


class CompleteIn(BaseModel):
    kwh_used: float | None = None


class VerifyPaymentIn(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# ---------- reviews & reports ----------
class ReviewIn(BaseModel):
    booking_id: int
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


class ReportIn(BaseModel):
    booking_id: int | None = None
    charger_id: int | None = None
    category: str = Field(default="other", max_length=40)
    message: str = Field(min_length=5, max_length=3000)


class ReportOut(ORM):
    id: int
    reporter_id: int
    booking_id: int | None
    charger_id: int | None
    category: str
    message: str
    status: str
    admin_reply: str
    created_at: datetime


# ---------- earnings & payouts ----------
class EarningsOut(BaseModel):
    completed_sessions: int
    total_earned_paise: int
    this_month_paise: int
    pending_payout_paise: int
    paid_out_paise: int
    upcoming_bookings: int


class PayoutOut(ORM):
    id: int
    host_id: int
    amount_paise: int
    booking_count: int
    upi_id: str
    status: str
    reference: str
    created_at: datetime
    paid_at: datetime | None
    host_name: str = ""
    host_phone: str = ""


class UploadOut(BaseModel):
    key: str
    url: str | None


TokenOut.model_rebuild()
