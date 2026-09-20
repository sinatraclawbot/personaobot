import logging
import httpx
from .config import settings

log = logging.getLogger("platform.whatsapp")


def send_text(chat_id, text):
    """Send a text message through the WhatsApp Web sidecar (best effort)."""
    if not settings().whatsapp_enabled:
        return
    try:
        r = httpx.post(
            settings().whatsapp_bridge_url.rstrip("/") + "/send",
            json={"chat_id": str(chat_id), "text": text},
            timeout=20,
        )
        r.raise_for_status()
    except Exception as exc:
        log.warning("whatsapp_send_failed chat_id=%s err=%s", chat_id, exc)
