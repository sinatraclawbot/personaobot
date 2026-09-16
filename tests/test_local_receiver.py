import httpx
import pytest

from app.local_receiver import deliver_batch


def test_failed_delivery_replays_without_acknowledging_batch():
    seen = []

    def handle(request):
        import json
        update = json.loads(request.content)
        seen.append(update["update_id"])
        return httpx.Response(503 if update["update_id"] == 2 else 200)

    updates = [{"update_id": i, "business_message": {}} for i in (1, 2)]
    offset = None
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            offset = deliver_batch(client, updates, "test-secret", "localhost", offset)
    assert offset is None
    assert seen == [1, 2]


def test_successful_delivery_authenticates_and_advances():
    def handle(request):
        assert request.headers["X-Telegram-Bot-Api-Secret-Token"] == "test-secret"
        assert request.headers["Host"] == "localhost:8000"
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert deliver_batch(client, [{"update_id": 7, "business_connection": {}}],
                             "test-secret", "localhost:8000") == 8
