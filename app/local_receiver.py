"""Optional local Bot API polling bridge; never run alongside a webhook."""
import logging
import time
from urllib.parse import urlparse

import httpx

from .config import settings

KINDS = (
    "business_connection", "business_message", "edited_business_message", "deleted_business_messages"
)
log = logging.getLogger(__name__)


def deliver_batch(client, updates, secret, host, offset=None):
    # Advance only after the API has durably stored every preceding update.
    # A failed batch is replayed; the database deduplicates already stored events.
    for update in updates:
        if any(kind in update for kind in KINDS):
            response = client.post(
                "http://api:8000/webhooks/telegram", json=update,
                headers={"X-Telegram-Bot-Api-Secret-Token": secret, "Host": host},
            )
            response.raise_for_status()
        offset = update["update_id"] + 1
    return offset


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    cfg = settings()
    if cfg.environment != "development":
        raise SystemExit("Local receiver requires development environment")
    if not cfg.telegram_bot_token or not cfg.telegram_webhook_secret:
        raise SystemExit("Telegram credentials required")
    base = "https://api.telegram.org/bot" + cfg.telegram_bot_token
    offset = None
    host = urlparse(cfg.app_url).netloc
    with httpx.Client(timeout=40) as client:
        while True:
            try:
                info = client.post(base + "/getWebhookInfo").json()
                if not info.get("ok"):
                    raise ValueError("Telegram status unavailable")
                if info["result"].get("url"):
                    log.error("Webhook is configured; polling paused. Stop the local receiver before deployment.")
                    time.sleep(30)
                    continue
                params = {"timeout": 25, "limit": 100, "allowed_updates": list(KINDS)}
                if offset is not None:
                    params["offset"] = offset
                result = client.post(base + "/getUpdates", json=params).json()
                if not result.get("ok"):
                    raise ValueError("Telegram polling unavailable")
                updates = result["result"]
                offset = deliver_batch(client, updates, cfg.telegram_webhook_secret, host, offset)
                if updates:
                    log.info("Delivered %d updates to the durable inbox", len(updates))
            except Exception as error:
                # HTTP exception strings can contain the bot token. Log only the type.
                log.warning("Receive attempt failed (%s); retrying", type(error).__name__)
                time.sleep(5)


if __name__ == "__main__":
    main()
