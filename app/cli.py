import argparse
import getpass
import secrets
import time
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import hasher
from .config import settings
from .db import engine
from .models import Audit, Conversation, Draft, Job, LoginAttempt, LoginSession, Memory, Message, User
from .services import audit, invalidate
from .telegram import Telegram
from .worker import connection_lock


def password():
    value = getpass.getpass("Password (14+ characters): ")
    if len(value) < 14 or value != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords must match and have at least 14 characters")
    return value


def purge_conversation(db, conv):
    invalidate(db, conv, "data_erased")
    conv.state, conv.reason = "paused", "data_erased"
    conv.client_name, conv.verification_note, conv.review_note = "Erased client", "", ""
    conv.adult_verified, conv.consent = False, False
    conv.last_incoming = 0
    for msg in db.scalars(
        select(Message).where(Message.profile_id == conv.profile_id, Message.conversation_id == conv.id)
    ):
        msg.text, msg.deleted = "", True
    for draft in db.scalars(select(Draft).where(Draft.profile_id == conv.profile_id, Draft.conversation_id == conv.id)):
        draft.text = ""
        if draft.status not in ("sent", "uncertain"):
            draft.status = "stale"
    db.query(Memory).filter_by(profile_id=conv.profile_id, conversation_id=conv.id).delete()
    for job in db.scalars(select(Job).where(Job.connection_id == conv.connection_id)):
        message = next(
            (
                job.payload[k]
                for k in ("business_message", "edited_business_message", "deleted_business_messages")
                if k in job.payload
            ),
            {},
        )
        if job.payload.get("conversation_id") == conv.id or message.get("chat", {}).get("id") == conv.chat_id:
            job.payload = {}
            job.status = "done"
    audit(db, "retention", "conversation_erased", conv.id, conv.profile_id)


def main():
    parser = argparse.ArgumentParser(description="Kindred operations")
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("create-admin", "set-password", "disable-user"):
        p = subs.add_parser(name)
        p.add_argument("email")
    subs.add_parser("webhook")
    subs.add_parser("webhook-info")
    subs.add_parser("secret")
    subs.add_parser("purge")
    p = subs.add_parser("erase-conversation")
    p.add_argument("profile_id")
    p.add_argument("conversation_id")
    subs.add_parser("demo")
    args = parser.parse_args()
    if args.command == "secret":
        print(secrets.token_urlsafe(48))
        return
    if args.command in ("webhook", "webhook-info"):
        if args.command == "webhook-info":
            data = Telegram().call("getWebhookInfo", {})
            print({k: data.get(k) for k in ("url", "pending_update_count", "last_error_date", "allowed_updates")})
        else:
            if not settings().app_url.startswith("https://") or len(settings().telegram_webhook_secret) < 32:
                raise SystemExit("Set an HTTPS APP_URL and a 32+ character TELEGRAM_WEBHOOK_SECRET first")
            Telegram().call(
                "setWebhook",
                {
                    "url": settings().app_url.rstrip("/") + "/webhooks/telegram",
                    "secret_token": settings().telegram_webhook_secret,
                    "max_connections": 20,
                    "allowed_updates": [
                        "business_connection",
                        "business_message",
                        "edited_business_message",
                        "deleted_business_messages",
                    ],
                    "drop_pending_updates": False,
                },
            )
            print("Webhook registered without dropping pending updates")
        return
    if args.command in ("purge", "erase-conversation"):
        with Session(engine()) as db:
            query = select(Conversation.id, Conversation.connection_id)
            if args.command == "erase-conversation":
                query = query.where(Conversation.id == args.conversation_id, Conversation.profile_id == args.profile_id)
            else:
                query = query.where(
                    Conversation.updated < time.time() - settings().retention_days * 86400,
                    Conversation.reason != "data_erased",
                )
            rows = list(db.execute(query))
        for cid, connection_id in rows:
            with connection_lock(connection_id) as db:
                conv = db.get(Conversation, cid)
                if args.command == "purge" and conv.updated >= time.time() - settings().retention_days * 86400:
                    continue
                purge_conversation(db, conv)
                db.commit()
        with Session(engine()) as db, db.begin():
            cutoff = time.time() - settings().retention_days * 86400
            for job in db.scalars(select(Job).where(Job.created < cutoff, Job.status != "running")):
                job.payload = {}
                if job.status in ("queued", "dead"):
                    job.status = "done"
            db.query(LoginSession).filter(LoginSession.expires < time.time()).delete()
            db.query(LoginAttempt).filter(LoginAttempt.since < time.time() - 86400).delete()
            db.query(Audit).filter(Audit.created < time.time() - 365 * 86400).delete()
        print(f"Erased content for {len(rows)} selected conversations; deduplication tombstones retained")
        return
    if args.command == "demo":
        if settings().environment == "production":
            raise SystemExit("Demo is disabled in production")
        from .demo import seed

        seed()
        return
    with Session(engine()) as db, db.begin():
        email = args.email.strip().lower()
        user = db.scalar(select(User).where(User.email == email))
        if args.command == "create-admin":
            if user:
                raise SystemExit("Account already exists")
            db.add(User(email=email, password_hash=hasher.hash(password()), admin=True))
        else:
            if not user:
                raise SystemExit("Account not found")
            if args.command == "set-password":
                user.password_hash = hasher.hash(password())
            else:
                user.active = False
            db.query(LoginSession).filter_by(user_id=user.id).delete()
        audit(db, "cli", args.command, email)
    print("Done")


if __name__ == "__main__":
    main()
