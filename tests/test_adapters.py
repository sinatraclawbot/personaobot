import json
import pytest
import httpx
from app.ai import AI, AIUnavailable, local_risk
from app.telegram import Telegram, TelegramError


@pytest.mark.parametrize(
    "text,reason",
    [
        ("I'm 17", "minors"),
        ("I am 9", "minors"),
        ("under 18", "minors"),
        ("full service available?", "sexual_services"),
        ("sex for money", "sexual_services"),
        ("blackmail her", "coercion"),
        ("trafficking", "trafficking"),
        ("bring cocaine", "illegal_activity"),
    ],
)
def test_local_safety_gate(text, reason):
    assert local_risk(text) == reason


def test_non_sexual_description_is_not_a_local_false_positive():
    assert local_risk("Non-sexual social companionship in public venues only.") is None


def test_ai_schema_context_and_output_moderation(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key")
    calls = []

    def handler(request):
        data = json.loads(request.content)
        calls.append((request.url.path, data))
        if request.url.path.endswith("moderations"):
            return httpx.Response(200, json={"results": [{"flagged": False}]})
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "action": "allow",
                                        "reason": "safe",
                                        "reply": "I'm the AI assistant. English is available.",
                                    }
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    ai = AI(httpx.Client(transport=httpx.MockTransport(handler)))
    result = ai.decide(
        {"profile": {"name": "Sofia"}, "memories": ["likes coffee"], "messages": [{"text": "What languages?"}]}
    )
    assert result.action == "allow"
    response_call = next(data for path, data in calls if path.endswith("responses"))
    assert response_call["store"] is False
    assert response_call["text"]["format"]["strict"] is True
    assert "previous_response_id" not in response_call and "tools" not in response_call
    assert len(calls) == 3


@pytest.mark.parametrize(
    "response",
    [
        {"status": "incomplete", "output": []},
        {"status": "completed", "output": []},
        {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "No"}]}]},
    ],
)
def test_ai_incomplete_and_refusal_fail_closed(monkeypatch, response):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key")

    def handler(request):
        return httpx.Response(
            200, json={"results": [{"flagged": False}]} if request.url.path.endswith("moderations") else response
        )

    ai = AI(httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(AIUnavailable):
        ai.decide({"messages": [{"text": "hello"}]})


def test_telegram_official_api_only(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    tg = Telegram(httpx.Client(transport=httpx.MockTransport(handler)))
    tg.send("connection-alpha", 800, "Hello")
    request = requests[0]
    assert str(request.url) == "https://api.telegram.org/bottest-token/sendMessage"
    assert json.loads(request.content)["business_connection_id"] == "connection-alpha"
    assert "parse_mode" not in json.loads(request.content)


def test_telegram_timeout_is_uncertain(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

    def handler(request):
        raise httpx.ReadTimeout("redacted", request=request)

    with pytest.raises(TelegramError) as result:
        Telegram(httpx.Client(transport=httpx.MockTransport(handler))).send("c", 1, "text")
    assert result.value.uncertain and "test-token" not in str(result.value)
