import math
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import get_settings


def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().local_timezone)


def to_utc_naive(dt: datetime) -> datetime:
    """Accept an aware datetime (or naive = local time) and return naive UTC for storage."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz())
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def utc_naive_to_aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc)


def parse_hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def _in_window(t: time, open_t: time, close_t: time) -> bool:
    if open_t == close_t:
        return True  # open 24 hours
    if open_t < close_t:
        return open_t <= t < close_t
    return t >= open_t or t < close_t  # overnight window, e.g. 20:00-06:00


def within_open_hours(start_utc: datetime, end_utc: datetime, open_s: str, close_s: str) -> bool:
    """True if every minute of the booking falls inside the charger's daily open hours."""
    open_t, close_t = parse_hhmm(open_s), parse_hhmm(close_s)
    if open_t == close_t:
        return True
    local = tz()
    cur = utc_naive_to_aware(start_utc).astimezone(local)
    end = utc_naive_to_aware(end_utc).astimezone(local)
    step = timedelta(minutes=5)
    while cur < end:
        if not _in_window(cur.time(), open_t, close_t):
            return False
        cur += step
    return True


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bounding_box(lat: float, lng: float, radius_km: float) -> tuple[float, float, float, float]:
    dlat = radius_km / 111.0
    dlng = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    return lat - dlat, lat + dlat, lng - dlng, lng + dlng
