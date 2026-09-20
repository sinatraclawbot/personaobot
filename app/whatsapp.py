import logging
import httpx
from .config import settings

log = logging.getLogger("platform.whatsapp")


def _bridge():
    return settings().whatsapp_bridge_url.rstrip("/")


def _post(path, payload):
    if not settings().whatsapp_enabled:
        return None
    try:
        r = httpx.post(_bridge() + path, json=payload, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        log.warning("whatsapp_bridge_failed path=%s err=%s", path, exc)
        return None


def send_text(profile_id, chat_id, text):
    """Send a text message through the profile's WhatsApp session. Returns True on success."""
    result = _post("/send", {"profile_id": str(profile_id), "chat_id": str(chat_id), "text": text})
    return bool(result and result.get("ok"))


def connect(profile_id):
    """Ask the sidecar to open a session for this profile (returns its QR via status)."""
    return bool(_post("/connect", {"profile_id": str(profile_id)}))


def disconnect(profile_id):
    return bool(_post("/disconnect", {"profile_id": str(profile_id)}))


def qr(profile_id):
    """Fetch this profile's QR code (data URL) or ready state from the sidecar."""
    if not settings().whatsapp_enabled:
        return {"status": "none", "qr": ""}
    try:
        r = httpx.get(_bridge() + "/qr/" + str(profile_id), timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        log.warning("whatsapp_qr_failed err=%s", exc)
        return {"status": "error", "qr": ""}