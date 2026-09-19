import httpx
from .config import settings


class TelegramError(Exception):
    def __init__(self, code, retry_after=0, uncertain=False):
        self.code, self.retry_after, self.uncertain = code, retry_after, uncertain
        super().__init__(f"telegram_{code}")


class Telegram:
    def __init__(self, client=None):
        self.client = client or httpx.Client(timeout=httpx.Timeout(20, connect=5))

    def call(self, method, payload):
        if not settings().telegram_bot_token:
            raise TelegramError("not_configured")
        try:
            r = self.client.post(f"https://api.telegram.org/bot{settings().telegram_bot_token}/{method}", json=payload)
            data = r.json()
        except (httpx.HTTPError, ValueError):
            # A timeout may happen AFTER Telegram accepted sendMessage. Never blind-retry it.
            raise TelegramError("transport", uncertain=method == "sendMessage") from None
        if not data.get("ok"):
            code = data.get("error_code", r.status_code)
            raise TelegramError(
                code,
                data.get("parameters", {}).get("retry_after", 0),
                uncertain=method == "sendMessage" and int(code) >= 500,
            )
        return data["result"]

    def connection(self, connection_id):
        return self.call("getBusinessConnection", {"business_connection_id": connection_id})

    def send(self, connection_id, chat_id, text):
        return self.call(
            "sendMessage",
            {
                "business_connection_id": connection_id,
                "chat_id": chat_id,
                "text": text,
                "protect_content": True,
                "link_preview_options": {"is_disabled": True},
            },
        )

    def get_file(self, file_id):
        result = self.call("getFile", {"file_id": file_id})
        path = result.get("file_path")
        if not path:
            raise TelegramError("no_file_path")
        dot = path.rfind(".")
        suffix = ("" if dot == -1 else "." + path[dot + 1:].lower())
        url = "https://api.telegram.org/file/bot" + settings().telegram_bot_token + "/" + path
        r = self.client.get(url, timeout=60)
        r.raise_for_status()
        return r.content, suffix

    def send_file(self, method, connection_id, chat_id, field, path, caption=""):
        if not settings().telegram_bot_token:
            raise TelegramError("not_configured")
        data = {"business_connection_id": connection_id, "chat_id": str(chat_id), "protect_content": "true"}
        if caption:
            data["caption"] = caption[:1024]
        try:
            with open(path, "rb") as handle:
                r = self.client.post("https://api.telegram.org/bot" + settings().telegram_bot_token + "/" + method, data=data, files={field: handle}, timeout=60)
                payload = r.json()
        except Exception:
            raise TelegramError("transport", uncertain=True) from None
        if not payload.get("ok"):
            raise TelegramError(payload.get("error_code", 0))
        return payload["result"]
