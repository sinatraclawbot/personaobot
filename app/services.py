import time
import re
from sqlalchemy import func, select, update
from .models import Audit, Connection, Conversation, Draft, Job, Memory, Message, Profile, Membership, User
from .ai import AI, AIUnavailable, local_risk
from .telegram import Telegram, TelegramError


class RetryJob(Exception):
    def __init__(self, reason, delay=5):
        self.reason, self.delay = reason, delay
        super().__init__(reason)


class InvalidUpdate(Exception):
    pass

def maybe_send_media(telegram, profile, conv, db):
    from .media import first_file
    last = db.scalar(select(Message).where(Message.profile_id == profile.id, Message.conversation_id == conv.id, Message.direction == "incoming").order_by(Message.created.desc()))
    text = (last.text if last else "") or ""
    try:
        import re as _re
        if _re.search(r"(video|videos)", text, _re.I):
            path = first_file(profile.id, "video")
            if path:
                telegram.send_file("sendVideo", conv.connection_id, conv.chat_id, "video", path)
                return
        if _re.search(r"(pic|photo|photos|foto)", text, _re.I):
            path = first_file(profile.id, "photo")
            if path:
                telegram.send_file("sendPhoto", conv.connection_id, conv.chat_id, "photo", path)
    except Exception:
        return



def audit(db, actor, action, target="", profile_id=None):
    db.add(Audit(actor=actor, action=action, target=str(target), profile_id=profile_id))


def enqueue(db, kind, dedupe, connection_id, payload):
    if not db.scalar(select(Job.id).where(Job.dedupe == dedupe)):
        db.add(Job(kind=kind, dedupe=dedupe, connection_id=connection_id, payload=payload))


def invalidate(db, conv, reason):
    conv.revision += 1
    conv.updated = time.time()
    db.execute(
        update(Draft)
        .where(
            Draft.profile_id == conv.profile_id,
            Draft.conversation_id == conv.id,
            Draft.status.in_(["pending", "queued"]),
        )
        .values(status="stale", reason=reason)
    )


def hold(db, conv, reason, blocked=False):
    invalidate(db, conv, reason)
    conv.state = "blocked" if blocked else "escalated"
    conv.reason = reason
    audit(db, "system", "conversation_" + conv.state, conv.id, conv.profile_id)


def save_connection(db, data, update_id=None):
    cid = str(data["id"])
    owner = int(data["user"]["id"])
    connection = db.get(Connection, cid)
    if connection and connection.owner_id != owner:
        raise InvalidUpdate("connection_owner_changed")
    if (
        connection
        and update_id is not None
        and update_id <= connection.last_update_id
        and connection.last_update_seen > time.time() - 7 * 86400
    ):
        return connection
    if not connection:
        profile = db.scalar(select(Profile).where(Profile.owner_telegram_id == owner))
        connection = Connection(
            id=cid,
            owner_id=owner,
            user_chat_id=int(data["user_chat_id"]),
            profile_id=profile.id if profile else None,
            last_update_id=-1,
        )
        db.add(connection)
    was_enabled = connection.enabled
    connection.enabled = bool(data.get("is_enabled", False))
    connection.rights = data.get("rights") or {}
    connection.checked = time.time()
    connection.established = int(data.get("date", 0))
    if update_id is not None:
        connection.last_update_id = update_id
        connection.last_update_seen = time.time()
    db.flush()
    if was_enabled and (not connection.enabled or not connection.rights.get("can_reply")):
        for conv in db.scalars(select(Conversation).where(Conversation.connection_id == cid)):
            hold(db, conv, "connection_permission_lost")
    return connection


def connection_for(db, cid, telegram):
    connection = db.get(Connection, cid)
    if not connection:
        connection = save_connection(db, telegram.connection(cid))
    if connection.id != cid:
        raise InvalidUpdate("connection_mismatch")
    if not connection.profile_id:
        raise RetryJob("unclaimed_connection", 60)
    return connection


def process_update(db, payload, telegram=None):
    telegram = telegram or Telegram()
    update_id = int(payload["update_id"])
    if "business_connection" in payload:
        save_connection(db, payload["business_connection"], update_id)
        return
    kind = next(
        (k for k in ("business_message", "edited_business_message", "deleted_business_messages") if k in payload), None
    )
    if not kind:
        return
    data = payload[kind]
    cid = str(data["business_connection_id"])
    connection = connection_for(db, cid, telegram)
    chat = data["chat"]
    if chat["type"] != "private":
        return
    profile_id = connection.profile_id
    conv = db.scalar(
        select(Conversation).where(
            Conversation.profile_id == profile_id,
            Conversation.connection_id == cid,
            Conversation.chat_id == int(chat["id"]),
        )
    )
    if not conv:
        conv = Conversation(
            profile_id=profile_id,
            connection_id=cid,
            chat_id=int(chat["id"]),
            client_name=str(chat.get("first_name", "Client"))[:200],
        )
        db.add(conv)
        db.flush()
    if kind == "deleted_business_messages":
        for mid in data["message_ids"]:
            msg = db.scalar(
                select(Message).where(
                    Message.profile_id == profile_id,
                    Message.conversation_id == conv.id,
                    Message.telegram_id == int(mid),
                )
            )
            if not msg:
                db.add(
                    Message(
                        profile_id=profile_id,
                        conversation_id=conv.id,
                        telegram_id=int(mid),
                        direction="unsupported",
                        text="",
                        deleted=True,
                        last_update_id=update_id,
                    )
                )
            else:
                msg.deleted, msg.text = True, ""
                msg.last_update_id = max(msg.last_update_id, update_id)
        # Conservatively invalidate derived memory because it could depend on deleted content.
        db.query(Memory).filter_by(profile_id=profile_id, conversation_id=conv.id).delete()
        invalidate(db, conv, "source_deleted")
        return
    mid = int(data["message_id"])
    msg = db.scalar(
        select(Message).where(
            Message.profile_id == profile_id, Message.conversation_id == conv.id, Message.telegram_id == mid
        )
    )
    event_time = float(data.get("edit_date", data.get("date", 0)))
    if msg and (
        msg.deleted or msg.event_time > event_time or (msg.event_time == event_time and msg.last_update_id >= update_id)
    ):
        return
    sender = data.get("from", {})
    is_owner = int(sender.get("id", 0)) == connection.owner_id
    is_bot = bool(sender.get("is_bot")) or bool(data.get("sender_business_bot"))
    supported = isinstance(data.get("text"), str) and not any(
        k in data for k in ("photo", "video", "document", "voice", "audio", "sticker", "animation")
    )
    direction = "outgoing" if is_bot else "owner" if is_owner else "incoming" if supported else "unsupported"
    if not msg:
        msg = Message(profile_id=profile_id, conversation_id=conv.id, telegram_id=mid)
        db.add(msg)
    msg.direction = direction
    msg.text = str(data.get("text", data.get("caption", "")))[:10000]
    if not is_bot and not (msg.media or []):
        media_id, media_kind = None, None
        if isinstance(data.get("photo"), list) and data["photo"]:
            media_id, media_kind = data["photo"][-1].get("file_id"), "photo"
        elif isinstance(data.get("video"), dict):
            media_id, media_kind = data["video"].get("file_id"), "video"
        if media_id:
            try:
                content, suffix = telegram.get_file(media_id)
                if not suffix:
                    suffix = ".jpg" if media_kind == "photo" else ".mp4"
                from .media import save_chat_media
                msg.media = [save_chat_media(profile_id, "m" + suffix, content)]
            except Exception:
                msg.media = []
    msg.created = min(float(data.get("date", time.time())), time.time())
    msg.last_update_id = update_id
    msg.event_time = event_time
    if is_bot:
        return
    invalidate(db, conv, "source_changed")
    if kind == "edited_business_message":
        db.query(Memory).filter_by(profile_id=profile_id, conversation_id=conv.id).delete()
    if is_owner:
        conv.state, conv.reason = "paused", "owner_takeover"
        return
    # Edits do not extend Telegram's 24-hour incoming-message window.
    conv.last_incoming = max(conv.last_incoming, msg.created)
    if not supported:
        hold(db, conv, "unsupported_media")
        return
    if re.fullmatch(
        r"\s*(stop|unsubscribe|cancel|leave me alone|do not contact me)[.!\s]*", msg.text, flags=re.IGNORECASE
    ):
        conv.consent = False
        hold(db, conv, "consent_withdrawn")
        return
    risk = local_risk(msg.text)
    if risk:
        hold(db, conv, risk, blocked=True)
        return
    # Owner messages cancel stale replies; the next client message can restart Auto mode.
    profile = db.get(Profile, profile_id)
    if conv.reason == "owner_takeover" and conv.state == "paused" and profile.mode == "auto":
        conv.state, conv.reason = "active", "client_returned"
    if conv.state == "active":
        enqueue(
            db,
            "generate",
            f"generate:{conv.id}:{conv.revision}",
            cid,
            {"profile_id": profile_id, "conversation_id": conv.id, "revision": conv.revision},
        )


def context_for(db, profile, conv):
    rows = list(
        db.scalars(
            select(Message)
            .where(
                Message.profile_id == profile.id,
                Message.conversation_id == conv.id,
                Message.deleted.is_(False),
                Message.direction.in_(["incoming", "outgoing", "owner"]),
            )
            .order_by(Message.created.desc(), Message.telegram_id.desc())
            .limit(30)
        )
    )
    memories = list(
        db.scalars(
            select(Memory.text)
            .where(Memory.profile_id == profile.id, Memory.conversation_id == conv.id)
            .order_by(Memory.created.desc())
            .limit(10)
        )
    )
    return {
        "profile": {"name": profile.name, **profile.config},
        "memories": memories,
        "messages": [
            {"role": "client" if row.direction == "incoming" else "assistant", "text": row.text[:4000]}
            for row in reversed(rows)
        ],
    }


def scope(db, payload):
    profile = db.get(Profile, payload["profile_id"])
    conv = db.scalar(
        select(Conversation)
        .where(Conversation.id == payload["conversation_id"], Conversation.profile_id == payload["profile_id"])
        .with_for_update()
    )
    if not profile or not conv:
        raise InvalidUpdate("invalid_scope")
    return profile, conv


def eligibility(profile, conv, connection):
    if not profile.enabled or not profile.lawful_reviewed:
        return "profile_not_enabled_or_reviewed"
    if conv.state != "active":
        return "conversation_not_active"
    if (
        not connection
        or connection.profile_id != profile.id
        or not connection.enabled
        or not connection.rights.get("can_reply")
    ):
        return "connection_permission_lost"
    if not 0 <= time.time() - conv.last_incoming < 86400 - 60:
        return "reply_window_expired"
    return None


def generate(db, payload, ai=None):
    profile, conv = scope(db, payload)
    if conv.revision != payload["revision"] or conv.state != "active":
        return
    reason = eligibility(profile, conv, db.get(Connection, conv.connection_id))
    if reason:
        hold(db, conv, reason)
        return
    if profile.mode == "human":
        hold(db, conv, "human_mode")
        return
    if profile.mode == "auto":
        recent = db.scalar(
            select(func.count())
            .select_from(Draft)
            .where(
                Draft.profile_id == profile.id,
                Draft.conversation_id == conv.id,
                Draft.created > time.time() - 3600,
                Draft.status.in_(["sent", "sending", "queued"]),
            )
        )
        if recent >= 12:
            hold(db, conv, "automation_hourly_limit")
            return
    ai = ai or AI()
    try:
        decision = ai.decide(context_for(db, profile, conv))
    except AIUnavailable as exc:
        hold(db, conv, str(exc))
        return
    if decision.action != "allow":
        hold(db, conv, decision.reason, decision.action == "block")
        return
    draft = Draft(
        profile_id=profile.id,
        conversation_id=conv.id,
        revision=conv.revision,
        profile_version=profile.version,
        text=decision.reply,
        status="queued" if profile.mode == "auto" else "pending",
    )
    db.add(draft)
    db.flush()
    if profile.mode == "auto":
        enqueue(
            db,
            "send",
            "send:" + draft.id,
            conv.connection_id,
            {"profile_id": profile.id, "conversation_id": conv.id, "draft_id": draft.id},
        )
    audit(db, "ai", "draft_created", draft.id, profile.id)


def send_draft(db, payload, telegram=None, ai=None):
    profile, conv = scope(db, payload)
    draft = db.scalar(
        select(Draft)
        .where(Draft.id == payload["draft_id"], Draft.profile_id == profile.id, Draft.conversation_id == conv.id)
        .with_for_update()
    )
    if not draft:
        raise InvalidUpdate("invalid_draft_scope")
    if draft.status == "sending":
        draft.status, draft.reason = "uncertain", "worker_interrupted_during_send"
        hold(db, conv, "delivery_uncertain")
        return
    if draft.status != "queued":
        return
    if draft.approved_by:
        approver = db.get(User, draft.approved_by)
        if (
            not approver
            or not approver.active
            or (not approver.admin and not db.get(Membership, (approver.id, profile.id)))
        ):
            draft.status, draft.reason = "blocked", "approver_access_revoked"
            return
    if draft.revision != conv.revision or draft.profile_version != profile.version:
        draft.status, draft.reason = "stale", "context_changed"
        return
    # Drain waiting updates before generating a side effect using an older conversation snapshot.
    pending = db.scalar(
        select(Job.id)
        .where(Job.kind == "update", Job.connection_id == conv.connection_id, Job.status.in_(["queued", "running"]))
        .limit(1)
    )
    if pending:
        raise RetryJob("incoming_update_pending", 2)
    if conv.last_sent > time.time() - 3:
        raise RetryJob("chat_rate_limit", 3)
    telegram, ai = telegram or Telegram(), ai or AI()
    reason = eligibility(profile, conv, db.get(Connection, conv.connection_id))
    if reason:
        draft.status, draft.reason = "blocked", reason
        return
    try:
        decision = ai.decide(context_for(db, profile, conv), candidate=draft.text)
    except AIUnavailable as exc:
        draft.status, draft.reason = "blocked", str(exc)
        hold(db, conv, str(exc))
        return
    if decision.action != "allow":
        draft.status, draft.reason = "blocked", decision.reason
        hold(db, conv, decision.reason, decision.action == "block")
        return
    # Authoritative refresh occurs AFTER expensive AI work and immediately before the send.
    try:
        fresh = telegram.connection(conv.connection_id)
    except TelegramError as exc:
        if exc.code in (400, 401, 403):
            draft.status, draft.reason = "blocked", "connection_refresh_denied"
            hold(db, conv, "connection_refresh_denied")
            return
        raise
    if fresh["id"] != conv.connection_id:
        raise InvalidUpdate("connection_mismatch")
    connection = save_connection(db, fresh)
    reason = eligibility(profile, conv, connection)
    if reason:
        draft.status, draft.reason = "blocked", reason
        return
    # New updates may have arrived while moderation/connection refresh was in flight.
    waiting = db.scalar(
        select(Job.id)
        .where(
            Job.kind == "update", Job.connection_id == conv.connection_id, Job.status.in_(["queued", "running"])
        )
        .limit(1)
    )
    if waiting:
        raise RetryJob("incoming_update_pending", 2)
    # Commit an intent before network IO. A crash or unknown outcome can never cause an automatic resend.
    draft.status = "sending"
    db.commit()
    attachments = list(draft.media or [])
    try:
        if attachments:
            from .media import resolve_chat
            result = None
            for index, item in enumerate(attachments):
                path = resolve_chat(profile.id, str(item.get("name", "")))
                if not path:
                    continue
                is_video = item.get("kind") == "video"
                method = "sendVideo" if is_video else "sendPhoto"
                field = "video" if is_video else "photo"
                caption = draft.text if index == 0 else ""
                result = telegram.send_file(method, conv.connection_id, conv.chat_id, field, path, caption=caption)
            if result is None:
                result = telegram.send(conv.connection_id, conv.chat_id, draft.text)
        else:
            result = telegram.send(conv.connection_id, conv.chat_id, draft.text)
    except TelegramError as exc:
        if exc.code == 429:
            draft.status = "queued"
            db.commit()
            raise RetryJob("telegram_rate_limit", max(1, exc.retry_after)) from None
        draft.status = "uncertain" if exc.uncertain else "blocked"
        draft.reason = str(exc)
        hold(db, conv, "delivery_uncertain" if exc.uncertain else "telegram_send_rejected")
        if exc.code in (401, 403):
            connection.enabled = False
        audit(db, "system", draft.reason, draft.id, profile.id)
        return
    draft.status, draft.telegram_id = "sent", int(result["message_id"])
    conv.last_sent = time.time()
    existing = db.scalar(
        select(Message.id).where(
            Message.profile_id == profile.id,
            Message.conversation_id == conv.id,
            Message.telegram_id == draft.telegram_id,
        )
    )
    if not existing:
        db.add(
            Message(
                profile_id=profile.id,
                conversation_id=conv.id,
                telegram_id=draft.telegram_id,
                direction="outgoing",
                text=draft.text,
                media=attachments,
                created=float(result.get("date", time.time())),
            )
        )
    else:
        db.get(Message, existing).media = attachments
    audit(db, "system", "message_sent", draft.id, profile.id)
