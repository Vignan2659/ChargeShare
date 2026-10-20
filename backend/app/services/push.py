"""Push notifications through Expo's push service (it delivers via FCM on Android and APNs on iPhone)."""
import logging
import threading

import httpx

from ..config import get_settings
from ..models import User

log = logging.getLogger("push")
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def _send(token: str, title: str, body: str, data: dict) -> None:
    s = get_settings()
    headers = {"accept": "application/json", "content-type": "application/json"}
    if s.expo_access_token:
        headers["authorization"] = f"Bearer {s.expo_access_token}"
    try:
        httpx.post(
            EXPO_PUSH_URL,
            json={"to": token, "title": title, "body": body, "data": data, "sound": "default"},
            headers=headers,
            timeout=10,
        )
    except httpx.HTTPError as e:  # never let a notification failure break a booking
        log.warning("push failed: %s", e)


def notify(user: User | None, title: str, body: str, data: dict | None = None) -> None:
    if user is None or not user.push_token or not get_settings().push_enabled:
        log.info("notify(skip) %s: %s", getattr(user, "id", None), title)
        return
    threading.Thread(target=_send, args=(user.push_token, title, body, data or {}), daemon=True).start()
