"""Payment endpoints.

Razorpay flow (no native SDK needed, works in Expo):
  1. App creates a booking (or an extension / overstay due) -> gets checkout_url
  2. App opens checkout_url in a WebView -> this server returns a tiny page that runs Razorpay Checkout
  3. On success the page POSTs to /payments/verify, which checks the signature and records the payment
  4. The page then navigates to chargeshare://payment-result?... which the app's WebView intercepts
  The webhook (/payments/webhook) is a safety net in case the phone closes mid-payment.
"""
import html
import json
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Booking, BookingStatus, ExtraCharge, Payment, PaymentStatus, User
from ..schemas import BookingOut, ExtraCheckoutOut, ExtraOut, VerifyPaymentIn
from ..security import get_current_user
from ..serializers import booking_out
from ..services import booking_logic, payments

router = APIRouter(tags=["payments"])


# ---------- signed links for the checkout page (the WebView has no login header) ----------
def make_pay_token(booking_id: int, kind: str = "booking") -> str:
    payload = {"bid": booking_id, "kind": kind, "purpose": "pay", "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def _check_pay_token(token: str, ref_id: int, kind: str = "booking") -> None:
    try:
        data = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Payment link expired. Go back and try again.")
    if data.get("purpose") != "pay" or data.get("bid") != ref_id or data.get("kind", "booking") != kind:
        raise HTTPException(401, "Invalid payment link")


def checkout_url(ref_id: int, kind: str = "booking") -> str:
    if payments.provider() != "razorpay":
        return ""
    path = "pay" if kind == "booking" else "pay-extra"
    return f"{get_settings().public_base_url}/{path}/{ref_id}?t={make_pay_token(ref_id, kind)}"


def _js(value) -> str:
    """JSON for embedding inside a <script> tag (stops '</script>' tricks in user text)."""
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _result_page(scheme: str, ref: str, status: str) -> str:
    return f"<script>window.location.href='{scheme}://payment-result?{ref}&status={status}'</script>"


def _checkout_html(*, order_id: str, amount: int, description: str, title: str, user: User, verify_path: str, ref: str, token: str) -> str:
    s = get_settings()
    options = {
        "key": s.razorpay_key_id,
        "amount": amount,
        "currency": "INR",
        "name": s.app_name,
        "description": description[:250],
        "order_id": order_id,
        "prefill": {"contact": user.phone, "name": user.name, "email": user.email},
        "theme": {"color": "#0F9D58"},
    }
    return f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pay</title><style>body{{font-family:system-ui;padding:32px;text-align:center;color:#222}}
button{{background:#0F9D58;color:#fff;border:0;border-radius:10px;padding:14px 24px;font-size:16px}}</style>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script></head><body>
<h3>Paying ₹{amount / 100:.2f}</h3><p>{html.escape(title)}</p>
<p id="msg">Opening secure payment…</p><button onclick="pay()">Pay now</button>
<script>
const scheme = {_js(s.app_scheme)};
const ref = {_js(ref)};
const opts = {_js(options)};
function go(status) {{ window.location.href = scheme + "://payment-result?" + ref + "&status=" + status; }}
opts.handler = async function (r) {{
  document.getElementById("msg").innerText = "Confirming payment…";
  try {{
    const res = await fetch({_js(verify_path)} + "&t=" + encodeURIComponent({_js(token)}), {{
      method: "POST", headers: {{"content-type": "application/json"}}, body: JSON.stringify(r)
    }});
    go(res.ok ? "success" : "failed");
  }} catch (e) {{ go("pending"); }}
}};
opts.modal = {{ ondismiss: function () {{ go("cancelled"); }} }};
function pay() {{ const rz = new Razorpay(opts); rz.on("payment.failed", function () {{ go("failed"); }}); rz.open(); }}
window.onload = pay;
</script></body></html>"""


# ---------- main booking payment ----------
@router.post("/payments/{booking_id}/mock-pay", response_model=BookingOut)
def mock_pay(booking_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Test mode only: pretend the driver paid."""
    if payments.provider() != "mock":
        raise HTTPException(400, "Test payments are switched off")
    b = db.get(Booking, booking_id)
    if b is None or b.driver_id != user.id:
        raise HTTPException(404, "Booking not found")
    if b.status != BookingStatus.PENDING_PAYMENT:
        raise HTTPException(400, "This booking is not waiting for payment")
    booking_logic.mark_paid(db, b, provider_payment_id=f"mock_pay_{b.id}")
    return booking_out(db, b, user)


@router.post("/payments/{booking_id}/checkout")
def checkout_again(booking_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Fresh payment link for a booking that is still waiting for payment."""
    b = db.get(Booking, booking_id)
    if b is None or b.driver_id != user.id:
        raise HTTPException(404, "Booking not found")
    if b.status != BookingStatus.PENDING_PAYMENT:
        raise HTTPException(400, "This booking is not waiting for payment")
    return {"provider": payments.provider(), "checkout_url": checkout_url(b.id), "amount_paise": b.amount_paise}


@router.post("/payments/{booking_id}/sync", response_model=BookingOut)
def sync_payment(booking_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """App calls this after the payment screen closes, in case the webhook hasn't arrived yet."""
    b = db.get(Booking, booking_id)
    if b is None or b.driver_id != user.id:
        raise HTTPException(404, "Booking not found")
    if b.status == BookingStatus.PENDING_PAYMENT and b.payment and b.payment.status == PaymentStatus.CREATED:
        paid_id = payments.fetch_order_paid_payment(b.payment.order_id)
        if paid_id:
            booking_logic.mark_paid(db, b, paid_id)
    for x in b.extras:
        if x.status == "created" and x.order_id:
            paid_id = payments.fetch_order_paid_payment(x.order_id)
            if paid_id:
                booking_logic.mark_extra_paid(db, x, paid_id)
    return booking_out(db, b, user)


@router.get("/pay/{booking_id}", response_class=HTMLResponse)
def checkout_page(booking_id: int, t: str, db: Session = Depends(get_db)):
    _check_pay_token(t, booking_id)
    b = db.get(Booking, booking_id)
    if b is None or b.payment is None:
        raise HTTPException(404, "Booking not found")
    if b.status != BookingStatus.PENDING_PAYMENT:
        return HTMLResponse(_result_page(get_settings().app_scheme, f"booking={b.id}", "already"))
    return HTMLResponse(
        _checkout_html(
            order_id=b.payment.order_id, amount=b.amount_paise, description=f"Charging at {b.charger.title}",
            title=b.charger.title, user=b.driver, verify_path=f"/payments/verify?b={b.id}", ref=f"booking={b.id}", token=t,
        )
    )


@router.post("/payments/verify")
def verify(body: VerifyPaymentIn, b: int, t: str, db: Session = Depends(get_db)):
    _check_pay_token(t, b)
    booking = db.get(Booking, b)
    if booking is None or booking.payment is None or booking.payment.order_id != body.razorpay_order_id:
        raise HTTPException(400, "Order mismatch")
    if not payments.verify_checkout_signature(body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature):
        raise HTTPException(400, "Payment signature check failed")
    booking_logic.mark_paid(db, booking, body.razorpay_payment_id)
    return {"ok": True, "status": booking.status}


# ---------- extensions and overstay dues ----------
def _own_extra(db: Session, extra_id: int, user: User) -> ExtraCharge:
    x = db.get(ExtraCharge, extra_id)
    if x is None or x.user_id != user.id:
        raise HTTPException(404, "Payment not found")
    return x


@router.get("/payments/dues", response_model=list[ExtraOut])
def my_dues(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(ExtraCharge).where(ExtraCharge.user_id == user.id, ExtraCharge.status == "due")).all()


@router.post("/payments/extra/{extra_id}/checkout", response_model=ExtraCheckoutOut)
def extra_checkout(extra_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    x = _own_extra(db, extra_id, user)
    if x.status == "due":
        booking_logic.start_dues_payment(db, x)
    elif x.status != "created":
        raise HTTPException(400, "This is already paid")
    return ExtraCheckoutOut(extra=ExtraOut.model_validate(x), provider=payments.provider(), checkout_url=checkout_url(x.id, "extra"))


@router.post("/payments/extra/{extra_id}/mock-pay", response_model=ExtraOut)
def extra_mock_pay(extra_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payments.provider() != "mock":
        raise HTTPException(400, "Test payments are switched off")
    x = _own_extra(db, extra_id, user)
    if x.status not in ("created", "due"):
        raise HTTPException(400, "This is already paid")
    booking_logic.mark_extra_paid(db, x, f"mock_pay_extra_{x.id}")
    return x


@router.get("/pay-extra/{extra_id}", response_class=HTMLResponse)
def extra_checkout_page(extra_id: int, t: str, db: Session = Depends(get_db)):
    _check_pay_token(t, extra_id, "extra")
    x = db.get(ExtraCharge, extra_id)
    if x is None:
        raise HTTPException(404, "Payment not found")
    b = x.booking
    if x.status not in ("created", "due") or not x.order_id:
        return HTMLResponse(_result_page(get_settings().app_scheme, f"booking={b.id}&extra={x.id}", "already"))
    what = f"Extend booking by {x.minutes} min" if x.kind == "extension" else f"Overstay fee ({x.minutes} min)"
    return HTMLResponse(
        _checkout_html(
            order_id=x.order_id, amount=x.amount_paise, description=f"{what} at {b.charger.title}", title=what,
            user=b.driver, verify_path=f"/payments/extra/verify?x={x.id}", ref=f"booking={b.id}&extra={x.id}", token=t,
        )
    )


@router.post("/payments/extra/verify")
def extra_verify(body: VerifyPaymentIn, x: int, t: str, db: Session = Depends(get_db)):
    _check_pay_token(t, x, "extra")
    extra = db.get(ExtraCharge, x)
    if extra is None or extra.order_id != body.razorpay_order_id:
        raise HTTPException(400, "Order mismatch")
    if not payments.verify_checkout_signature(body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature):
        raise HTTPException(400, "Payment signature check failed")
    booking_logic.mark_extra_paid(db, extra, body.razorpay_payment_id)
    return {"ok": True, "status": extra.status}


# ---------- webhook ----------
@router.post("/payments/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    """Set this URL in Razorpay Dashboard → Webhooks, events: payment.captured."""
    raw = await request.body()
    if not payments.verify_webhook_signature(raw, request.headers.get("x-razorpay-signature", "")):
        raise HTTPException(400, "Bad signature")
    event = json.loads(raw)
    if event.get("event") == "payment.captured":
        entity = event["payload"]["payment"]["entity"]
        order_id = entity.get("order_id")
        pay = db.scalar(select(Payment).where(Payment.order_id == order_id))
        if pay is not None:
            booking_logic.mark_paid(db, pay.booking, entity["id"])
        else:
            extra = db.scalar(select(ExtraCharge).where(ExtraCharge.order_id == order_id))
            if extra is not None:
                booking_logic.mark_extra_paid(db, extra, entity["id"])
    return {"ok": True}
