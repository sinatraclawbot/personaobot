import os
import time
import pytest
from sqlalchemy.orm import Session
from app.config import settings
from app.db import engine
from app.models import Base, Connection, Conversation, Message, Profile
from app.schemas import Decision, ProfileConfig


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.getenv("TEST_POSTGRES_URL", "sqlite:///" + str(tmp_path / "test.db")))
    monkeypatch.setenv("APP_URL", "http://testserver")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-secret-with-at-least-32-characters")
    settings.cache_clear()
    engine.cache_clear()
    Base.metadata.drop_all(engine())
    Base.metadata.create_all(engine())
    yield
    engine().dispose()
    engine.cache_clear()
    settings.cache_clear()


@pytest.fixture
def db(database):
    with Session(engine(), expire_on_commit=False) as session:
        yield session


def make_profile(db, owner=101, name="Sofia", mode="approval", chat=700):
    profile = Profile(
        name=name,
        owner_telegram_id=owner,
        enabled=True,
        lawful_reviewed=True,
        mode=mode,
        config=ProfileConfig().model_dump(),
    )
    db.add(profile)
    db.flush()
    conn = Connection(
        id="connection-" + str(owner),
        profile_id=profile.id,
        owner_id=owner,
        user_chat_id=owner,
        enabled=True,
        rights={"can_reply": True},
    )
    db.add(conn)
    db.flush()
    conv = Conversation(
        profile_id=profile.id,
        connection_id=conn.id,
        chat_id=chat,
        adult_verified=True,
        consent=True,
        last_incoming=time.time(),
    )
    db.add(conv)
    db.flush()
    db.add(
        Message(
            profile_id=profile.id,
            conversation_id=conv.id,
            telegram_id=1,
            direction="incoming",
            text="What languages do you speak?",
        )
    )
    db.commit()
    return profile, conn, conv


@pytest.fixture
def scope(db):
    return make_profile(db)


class FakeAI:
    def __init__(self, action="allow", reason="safe", reply="I'm Sofia's AI assistant. Sofia speaks English."):
        self.action, self.reason, self.reply = action, reason, reply
        self.contexts = []

    def decide(self, context, candidate=None):
        self.contexts.append((context, candidate))
        return Decision(action=self.action, reason=self.reason, reply=self.reply if self.action == "allow" else "")


class FakeTelegram:
    def __init__(self, conn, fail=None, rights=None, enabled=True):
        self.conn, self.fail = conn, fail
        self.rights = rights if rights is not None else {"can_reply": True}
        self.enabled = enabled
        self.sent = []

    def connection(self, cid):
        return {
            "id": cid,
            "user": {"id": self.conn.owner_id},
            "user_chat_id": self.conn.owner_id,
            "date": 1,
            "is_enabled": self.enabled,
            "rights": self.rights,
        }

    def send(self, cid, chat, text):
        self.sent.append((cid, chat, text))
        if self.fail:
            raise self.fail
        return {"message_id": 500, "date": int(time.time())}
