"""Fill the database with demo data:  python -m app.seed

Creates an admin, a driver and a host with 5 approved chargers around Hyderabad
(one of them residents-only in the demo society "Lake View Residency", join code LAKE01),
so you can try the app straight away. Log in with these numbers (OTP prints in the server log):
  admin  +919000000001
  host   +919000000002
  driver +919000000003
"""
from sqlalchemy import select

from .db import SessionLocal, init_db
from .models import Charger, ChargerStatus, Community, CommunityMember, HostStatus, User

DEMO = [
    # title, address, area, lat, lng, vehicles, connector, kW, mode, price ₹, open, close, off-peak ₹ (22:00–06:00), idle fee ₹/15 min
    ("Gachibowli Villa Charger", "Villa 14, Road 2, Gachibowli, Hyderabad", "Gachibowli", 17.4401, 78.3489, ["4W"], "Type 2 (AC)", 7.4, "kwh", 16, "06:00", "23:00", 12, 20),
    ("Kondapur Apartment Socket", "Flat 304, Botanical Garden Rd, Kondapur", "Kondapur", 17.4622, 78.3568, ["2W", "3W"], "15A socket", 3.3, "hour", 25, "00:00", "00:00", 15, 0),
    ("Madhapur Office Parking", "Level P2, Hitech City Rd, Madhapur", "Madhapur", 17.4483, 78.3915, ["2W", "4W"], "Type 2 (AC)", 11, "hour", 120, "08:00", "20:00", None, 30),
    ("Jubilee Hills Home Charger", "8-2-293, Road 36, Jubilee Hills", "Jubilee Hills", 17.4326, 78.4071, ["4W"], "Bharat AC-001", 3.3, "kwh", 14, "18:00", "08:00", None, 0),
    ("Kokapet Society Charger", "Tower C basement, Lake View Residency, Kokapet", "Kokapet", 17.3950, 78.3305, ["2W", "4W"], "Type 2 (AC)", 7.4, "hour", 90, "00:00", "00:00", 60, 25),
]


def run():
    init_db()
    with SessionLocal() as db:
        def user(phone, name, **kw):
            u = db.scalar(select(User).where(User.phone == phone))
            if u is None:
                u = User(phone=phone, name=name, **kw)
                db.add(u)
                db.flush()
            return u

        user("+919000000001", "Admin", is_admin=True)
        host = user(
            "+919000000002", "Ravi (demo host)", is_host=True, host_status=HostStatus.APPROVED, payout_upi="ravi@okaxis"
        )
        driver = user("+919000000003", "Priya (demo driver)", vehicle_type="4W")
        society = db.scalar(select(Community).where(Community.code == "LAKE01"))
        if society is None:
            society = Community(name="Lake View Residency", address="Kokapet, Hyderabad", code="LAKE01", manager_id=host.id, status="approved")
            db.add(society)
            db.flush()
            db.add(CommunityMember(community_id=society.id, user_id=host.id, flat="C-1204", status="approved"))
            db.add(CommunityMember(community_id=society.id, user_id=driver.id, flat="C-803", status="approved"))
        if not db.scalar(select(Charger.id).where(Charger.host_id == host.id)):
            for t, a, area, lat, lng, vt, ct, kw, mode, price, o, c, offpeak, idle in DEMO:
                db.add(
                    Charger(
                        host_id=host.id, title=t, address=a, area=area, lat=lat, lng=lng, vehicle_types=vt, connector_type=ct,
                        power_kw=kw, pricing_mode=mode, price_paise=price * 100, open_time=o, close_time=c,
                        offpeak_price_paise=offpeak * 100 if offpeak else None, idle_fee_paise=idle * 100,
                        status=ChargerStatus.APPROVED, safety_checked=True, auto_accept=mode == "hour",
                        community_id=society.id if "Society" in t else None,
                        description="Demo listing", access_notes="Gate code 1234. Parking slot B-12.",
                    )
                )
        db.commit()
    print("Demo data ready.")


if __name__ == "__main__":
    run()
