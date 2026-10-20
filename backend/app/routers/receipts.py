"""Printable receipt for a booking: every rupee in and out, in one place."""
import html

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Booking
from ..services.timeutil import tz, utc_naive_to_aware
from .payments import _check_pay_token

router = APIRouter(tags=["receipts"])


def _rs(p: int | None) -> str:
    return f"₹{(p or 0) / 100:,.2f}"


def _local(dt) -> str:
    return utc_naive_to_aware(dt).astimezone(tz()).strftime("%d %b %Y, %I:%M %p") if dt else "—"


@router.get("/receipts/{booking_id}", response_class=HTMLResponse)
def receipt(booking_id: int, t: str, db: Session = Depends(get_db)):
    _check_pay_token(t, booking_id, "receipt")
    b = db.get(Booking, booking_id)
    if b is None:
        raise HTTPException(404, "Booking not found")
    s, c = get_settings(), b.charger
    rows = [("Booked slot", f"{_local(b.start_at)} – {_local(b.end_at)}")]
    if b.extended_minutes:
        rows.append(("Extended by", f"{b.extended_minutes} min"))
    rows += [
        ("Charger", f"{c.title} ({c.connector_type}, {c.power_kw} kW)"),
        ("Location", c.area or "—"),
        ("Pricing", f"{_rs(b.unit_price_paise)} per {'kWh' if b.pricing_mode == 'kwh' else 'hour'}"),
    ]
    if b.kwh_used is not None:
        rows.append(("Energy used", f"{b.kwh_used} kWh"))
    money = [("Paid upfront", _rs(b.amount_paise)), ("Refunded", _rs(b.refund_paise))]
    for x in b.extras:
        if x.kind == "overstay":
            money.append((f"Overstay fee ({x.minutes} min) – {x.status}", _rs(x.amount_paise)))
    if b.final_amount_paise is not None:
        money.append(("Charging cost", _rs(b.final_amount_paise)))
        money.append((f"  of which {s.app_name} service fee ({s.commission_percent:.0f}%)", _rs(b.commission_paise)))
        money.append(("  of which paid to the host", _rs(b.host_earning_paise)))
    table = "".join(f"<tr><td>{html.escape(k)}</td><td>{html.escape(v)}</td></tr>" for k, v in rows)
    mtable = "".join(f"<tr><td>{html.escape(k)}</td><td class='r'>{html.escape(v)}</td></tr>" for k, v in money)
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Receipt #{b.id}</title><style>body{{font-family:system-ui;max-width:560px;margin:0 auto;padding:24px;color:#1b1f23}}
h1{{color:#0b7a44;margin:0}}table{{width:100%;border-collapse:collapse;margin:16px 0}}td{{padding:8px 0;border-bottom:1px solid #e3e7eb;vertical-align:top}}
.r{{text-align:right;font-variant-numeric:tabular-nums}}.muted{{color:#5f6b76;font-size:13px}}</style></head><body>
<h1>{html.escape(s.app_name)}</h1><p class="muted">Receipt for booking #{b.id} · status: {html.escape(b.status)}</p>
<p>Driver: {html.escape(b.driver.name)} · Host: {html.escape(b.host.name)}</p>
<table>{table}</table><table>{mtable}</table>
<p class="muted">Prices include applicable taxes. Payments processed by Razorpay. Issued by [YOUR BUSINESS NAME], GSTIN [YOUR GSTIN].
Questions? Reply from the app: Booking → Report a problem.</p></body></html>"""
    )
