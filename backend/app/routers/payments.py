"""Payment endpoints.

Razorpay flow (no native SDK needed, works in Expo):
  1. App creates a booking -> gets checkout_url
  2. App opens checkout_url in a WebView -> this server returns a tiny page that runs Razorpay Checkout
  3. On success the page POSTs to /payments/verify, which checks the signature and confirms the booking
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
from ..models import Booking, BookingStatus, Payment, PaymentStatus, User
from ..schemas import BookingOut, VerifyPaymentIn
from ..security import get_current_user
from ..serializers import booking_out
from ..services import booking_logic, payments

router = APIRouter(tags=["payments"])


def make_pay_token(booking_id: int) -> str:
    payload = {"bid": booking_id, "purpose": "pay", "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def _check_pay_token(token: str, booking_id: int) -> None:
    try:
        data = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Payment link expired. Go back and try again.")
    if data.get("purpose") != "pay" or data.get("bid") != booking_id:
        raise HTTPException(401, "Invalid payment link")


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
    url = ""
    if payments.provider() == "razorpay":
        url = f"{get_settings().public_base_url}/pay/{b.id}?t={make_pay_token(b.id)}"
    return {"provider": payments.provider(), "checkout_url": url, "amount_paise": b.amount_paise}


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
    return booking_out(db, b, user)


@router.get("/pay/{booking_id}", response_class=HTMLResponse)
def checkout_page(booking_id: int, t: str, db: Session = Depends(get_db)):
    _check_pay_token(t, booking_id)
    s = get_settings()
    b = db.get(Booking, booking_id)
    if b is None or b.payment is None:
        raise HTTPException(404, "Booking not found")
    if b.status != BookingStatus.PENDING_PAYMENT:
        return HTMLResponse(_result_page(s.app_scheme, b.id, "already"))

    options = {
        "key": s.razorpay_key_id,
        "amount": b.amount_paise,
        "currency": "INR",
        "name": s.app_name,
        "description": f"Charging at {b.charger.title}"[:250],
        "order_id": b.payment.order_id,
        "prefill": {"contact": b.driver.phone, "name": b.driver.name, "email": b.driver.email},
        "theme": {"color": "#0F9D58"},
    }
    return HTMLResponse(
        f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pay</title><style>body{{font-family:system-ui;padding:32px;text-align:center;color:#222}}
button{{background:#0F9D58;color:#fff;border:0;border-radius:10px;padding:14px 24px;font-size:16px}}</style>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script></head><body>
<h3>Paying ₹{b.amount_paise / 100:.2f}</h3><p>{html.escape(b.charger.title)}</p>
<p id="msg">Opening secure payment…</p><button onclick="pay()">Pay now</button>
<script>
const scheme = {_js(s.app_scheme)};
const bid = {b.id};
const opts = {_js(options)};
function go(status) {{ window.location.href = scheme + "://payment-result?booking=" + bid + "&status=" + status; }}
opts.handler = async function (r) {{
  document.getElementById("msg").innerText = "Confirming payment…";
  try {{
    const res = await fetch("/payments/verify?b=" + bid + "&t=" + encodeURIComponent({_js(t)}), {{
      method: "POST", headers: {{"content-type": "application/json"}}, body: JSON.stringify(r)
    }});
    go(res.ok ? "success" : "failed");
  }} catch (e) {{ go("pending"); }}
}};
opts.modal = {{ ondismiss: function () {{ go("cancelled"); }} }};
function pay() {{ const rz = new Razorpay(opts); rz.on("payment.failed", function () {{ go("failed"); }}); rz.open(); }}
window.onload = pay;
</script></body></html>"""
    )


def _js(value) -> str:
    """JSON for embedding inside a <script> tag (stops '</script>' tricks in user text)."""
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _result_page(scheme: str, booking_id: int, status: str) -> str:
    return f"<script>window.location.href='{scheme}://payment-result?booking={booking_id}&status={status}'</script>"


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


@router.post("/payments/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    """Set this URL in Razorpay Dashboard → Webhooks, events: payment.captured, refund.processed."""
    raw = await request.body()
    if not payments.verify_webhook_signature(raw, request.headers.get("x-razorpay-signature", "")):
        raise HTTPException(400, "Bad signature")
    event = json.loads(raw)
    if event.get("event") == "payment.captured":
        entity = event["payload"]["payment"]["entity"]
        pay = db.scalar(select(Payment).where(Payment.order_id == entity.get("order_id")))
        if pay is not None:
            booking_logic.mark_paid(db, pay.booking, entity["id"])
    return {"ok": True}
