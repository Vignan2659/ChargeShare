"""End-to-end tests of the main flows.  Run:  pytest -q"""
import os
import tempfile
from datetime import datetime, timedelta, timezone

_tmp = tempfile.mkdtemp()
os.environ.update(
    DATABASE_URL=f"sqlite:///{_tmp}/test.db",
    PAYMENT_PROVIDER="mock",
    OTP_PROVIDER="console",
    PUSH_ENABLED="false",
    ADMIN_PHONES="+919000000001",
    LOCAL_UPLOAD_DIR=f"{_tmp}/uploads",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import otp as otp_service  # noqa: E402

SENT: dict[str, str] = {}
otp_service._send = lambda phone, code: SENT.__setitem__(phone, code)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def login(client, phone, name=None):
    r = client.post("/auth/otp/request", json={"phone": phone})
    assert r.status_code == 200, r.text
    norm = r.json()["phone"]
    r = client.post("/auth/otp/verify", json={"phone": phone, "code": SENT[norm]})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    if name:
        assert client.patch("/me", json={"name": name, "vehicle_type": "4W"}, headers=h).status_code == 200
    return h


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def slot(hours_from_now=3, length=2):
    # round to the next hour so times are clean
    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=hours_from_now)
    return iso(base), iso(base + timedelta(hours=length))


CHECKS = {"cable_ok": True, "connector_matches": True, "area_dry": True}

CHARGER = {
    "title": "Test Villa Charger",
    "address": "Road 1, Gachibowli, Hyderabad",
    "lat": 17.44,
    "lng": 78.35,
    "vehicle_types": ["4W", "2W"],
    "connector_type": "Type 2 (AC)",
    "power_kw": 7.4,
    "pricing_mode": "hour",
    "price_paise": 10000,
    "open_time": "00:00",
    "close_time": "00:00",
    "access_notes": "Gate 2, slot B-12",
}


@pytest.fixture(scope="module")
def world(client):
    admin = login(client, "9000000001", "Admin")
    host = login(client, "9000000002", "Ravi")
    driver = login(client, "+91 90000 00003", "Priya")

    # bad phone rejected
    assert client.post("/auth/otp/request", json={"phone": "12345"}).status_code == 400

    # host uploads ID, applies, admin approves
    up = client.post("/uploads", files={"file": ("id.png", b"\x89PNG fake", "image/png")}, data={"kind": "id_doc"}, headers=host)
    assert up.status_code == 200, up.text
    key = up.json()["key"]
    assert up.json()["url"] is None  # private
    r = client.post("/me/host-application", json={"id_doc_keys": [key], "payout_upi": "ravi@okaxis"}, headers=host)
    assert r.json()["host_status"] == "pending"
    assert client.get("/admin/stats", headers=host).status_code == 403
    pending = client.get("/admin/users?host_status=pending", headers=admin).json()
    host_id = pending[0]["id"]
    assert client.get(f"/admin/files/{key}", headers=admin).status_code == 200
    assert client.post(f"/admin/hosts/{host_id}/approve", headers=admin).json()["is_host"] is True

    r = client.post("/chargers", json=CHARGER, headers=host)
    assert r.status_code == 201, r.text
    charger = r.json()
    assert charger["status"] == "pending"
    # not visible before approval
    assert client.get("/chargers?lat=17.44&lng=78.35", headers=driver).json() == []
    client.post(f"/admin/chargers/{charger['id']}/approve", json={"safety_checked": True}, headers=admin)
    return {"admin": admin, "host": host, "driver": driver, "charger": charger}


def test_search_and_detail(client, world):
    res = client.get("/chargers?lat=17.45&lng=78.36&radius_km=5&vehicle=4W", headers=world["driver"]).json()
    assert len(res) == 1 and res[0]["distance_km"] < 3
    assert "qr_token" not in res[0] and "access_notes" not in res[0]
    assert client.get("/chargers?lat=12.97&lng=77.59", headers=world["driver"]).json() == []  # Bengaluru
    d = client.get(f"/chargers/{world['charger']['id']}", headers=world["driver"]).json()
    assert d["busy"] == []


def test_full_booking_flow(client, world):
    driver, host, admin = world["driver"], world["host"], world["admin"]
    cid = world["charger"]["id"]
    start, end = slot(3, 2)

    q = client.post("/bookings/quote", json={"charger_id": cid, "start_at": start, "end_at": end}, headers=driver).json()
    assert q["amount_paise"] == 20000  # ₹100/h × 2h

    # host can't book own charger
    assert client.post("/bookings", json={"charger_id": cid, "start_at": start, "end_at": end}, headers=host).status_code == 400

    r = client.post("/bookings", json={"charger_id": cid, "start_at": start, "end_at": end, "vehicle_type": "4W"}, headers=driver)
    assert r.status_code == 201, r.text
    b = r.json()["booking"]
    assert b["status"] == "pending_payment" and r.json()["provider"] == "mock"
    assert b["other_party_phone"] == ""  # contact hidden before confirmation

    # overlapping slot blocked while first is unpaid
    s2, e2 = slot(4, 2)
    assert client.post("/bookings", json={"charger_id": cid, "start_at": s2, "end_at": e2}, headers=admin).status_code == 409

    b = client.post(f"/payments/{b['id']}/mock-pay", headers=driver).json()
    assert b["status"] == "requested"
    # host sees it and accepts
    hb = client.get("/bookings?role=host&scope=upcoming", headers=host).json()
    assert [x["id"] for x in hb] == [b["id"]]
    b = client.post(f"/bookings/{b['id']}/accept", headers=host).json()
    assert b["status"] == "confirmed"
    b = client.get(f"/bookings/{b['id']}", headers=driver).json()
    assert b["other_party_phone"].startswith("+91") and b["access_notes"] == "Gate 2, slot B-12"

    # too early to check in (slot starts in 3h)
    qr = client.get(f"/chargers/{cid}/manage", headers=host).json()["qr_token"]
    assert client.post(f"/bookings/{b['id']}/check-in", json={"qr_token": qr, "checklist": CHECKS}, headers=driver).status_code == 400


def _make_confirmed(client, world, hours_from_now, length=1, mode=None):
    """Helper: creates a paid+accepted booking. Moves start into the past via the DB when needed."""
    from app.db import SessionLocal
    from app.models import Booking, Charger

    cid = world["charger"]["id"]
    if mode:
        with SessionLocal() as db:
            db.get(Charger, cid).pricing_mode = mode
            db.commit()
    start, end = slot(hours_from_now, length)
    r = client.post("/bookings", json={"charger_id": cid, "start_at": start, "end_at": end}, headers=world["driver"])
    assert r.status_code == 201, r.text
    bid = r.json()["booking"]["id"]
    client.post(f"/payments/{bid}/mock-pay", headers=world["driver"])
    client.post(f"/bookings/{bid}/accept", headers=world["host"])
    return bid


def _shift_to_now(bid):
    from app.db import SessionLocal
    from app.models import Booking, utcnow

    with SessionLocal() as db:
        b = db.get(Booking, bid)
        length = b.end_at - b.start_at
        b.start_at = utcnow() - timedelta(minutes=5)
        b.end_at = b.start_at + length
        db.commit()


def test_checkin_and_complete_hourly(client, world):
    bid = _make_confirmed(client, world, 30)
    _shift_to_now(bid)
    qr = client.get(f"/chargers/{world['charger']['id']}/manage", headers=world["host"]).json()["qr_token"]
    assert client.post(f"/bookings/{bid}/check-in", json={"qr_token": "wrong"}, headers=world["driver"]).status_code == 400
    b = client.post(f"/bookings/{bid}/check-in", json={"qr_token": qr, "checklist": CHECKS}, headers=world["driver"]).json()
    assert b["status"] == "active"
    b = client.post(f"/bookings/{bid}/complete", json={}, headers=world["driver"]).json()
    assert b["status"] == "completed"
    assert b["final_amount_paise"] == 10000 and b["commission_paise"] == 1000 and b["host_earning_paise"] == 9000
    assert b["can_review"] is True
    assert client.post("/reviews", json={"booking_id": bid, "rating": 5, "comment": "Great"}, headers=world["driver"]).status_code == 201
    assert client.post("/reviews", json={"booking_id": bid, "rating": 5}, headers=world["driver"]).status_code == 400
    d = client.get(f"/chargers/{world['charger']['id']}", headers=world["driver"]).json()
    assert d["rating_avg"] == 5.0 and d["rating_count"] == 1


def test_per_kwh_refund(client, world):
    bid = _make_confirmed(client, world, 40, length=2, mode="kwh")
    _shift_to_now(bid)
    qr = client.get(f"/chargers/{world['charger']['id']}/manage", headers=world["host"]).json()["qr_token"]
    client.post(f"/bookings/{bid}/check-in", json={"qr_token": qr, "checklist": CHECKS}, headers=world["driver"])
    # ₹100/kWh × 7.4kW × 2h = ₹1480 prepaid; used 5 kWh = ₹500
    b = client.post(f"/bookings/{bid}/complete", json={"kwh_used": 5}, headers=world["host"]).json()
    assert b["amount_paise"] == 148000
    assert b["final_amount_paise"] == 50000 and b["refund_paise"] == 98000
    # switch back to hourly
    from app.db import SessionLocal
    from app.models import Charger

    with SessionLocal() as db:
        db.get(Charger, world["charger"]["id"]).pricing_mode = "hour"
        db.commit()


def test_cancellation_rules(client, world):
    # early cancel by driver = full refund
    bid = _make_confirmed(client, world, 50)
    b = client.post(f"/bookings/{bid}/cancel", json={"reason": "plans changed"}, headers=world["driver"]).json()
    assert b["status"] == "cancelled" and b["refund_paise"] == 10000
    # host decline = full refund
    start, end = slot(60, 1)
    r = client.post("/bookings", json={"charger_id": world["charger"]["id"], "start_at": start, "end_at": end}, headers=world["driver"])
    bid = r.json()["booking"]["id"]
    client.post(f"/payments/{bid}/mock-pay", headers=world["driver"])
    b = client.post(f"/bookings/{bid}/decline", json={"reason": "busy"}, headers=world["host"]).json()
    assert b["status"] == "declined" and b["refund_paise"] == 10000
    # late cancel (< 1h before) = 50% refund, host keeps the rest minus commission
    bid = _make_confirmed(client, world, 70)
    from app.db import SessionLocal
    from app.models import Booking, utcnow

    with SessionLocal() as db:
        bk = db.get(Booking, bid)
        bk.start_at, bk.end_at = utcnow() + timedelta(minutes=30), utcnow() + timedelta(minutes=90)
        db.commit()
    b = client.post(f"/bookings/{bid}/cancel", json={}, headers=world["driver"]).json()
    assert b["refund_paise"] == 5000 and b["host_earning_paise"] == 4500


def test_sweeper_expires_and_completes(client, world):
    from app.db import SessionLocal
    from app.models import Booking, utcnow
    from app.services.booking_logic import sweep

    bid = _make_confirmed(client, world, 80)  # confirmed but driver never shows up
    with SessionLocal() as db:
        b = db.get(Booking, bid)
        b.start_at, b.end_at = utcnow() - timedelta(hours=3), utcnow() - timedelta(hours=2)
        db.commit()
        sweep(db)
        db.refresh(b)
        assert b.status == "completed" and b.no_show is True and b.host_earning_paise == 9000


def test_payouts(client, world):
    admin = world["admin"]
    created = client.post("/admin/payouts/generate", headers=admin).json()
    assert len(created) == 1 and created[0]["upi_id"] == "ravi@okaxis"
    assert created[0]["amount_paise"] == 9000 + 45000 + 4500 + 9000  # hourly, kwh (₹500 → ₹450), late cancel, no-show
    assert client.post("/admin/payouts/generate", headers=admin).json() == []  # nothing new
    p = client.post(f"/admin/payouts/{created[0]['id']}/mark-paid", json={"reference": "UTR123456"}, headers=admin).json()
    assert p["status"] == "paid"
    e = client.get("/me/earnings", headers=world["host"]).json()
    assert e["paid_out_paise"] == p["amount_paise"] and e["pending_payout_paise"] == 0


def test_reports_and_delete_account(client, world):
    r = client.post("/reports", json={"category": "safety", "message": "Loose socket at charger"}, headers=world["driver"])
    assert r.status_code == 201
    assert len(client.get("/admin/reports", headers=world["admin"]).json()) == 1
    extra = login(client, "9000000009", "Temp")
    assert client.delete("/me", headers=extra).status_code == 200
    assert client.get("/me", headers=extra).status_code == 401


# =====================================================================
#  Gap-filling features (run after the payout test above, same database)
# =====================================================================
from zoneinfo import ZoneInfo  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
C2 = {**CHARGER, "title": "Kondapur Night Saver", "address": "Flat 9, Secret Lane, Kondapur", "area": "Kondapur",
      "lat": 17.4622, "lng": 78.3568, "auto_accept": True, "offpeak_price_paise": 5000, "offpeak_start": "22:00",
      "offpeak_end": "06:00", "idle_fee_paise": 2000, "access_notes": "Basement B1"}


def _now_slot(minutes=60, offset_min=1):
    s = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=offset_min)
    return iso(s), iso(s + timedelta(minutes=minutes))


@pytest.fixture(scope="module")
def w2(client, world):
    admin = world["admin"]
    host = login(client, "9100000002", "Meera")
    driver = login(client, "9100000003", "Arjun")
    up = client.post("/uploads", files={"file": ("id.png", b"\x89PNG", "image/png")}, data={"kind": "id_doc"}, headers=host).json()
    client.post("/me/host-application", json={"id_doc_keys": [up["key"]], "payout_upi": "meera@okicici"}, headers=host)
    host_id = client.get("/me", headers=host).json()["id"]
    client.post(f"/admin/hosts/{host_id}/approve", headers=admin)
    c = client.post("/chargers", json=C2, headers=host).json()
    client.post(f"/admin/chargers/{c['id']}/approve", json={"safety_checked": True}, headers=admin)
    return {"admin": admin, "host": host, "driver": driver, "cid": c["id"], "other": world["driver"]}


def test_offpeak_pricing(client, w2):
    day = (datetime.now(IST) + timedelta(days=2)).date()
    def quote(h, m, mins):
        s = datetime(day.year, day.month, day.day, h, m, tzinfo=IST)
        return client.post("/bookings/quote", json={"charger_id": w2["cid"], "start_at": s.isoformat(), "end_at": (s + timedelta(minutes=mins)).isoformat()}, headers=w2["driver"]).json()
    assert quote(23, 0, 60)["amount_paise"] == 5000  # all off-peak
    assert quote(12, 0, 60)["amount_paise"] == 10000  # all normal
    assert quote(21, 30, 60)["amount_paise"] == 7500  # half and half


def test_location_privacy(client, w2):
    res = client.get("/chargers?lat=17.46&lng=78.356&radius_km=3", headers=w2["driver"]).json()
    c = next(x for x in res if x["id"] == w2["cid"])
    assert c["location_approximate"] is True and c["address"] == "Kondapur"
    assert (c["lat"], c["lng"]) != (17.4622, 78.3568)
    mine = client.get("/chargers/mine", headers=w2["host"]).json()[0]
    assert mine["address"] == C2["address"] and mine["lat"] == 17.4622


def test_available_now_filter(client, w2):
    q = "/chargers?lat=17.46&lng=78.356&radius_km=3&available_now=true"
    assert any(x["id"] == w2["cid"] for x in client.get(q, headers=w2["driver"]).json())
    s, e = _now_slot(60)
    b = client.post("/bookings", json={"charger_id": w2["cid"], "start_at": s, "end_at": e}, headers=w2["driver"]).json()["booking"]
    client.post(f"/payments/{b['id']}/mock-pay", headers=w2["driver"])
    assert not any(x["id"] == w2["cid"] for x in client.get(q, headers=w2["driver"]).json())
    client.post(f"/bookings/{b['id']}/cancel", json={}, headers=w2["driver"])  # free the slot again


def test_not_working_refund_and_auto_offline(client, w2):
    for i in range(2):
        s, e = _now_slot(60)
        r = client.post("/bookings", json={"charger_id": w2["cid"], "start_at": s, "end_at": e}, headers=w2["driver"])
        assert r.status_code == 201, r.text
        b = client.post(f"/payments/{r.json()['booking']['id']}/mock-pay", headers=w2["driver"]).json()
        assert b["status"] == "confirmed"  # instant booking
        b = client.post(f"/bookings/{b['id']}/not-working", json={"reason": "No power at the socket"}, headers=w2["driver"]).json()
        assert b["status"] == "cancelled" and b["charger_failed"] is True and b["refund_paise"] == b["amount_paise"]
    c = client.get(f"/chargers/{w2['cid']}/manage", headers=w2["host"]).json()
    assert c["offline"] is True and c["failed_reports"] == 2
    s, e = _now_slot(60)
    assert client.post("/bookings", json={"charger_id": w2["cid"], "start_at": s, "end_at": e}, headers=w2["driver"]).status_code == 400
    assert any(f["charger_id"] == w2["cid"] for f in client.get("/admin/flags", headers=w2["admin"]).json()["unreliable_chargers"])
    client.patch(f"/chargers/{w2['cid']}", json={"offline": False}, headers=w2["host"])  # host fixed it


def test_checklist_extension_overstay_and_dues(client, w2):
    from app.db import SessionLocal
    from app.models import Booking, utcnow

    s, e = _now_slot(60)
    b = client.post("/bookings", json={"charger_id": w2["cid"], "start_at": s, "end_at": e}, headers=w2["driver"]).json()["booking"]
    client.post(f"/payments/{b['id']}/mock-pay", headers=w2["driver"])
    qr = client.get(f"/chargers/{w2['cid']}/manage", headers=w2["host"]).json()["qr_token"]
    # checklist is required
    assert client.post(f"/bookings/{b['id']}/check-in", json={"qr_token": qr}, headers=w2["driver"]).status_code == 400
    b = client.post(f"/bookings/{b['id']}/check-in", json={"qr_token": qr, "checklist": CHECKS}, headers=w2["driver"]).json()
    assert b["status"] == "active" and b["checklist"]["cable_ok"] is True

    # extend by 30 min
    x = client.post(f"/bookings/{b['id']}/extend", json={"minutes": 30}, headers=w2["driver"]).json()
    assert x["extra"]["kind"] == "extension" and x["provider"] == "mock"
    client.post(f"/payments/extra/{x['extra']['id']}/mock-pay", headers=w2["driver"])
    b2 = client.get(f"/bookings/{b['id']}", headers=w2["driver"]).json()
    assert b2["extended_minutes"] == 30 and b2["amount_paise"] == b["amount_paise"] + x["extra"]["amount_paise"]

    # driver leaves 40 minutes late; host closes the session -> overstay fee (40 - 15 grace = 25 min = 2 blocks)
    with SessionLocal() as db:
        bk = db.get(Booking, b["id"])
        bk.end_at = utcnow() - timedelta(minutes=40)
        db.commit()
    done = client.post(f"/bookings/{b['id']}/complete", json={}, headers=w2["host"]).json()
    assert done["status"] == "completed" and done["overstay_minutes"] >= 40
    dues = client.get("/payments/dues", headers=w2["driver"]).json()
    assert len(dues) == 1 and dues[0]["amount_paise"] == 4000
    s, e = _now_slot(60, offset_min=120)
    assert client.post("/bookings", json={"charger_id": w2["cid"], "start_at": s, "end_at": e}, headers=w2["driver"]).status_code == 402
    co = client.post(f"/payments/extra/{dues[0]['id']}/checkout", headers=w2["driver"]).json()
    assert client.post(f"/payments/extra/{co['extra']['id']}/mock-pay", headers=w2["driver"]).json()["status"] == "paid"
    assert client.get("/payments/dues", headers=w2["driver"]).json() == []
    e2 = client.get("/me/earnings", headers=w2["host"]).json()
    assert e2["pending_payout_paise"] >= 3600  # 90% of the ₹40 overstay fee is the host's

    # receipt
    link = client.get(f"/bookings/{b['id']}/receipt-link", headers=w2["driver"]).json()["url"]
    page = client.get(link.split("8000", 1)[-1] if "8000" in link else link)
    assert page.status_code == 200 and "Receipt" in page.text and "Overstay" in page.text


def test_waitlist_notifies_when_slot_opens(client, w2):
    day = (datetime.now(IST) + timedelta(days=3)).date()
    start = datetime(day.year, day.month, day.day, 10, 0, tzinfo=IST)
    body = {"charger_id": w2["cid"], "start_at": start.isoformat(), "end_at": (start + timedelta(hours=1)).isoformat()}
    b = client.post("/bookings", json=body, headers=w2["other"]).json()["booking"]
    client.post(f"/payments/{b['id']}/mock-pay", headers=w2["other"])
    assert client.post("/bookings", json=body, headers=w2["driver"]).status_code == 409
    assert client.post(f"/chargers/{w2['cid']}/waitlist", json={"day": day.isoformat()}, headers=w2["driver"]).status_code == 201
    client.post(f"/bookings/{b['id']}/cancel", json={}, headers=w2["other"])
    w = client.get("/chargers/waitlist/mine", headers=w2["driver"]).json()
    assert w[0]["notified_at"] is not None


def test_housing_society(client, w2):
    admin, manager, resident, outsider = w2["admin"], w2["host"], w2["driver"], w2["other"]
    com = client.post("/communities", json={"name": "Green Meadows", "address": "Kondapur, Hyderabad", "manager_flat": "A-101"}, headers=manager).json()
    assert com["status"] == "pending" and com["code"]
    assert client.post("/communities/join", json={"code": com["code"], "flat": "B-202"}, headers=resident).status_code == 404  # not approved yet
    client.post(f"/admin/communities/{com['id']}/approve", json={}, headers=admin)
    client.post("/communities/join", json={"code": com["code"], "flat": "B-202"}, headers=resident)
    members = client.get(f"/communities/{com['id']}/members", headers=manager).json()
    pending = next(m for m in members if m["status"] == "pending")
    client.post(f"/communities/{com['id']}/members/{pending['id']}/approve", headers=manager)

    c3 = client.post("/chargers", json={**CHARGER, "title": "Green Meadows Basement", "lat": 17.47, "lng": 78.36, "community_id": com["id"]}, headers=manager).json()
    client.post(f"/admin/chargers/{c3['id']}/approve", json={}, headers=admin)
    q = "/chargers?lat=17.47&lng=78.36&radius_km=2"
    assert any(x["id"] == c3["id"] for x in client.get(q, headers=resident).json())
    assert not any(x["id"] == c3["id"] for x in client.get(q, headers=outsider).json())
    assert client.get(f"/chargers/{c3['id']}", headers=outsider).status_code == 404

    # resident charges once -> appears on the monthly per-flat statement
    bid = None
    s, e = _now_slot(60)
    bid = client.post("/bookings", json={"charger_id": c3["id"], "start_at": s, "end_at": e}, headers=resident).json()["booking"]["id"]
    client.post(f"/payments/{bid}/mock-pay", headers=resident)
    client.post(f"/bookings/{bid}/accept", headers=manager)
    qr = client.get(f"/chargers/{c3['id']}/manage", headers=manager).json()["qr_token"]
    client.post(f"/bookings/{bid}/check-in", json={"qr_token": qr, "checklist": CHECKS}, headers=resident)
    client.post(f"/bookings/{bid}/complete", json={}, headers=resident)
    st = client.get(f"/communities/{com['id']}/statement", headers=manager).json()
    row = next(r for r in st["rows"] if r["flat"] == "B-202")
    assert row["sessions"] == 1 and row["amount_paise"] == 10000 and row["kwh"] == 7.4
    assert client.get(f"/communities/{com['id']}/statement", headers=resident).status_code == 404  # manager only
