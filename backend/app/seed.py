"""Fill the database with demo data:  python -m app.seed

Creates an admin, a driver and a host with 5 approved chargers around Hyderabad,
so you can try the app straight away. Log in with these numbers (OTP prints in the server log):
  admin  +919000000001
  host   +919000000002
  driver +919000000003
"""
from sqlalchemy import select

from .db import SessionLocal, init_db
from .models import Charger, ChargerStatus, HostStatus, User

DEMO = [
    # title, address, lat, lng, vehicles, connector, kW, mode, price ₹, open, close
    ("Gachibowli Villa Charger", "Road 2, Gachibowli, Hyderabad", 17.4401, 78.3489, ["4W"], "Type 2 (AC)", 7.4, "kwh", 16, "06:00", "23:00"),
    ("Kondapur Apartment Socket", "Botanical Garden Rd, Kondapur", 17.4622, 78.3568, ["2W", "3W"], "15A socket", 3.3, "hour", 25, "00:00", "00:00"),
    ("Madhapur Office Parking", "Hitech City Rd, Madhapur", 17.4483, 78.3915, ["2W", "4W"], "Type 2 (AC)", 11, "hour", 120, "08:00", "20:00"),
    ("Jubilee Hills Home Charger", "Road 36, Jubilee Hills", 17.4326, 78.4071, ["4W"], "Bharat AC-001", 3.3, "kwh", 14, "18:00", "08:00"),
    ("Kokapet Society Charger", "Kokapet, Hyderabad", 17.3950, 78.3305, ["2W", "4W"], "Type 2 (AC)", 7.4, "hour", 90, "00:00", "00:00"),
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
        user("+919000000003", "Priya (demo driver)", vehicle_type="4W")
        if not db.scalar(select(Charger.id).where(Charger.host_id == host.id)):
            for t, a, lat, lng, vt, ct, kw, mode, price, o, c in DEMO:
                db.add(
                    Charger(
                        host_id=host.id, title=t, address=a, lat=lat, lng=lng, vehicle_types=vt, connector_type=ct,
                        power_kw=kw, pricing_mode=mode, price_paise=price * 100, open_time=o, close_time=c,
                        status=ChargerStatus.APPROVED, safety_checked=True, auto_accept=mode == "hour",
                        description="Demo listing", access_notes="Gate code 1234. Parking slot B-12.",
                    )
                )
        db.commit()
    print("Demo data ready.")


if __name__ == "__main__":
    run()
