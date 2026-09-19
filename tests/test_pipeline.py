import time
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.ai import AIUnavailable
from app.models import Connection, Conversation, Draft, Job, Memory, Message
from app.services import InvalidUpdate, RetryJob, context_for, generate, process_update, save_connection, send_draft
from app.telegram import TelegramError
from conftest import FakeAI, FakeTelegram, make_profile


def incoming(conn, uid=10, mid=2, text="What languages do you speak?", kind="business_message", sender=700, **kwargs):
    return {
        "update_id": uid,
        kind: {
            "business_connection_id": conn.id,
            "chat": {"id": 700, "type": "private"},
            "message_id": mid,
            "date": int(time.time()),
            "from": {"id": sender},
            "text": text,
            **kwargs,
        },
    }


def create_draft(db, profile, conv, status="queued"):
    draft = Draft(
        profile_id=profile.id,
        conversation_id=conv.id,
        revision=conv.revision,
        profile_version=profile.version,
        text="I'm Sofia's AI assistant. Sofia speaks English.",
        status=status,
    )
    db.add(draft)
    db.commit()
    return draft, {"profile_id": profile.id, "conversation_id": conv.id, "draft_id": draft.id}


def test_same_chat_and_message_ids_are_isolated(db, scope):
    p1, c1, v1 = scope
    p2, c2, v2 = make_profile(db, 102, "Anna")
    process_update(db, incoming(c1, uid=10, text="Sofia private context"))
    process_update(db, incoming(c2, uid=11, text="Anna private context"))
    db.add(Memory(profile_id=p2.id, conversation_id=v2.id, text="Anna private memory"))
    db.commit()
    context = context_for(db, p1, v1)
    assert "Sofia private context" in str(context)
    assert "Anna private" not in str(context)
    assert v1.id != v2.id
    assert len(list(db.scalars(select(Message).where(Message.telegram_id == 2)))) == 2


def test_database_rejects_cross_profile_message(db, scope):
    p1, _, _ = scope
    _, _, v2 = make_profile(db, 102, "Anna")
    db.add(Message(profile_id=p1.id, conversation_id=v2.id, telegram_id=8, direction="incoming", text="bad"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_approval_mode_creates_pending_without_send(db, scope):
    p, _, v = scope
    generate(db, {"profile_id": p.id, "conversation_id": v.id, "revision": v.revision}, FakeAI())
    db.commit()
    assert db.scalar(select(Draft)).status == "pending"
    assert not db.scalar(select(Job).where(Job.kind == "send"))


def test_auto_mode_queues_send(db, scope):
    p, _, v = scope
    p.mode = "auto"
    generate(db, {"profile_id": p.id, "conversation_id": v.id, "revision": v.revision}, FakeAI())
    db.commit()
    assert db.scalar(select(Draft)).status == "queued"
    assert db.scalar(select(Job).where(Job.kind == "send"))


def test_edit_invalidates_drafts_and_memory(db, scope):
    p, c, v = scope
    draft, _ = create_draft(db, p, v, "pending")
    db.add(Memory(profile_id=p.id, conversation_id=v.id, text="Preference"))
    original = v.last_incoming
    process_update(
        db, incoming(c, uid=11, mid=1, text="Changed", kind="edited_business_message", date=int(original) - 100)
    )
    db.commit()
    assert draft.status == "stale"
    assert db.scalar(select(Message).where(Message.telegram_id == 1)).text == "Changed"
    assert not db.scalar(select(Memory))
    assert v.last_incoming == original


def test_deleted_tombstone_prevents_resurrection(db, scope):
    _, c, v = scope
    process_update(
        db,
        {
            "update_id": 30,
            "deleted_business_messages": {
                "business_connection_id": c.id,
                "chat": {"id": 700, "type": "private"},
                "message_ids": [44],
            },
        },
    )
    process_update(db, incoming(c, uid=29, mid=44, text="Deleted secret"))
    db.commit()
    msg = db.scalar(select(Message).where(Message.conversation_id == v.id, Message.telegram_id == 44))
    assert msg.deleted and msg.text == ""


def test_duplicate_and_old_edits_ignored(db, scope):
    _, c, _ = scope
    process_update(db, incoming(c, uid=20, text="Newer edit", kind="edited_business_message"))
    process_update(db, incoming(c, uid=19, text="Original"))
    db.commit()
    assert db.scalar(select(Message).where(Message.telegram_id == 2)).text == "Newer edit"


def test_owner_takeover_pauses(db, scope):
    _, c, v = scope
    process_update(db, incoming(c, sender=c.owner_id))
    assert v.state == "paused" and v.reason == "owner_takeover"


def test_bot_echo_does_not_generate(db, scope):
    _, c, v = scope
    process_update(db, incoming(c, sender_business_bot={"id": 909, "is_bot": True}))
    db.flush()
    assert v.revision == 0
    assert not db.scalar(select(Job))


def test_visual_media_does_not_escalate(db, scope):
    _, c, v = scope
    process_update(db, incoming(c, photo=[{"file_id": "unused"}]))
    assert v.state == "active" and not v.reason


def test_unclaimed_connection_cannot_generate(db):
    c = Connection(id="unknown", owner_id=999, user_chat_id=999, enabled=True, rights={"can_reply": True})
    db.add(c)
    db.commit()
    with pytest.raises(RetryJob, match="unclaimed_connection"):
        process_update(db, incoming(c))
    assert not db.scalar(select(Conversation))


def test_unknown_connection_recovered_via_official_api(db, scope):
    p, c, _ = scope
    payload = incoming(c)
    payload["business_message"]["business_connection_id"] = "new-connection"
    process_update(db, payload, FakeTelegram(c))
    db.commit()
    assert db.get(Connection, "new-connection").profile_id == p.id


def test_connection_owner_is_immutable(db, scope):
    _, c, _ = scope
    data = FakeTelegram(c).connection(c.id)
    data["user"]["id"] = 999
    with pytest.raises(InvalidUpdate, match="connection_owner_changed"):
        save_connection(db, data)


def test_disconnect_invalidates_drafts(db, scope):
    p, c, v = scope
    draft, _ = create_draft(db, p, v)
    save_connection(db, FakeTelegram(c, enabled=False).connection(c.id), 100)
    db.commit()
    assert not c.enabled and draft.status == "stale" and v.state == "escalated"


@pytest.mark.parametrize(
    "action,reason",
    [
        ("block", "sexual_services"),
        ("block", "minors"),
        ("block", "coercion"),
        ("block", "trafficking"),
        ("block", "illegal_activity"),
        ("escalate", "uncertain"),
    ],
)
def test_risky_decisions_never_queue_send(db, scope, action, reason):
    p, _, v = scope
    p.mode = "auto"
    generate(db, {"profile_id": p.id, "conversation_id": v.id, "revision": 0}, FakeAI(action, reason))
    db.commit()
    assert v.state in ("blocked", "escalated")
    assert not db.scalar(select(Draft)) and not db.scalar(select(Job))


def test_ai_failure_fails_closed(db, scope):
    p, _, v = scope

    class FailedAI:
        def decide(self, *_, **kwargs):
            raise AIUnavailable("ai_unavailable")

    generate(db, {"profile_id": p.id, "conversation_id": v.id, "revision": 0}, FailedAI())
    assert v.state == "escalated"
    assert not db.scalar(select(Draft))


@pytest.mark.parametrize("field", ["adult_verified", "consent"])
def test_routine_replies_do_not_require_manual_attestation(db, scope, field):
    p, _, v = scope
    setattr(v, field, False)
    ai = FakeAI()
    generate(db, {"profile_id": p.id, "conversation_id": v.id, "revision": 0}, ai)
    assert v.state == "active" and len(ai.contexts) == 1
    assert db.scalar(select(Draft)) is not None


def test_successful_send_uses_exact_business_connection(db, scope):
    p, c, v = scope
    draft, payload = create_draft(db, p, v)
    tg = FakeTelegram(c)
    send_draft(db, payload, tg, FakeAI())
    db.commit()
    assert draft.status == "sent" and draft.telegram_id == 500
    assert tg.sent == [(c.id, v.chat_id, draft.text)]
    send_draft(db, payload, tg, FakeAI())
    assert len(tg.sent) == 1


@pytest.mark.parametrize("rights,enabled", [({}, True), ({"can_reply": True}, False)])
def test_fresh_permission_check_prevents_send(db, scope, rights, enabled):
    p, c, v = scope
    draft, payload = create_draft(db, p, v)
    tg = FakeTelegram(c, rights=rights, enabled=enabled)
    send_draft(db, payload, tg, FakeAI())
    assert draft.status == "blocked" and tg.sent == []


def test_window_expires_during_moderation(db, scope):
    p, c, v = scope
    draft, payload = create_draft(db, p, v)

    class SlowAI(FakeAI):
        def decide(self, *args, **kwargs):
            v.last_incoming = time.time() - 86401
            return super().decide(*args, **kwargs)

    tg = FakeTelegram(c)
    send_draft(db, payload, tg, SlowAI())
    assert draft.status == "blocked" and tg.sent == []


def test_stale_draft_never_sends(db, scope):
    p, c, v = scope
    draft, payload = create_draft(db, p, v)
    v.revision += 1
    tg = FakeTelegram(c)
    send_draft(db, payload, tg, FakeAI())
    assert draft.status == "stale" and tg.sent == []


def test_pending_update_defers_send(db, scope):
    p, c, v = scope
    _, payload = create_draft(db, p, v)
    db.add(Job(kind="update", connection_id=c.id, dedupe="update:44", payload=incoming(c, uid=44)))
    db.commit()
    with pytest.raises(RetryJob, match="incoming_update_pending"):
        send_draft(db, payload, FakeTelegram(c), FakeAI())


def test_manual_reply_is_checked_too(db, scope):
    p, c, v = scope
    draft, payload = create_draft(db, p, v)
    tg = FakeTelegram(c)
    send_draft(db, payload, tg, FakeAI("block", "sexual_services"))
    assert draft.status == "blocked" and tg.sent == [] and v.state == "blocked"


def test_unknown_delivery_not_retried(db, scope):
    p, c, v = scope
    draft, payload = create_draft(db, p, v)
    tg = FakeTelegram(c, fail=TelegramError("transport", uncertain=True))
    send_draft(db, payload, tg, FakeAI())
    db.commit()
    send_draft(db, payload, tg, FakeAI())
    assert draft.status == "uncertain" and len(tg.sent) == 1


def test_interrupted_intent_becomes_uncertain(db, scope):
    p, c, v = scope
    draft, payload = create_draft(db, p, v, "sending")
    tg = FakeTelegram(c)
    send_draft(db, payload, tg, FakeAI())
    assert draft.status == "uncertain" and tg.sent == []


def test_explicit_429_is_retryable(db, scope):
    p, c, v = scope
    draft, payload = create_draft(db, p, v)
    with pytest.raises(RetryJob) as error:
        send_draft(db, payload, FakeTelegram(c, fail=TelegramError(429, retry_after=17)), FakeAI())
    assert error.value.delay == 17 and draft.status == "queued"


def test_cross_profile_payload_rejected(db, scope):
    p, c, v = scope
    p2, _, _ = make_profile(db, 102, "Anna")
    _, payload = create_draft(db, p, v)
    payload["profile_id"] = p2.id
    with pytest.raises(InvalidUpdate, match="invalid_scope"):
        send_draft(db, payload, FakeTelegram(c), FakeAI())


def test_opt_out_revokes_consent(db, scope):
    _, conn, conv = scope
    process_update(db, incoming(conn, text="STOP"))
    assert conv.consent is False and conv.reason == "consent_withdrawn"


def test_local_risk_blocks_even_while_paused(db, scope):
    _, conn, conv = scope
    conv.state = "paused"
    process_update(db, incoming(conn, text="I'm 16"))
    assert conv.state == "blocked" and conv.reason == "minors"


def test_update_id_restart_after_week_does_not_ignore_connection_change(db, scope):
    _, conn, _ = scope
    conn.last_update_id = 999999
    conn.last_update_seen = time.time() - 8 * 86400
    save_connection(db, FakeTelegram(conn, enabled=False).connection(conn.id), 10)
    assert conn.enabled is False and conn.last_update_id == 10


def test_edit_time_handles_update_id_reset(db, scope):
    _, conn, _ = scope
    process_update(db, incoming(conn, uid=999999, text="Earlier", date=int(time.time()) - 8 * 86400))
    process_update(
        db, incoming(conn, uid=10, text="New edit", kind="edited_business_message", edit_date=int(time.time()))
    )
    db.flush()
    assert db.scalar(select(Message).where(Message.telegram_id == 2)).text == "New edit"


def test_update_arriving_during_ai_check_defers_send(db, scope):
    p, conn, conv = scope
    _, payload = create_draft(db, p, conv)

    class IncomingAI(FakeAI):
        def decide(self, *args, **kwargs):
            db.add(Job(kind="update", dedupe="arrived-during-ai", connection_id=conn.id, payload=incoming(conn)))
            return super().decide(*args, **kwargs)

    telegram = FakeTelegram(conn)
    with pytest.raises(RetryJob, match="incoming_update_pending"):
        send_draft(db, payload, telegram, IncomingAI())
    assert telegram.sent == []


def test_revoked_approver_cannot_send(db, scope):
    from app.models import User

    p, conn, conv = scope
    user = User(email="revoked@example.test", password_hash="unused", active=False, admin=True)
    db.add(user)
    db.commit()
    draft, payload = create_draft(db, p, conv)
    draft.approved_by = user.id
    db.commit()
    telegram = FakeTelegram(conn)
    send_draft(db, payload, telegram, FakeAI())
    assert draft.status == "blocked" and draft.reason == "approver_access_revoked" and telegram.sent == []


def test_auto_restarts_on_client_message_after_owner_reply(db, scope):
    profile, conn, conv = scope
    profile.mode = 'auto'
    process_update(db, incoming(conn, sender=conn.owner_id))
    assert conv.state == 'paused'
    process_update(db, incoming(conn, uid=11, mid=3))
    db.flush()
    assert conv.state == 'active'
    assert db.scalar(select(Job).where(Job.kind == 'generate')) is not None


@pytest.mark.parametrize('reason', ['consent_withdrawn', 'operator_pause', 'minors'])
def test_auto_does_not_restart_protected_holds(db, scope, reason):
    profile, conn, conv = scope
    profile.mode = 'auto'
    conv.state, conv.reason = 'paused', reason
    process_update(db, incoming(conn))
    db.flush()
    assert conv.state == 'paused'
    assert db.scalar(select(Job).where(Job.kind == 'generate')) is None
