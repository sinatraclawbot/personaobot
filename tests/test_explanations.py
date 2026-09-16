from app.explanations import DEFAULT_COPY, REASON_COPY, explain_reason

REQUIRED = (
    "owner_takeover",
    "unsupported_media",
    "consent_withdrawn",
    "sexual_services",
    "connection_permission_lost",
    "connection_refresh_denied",
    "delivery_uncertain",
    "telegram_send_rejected",
    "human_mode",
    "automation_hourly_limit",
    "manual_gate_removed",
    "client_returned",
    "reply_window_expired",
    "incoming_window_expired",
)


def test_required_reasons_have_plain_copy():
    for code in REQUIRED:
        text = explain_reason(code)
        assert text
        assert text != DEFAULT_COPY
        assert "_" not in text
        assert text == REASON_COPY[code]


def test_unknown_and_empty_reasons():
    assert explain_reason("") == ""
    assert explain_reason(None) == ""
    assert explain_reason("not_a_known_reason") == DEFAULT_COPY
    assert "not broken" in DEFAULT_COPY.lower() or "is not broken" in DEFAULT_COPY
