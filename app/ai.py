import json
import logging
import re
import unicodedata
import httpx
from .config import settings
from .schemas import Decision

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

ENGINE_POLICY = """You are the woman named in PROFILE_JSON.name. Talk like her in a real Telegram chat. Not an AI, not Grok, not a secretary, not a menu robot.

SOURCE OF TRUTH — only PROFILE_JSON:
personality, writing_style, languages, pricing, availability, boundaries, meeting_rules, instructions.


Speak ONLY in PROFILE_JSON.chat_language pack.
That pack is language + attitude + target + style from personality, writing_style, instructions.
Do not switch language. Do not switch girl. Do not chase.

How to talk:
- Like a person. Short. 1-4 sentences.
- Answer the actual question. If he asks what is included, explain the packages from pricing in her words.
- Same language he used (Hebrew / Russian / English).
- Do not chase.
- Do not dump the full price list unless he asked about price, packages, or what is included.
- Never invent extras, prices, or streets that are not in the profile.
- Paid adult details in this profile are allowed. Say them calmly if asked.
- Address: follow meeting_rules. Area first, exact street only after time + package.
- Photos: follow instructions. Do not send files.
- Adults only. If he sounds under 18, stop.
Output only her message text.
"""

def local_risk(text):
    value = unicodedata.normalize("NFKC", text).casefold()
    patterns = {
        "minors": r"\b(underage|minor|child|schoolgirl|schoolboy|under\s*18|(?:i\s*(?:am|[’']?m)|aged?)\s*(?:[0-9]|1[0-7])\b)",
        "coercion": r"\b(force[ds]?|blackmail|without\s+consent|drug\s+her|drug\s+him)\b",
        "trafficking": r"\b(traffick\w*|confiscat\w*\s+passport|sell\s+(?:girls|women|boys))\b",
        "illegal_activity": r"\b(cocaine|heroin|meth|stolen|fake\s+id)\b",
    }
    for reason, pattern in patterns.items():
        if re.search(pattern, value):
            return reason
    return None

def price_reply(profile):
    pricing = ((profile or {}).get("pricing") or "").strip()
    availability = ((profile or {}).get("availability") or "").strip()
    parts = [p for p in (pricing, availability) if p]
    if parts:
        parts.append("אתה בא אליי או שאני אליך?")
        return "\n".join(parts)
    return "תגיד מתי ואיזה מפגש ואכוון אותך"

def system_prompt(profile):
    return ENGINE_POLICY + "\n\nPROFILE_JSON:\n" + json.dumps(profile or {}, ensure_ascii=False)

class AIUnavailable(Exception):
    pass

class AI:
    def __init__(self, client=None):
        self.client = client or httpx.Client(timeout=httpx.Timeout(45, connect=5))

    def _base(self):
        return (settings().openai_base_url or "https://openrouter.ai/api/v1").rstrip("/") + "/"

    def request(self, path, body):
        if not settings().openai_api_key:
            raise AIUnavailable("ai_not_configured")
        try:
            r = self.client.post(self._base() + path, json=body, headers={"Authorization": "Bearer " + settings().openai_api_key, "HTTP-Referer": settings().app_url, "X-Title": "profile-chat"})
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError):
            raise AIUnavailable("ai_unavailable") from None

    def _llm_reply(self, context):
        profile = context.get("profile") or {}
        latest = context["messages"][-1]["text"] if context.get("messages") else ""
        messages = [{"role": "system", "content": system_prompt(profile)}]
        for row in context.get("messages") or []:
            role = "assistant" if row.get("role") == "assistant" else "user"
            messages.append({"role": role, "content": row.get("text") or ""})
        if not any(m["role"] == "user" for m in messages[1:]):
            messages.append({"role": "user", "content": latest or "שלום"})
        data = self.request("chat/completions", {"model": settings().openai_model, "temperature": 0.9, "max_tokens": 400, "messages": messages})
        reply = (data["choices"][0]["message"]["content"] or "").strip()
        if not reply:
            raise AIUnavailable("empty_reply")
        return reply[:3500]

    def suggest(self, context):
        profile = context.get("profile") or {}
        latest = context["messages"][-1]["text"] if context.get("messages") else ""
        messages = [{"role": "system", "content": system_prompt(profile)}]
        for row in context.get("messages") or []:
            role = "assistant" if row.get("role") == "assistant" else "user"
            messages.append({"role": role, "content": row.get("text") or ""})
        if not any(m["role"] == "user" for m in messages[1:]):
            messages.append({"role": "user", "content": latest or "שלום"})
        replies = []
        try:
            data = self.request(
                "chat/completions",
                {"model": settings().openai_model, "temperature": 0.9, "max_tokens": 400, "n": 2, "messages": messages},
            )
            for choice in data.get("choices") or []:
                text = (choice.get("message", {}).get("content") or "").strip()
                if text and text not in replies:
                    replies.append(text[:3500])
        except Exception:
            replies = []
        if len(replies) < 2:
            try:
                data = self.request(
                    "chat/completions",
                    {"model": settings().openai_model, "temperature": 0.5, "max_tokens": 400, "messages": messages},
                )
                text = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                if text and text not in replies:
                    replies.append(text[:3500])
            except Exception:
                pass
        return replies[:2]

    def decide(self, context, candidate=None):
        profile = context.get("profile") or {}
        latest = context["messages"][-1]["text"] if context.get("messages") else ""
        target = candidate if candidate is not None else latest
        risk = local_risk(target)
        if risk:
            return Decision(action="block", reason=risk, reply="")
        if candidate is not None:
            return Decision(action="allow", reason="safe", reply=candidate)
        try:
            reply = self._llm_reply(context)
        except Exception:
            reply = price_reply(profile)
        if local_risk(reply):
            return Decision(action="block", reason="uncertain", reply="")
        return Decision(action="allow", reason="safe", reply=reply)
