"""Payment gateway wrapper.

PAYMENT_PROVIDER=mock    -> no real money; the app shows a "Pay (test)" button. Use while developing.
PAYMENT_PROVIDER=razorpay -> real Razorpay orders, checkout, signature checks and refunds.
"""
import hashlib
import hmac
import logging
import secrets

import httpx

from ..config import get_settings

log = logging.getLogger("payments")
RAZORPAY_API = "https://api.razorpay.com/v1"


class PaymentError(Exception):
    pass


def provider() -> str:
    return get_settings().payment_provider


def _auth() -> tuple[str, str]:
    s = get_settings()
    if not (s.razorpay_key_id and s.razorpay_key_secret):
        raise PaymentError("Razorpay keys are not configured")
    return (s.razorpay_key_id, s.razorpay_key_secret)


def create_order(amount_paise: int, receipt: str, notes: dict | None = None) -> str:
    if provider() == "mock":
        return f"mock_order_{secrets.token_hex(8)}"
    r = httpx.post(
        f"{RAZORPAY_API}/orders",
        auth=_auth(),
        json={"amount": amount_paise, "currency": "INR", "receipt": receipt, "notes": notes or {}},
        timeout=20,
    )
    if r.status_code >= 300:
        log.error("Razorpay order failed: %s %s", r.status_code, r.text)
        raise PaymentError("Could not start payment. Please try again.")
    return r.json()["id"]


def verify_checkout_signature(order_id: str, payment_id: str, signature: str) -> bool:
    secret = get_settings().razorpay_key_secret.encode()
    expected = hmac.new(secret, f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    secret = get_settings().razorpay_webhook_secret
    if not secret:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def fetch_order_paid_payment(order_id: str) -> str | None:
    """Return a captured payment id for this order, if Razorpay has one."""
    if provider() == "mock":
        return None
    r = httpx.get(f"{RAZORPAY_API}/orders/{order_id}/payments", auth=_auth(), timeout=20)
    if r.status_code >= 300:
        return None
    for item in r.json().get("items", []):
        if item.get("status") == "captured":
            return item["id"]
    return None


def refund(payment_id: str, amount_paise: int) -> str:
    if amount_paise <= 0:
        return ""
    if provider() == "mock" or payment_id.startswith("mock_"):
        return f"mock_rfnd_{secrets.token_hex(6)}"
    r = httpx.post(
        f"{RAZORPAY_API}/payments/{payment_id}/refund",
        auth=_auth(),
        json={"amount": amount_paise, "speed": "normal"},
        timeout=20,
    )
    if r.status_code >= 300:
        log.error("Razorpay refund failed: %s %s", r.status_code, r.text)
        raise PaymentError("Refund failed at the payment gateway")
    return r.json()["id"]
