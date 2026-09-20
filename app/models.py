import time
import uuid
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def uid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"
    id = Column(String(36), primary_key=True, default=uid)
    email = Column(String(254), nullable=False, unique=True)
    password_hash = Column(Text, nullable=False)
    admin = Column(Boolean, nullable=False, default=False)
    active = Column(Boolean, nullable=False, default=True)


class LoginSession(Base):
    __tablename__ = "sessions"
    token_hash = Column(String(64), primary_key=True)
    user_id = Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    csrf = Column(String(64), nullable=False)
    expires = Column(Float, nullable=False, index=True)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    key = Column(String(64), primary_key=True)
    count = Column(Integer, nullable=False, default=0)
    since = Column(Float, nullable=False)


class Profile(Base):
    __tablename__ = "profiles"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String(100), nullable=False)
    owner_telegram_id = Column(BigInteger, nullable=False, unique=True)
    mode = Column(String(16), nullable=False, default="approval")
    enabled = Column(Boolean, nullable=False, default=False)
    lawful_reviewed = Column(Boolean, nullable=False, default=False)
    config = Column(JSON, nullable=False, default=dict)
    version = Column(Integer, nullable=False, default=1)
    created = Column(Float, nullable=False, default=time.time)
    __table_args__ = (CheckConstraint("mode in ('auto','approval','human')"),)


class Membership(Base):
    __tablename__ = "memberships"
    user_id = Column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    profile_id = Column(ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)


class Connection(Base):
    __tablename__ = "connections"
    id = Column(String(256), primary_key=True)
    profile_id = Column(ForeignKey("profiles.id"), nullable=True, index=True)
    owner_id = Column(BigInteger, nullable=False)
    user_chat_id = Column(BigInteger, nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    rights = Column(JSON, nullable=False, default=dict)
    established = Column(BigInteger, nullable=False, default=0)
    checked = Column(Float, nullable=False, default=time.time)
    last_update_id = Column(BigInteger, nullable=False, default=-1)
    last_update_seen = Column(Float, nullable=False, default=0)
    __table_args__ = (UniqueConstraint("profile_id", "id"),)


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(String(36), primary_key=True, default=uid)
    profile_id = Column(ForeignKey("profiles.id"), nullable=False)
    connection_id = Column(String(256), nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    channel = Column(String(16), nullable=False, default="telegram")
    whatsapp_chat_id = Column(String(128), nullable=True)
    client_name = Column(String(200), nullable=False, default="Client")
    state = Column(String(16), nullable=False, default="active")
    reason = Column(String(100), nullable=False, default="")
    adult_verified = Column(Boolean, nullable=False, default=False)
    consent = Column(Boolean, nullable=False, default=False)
    verification_note = Column(Text, nullable=False, default="")
    review_note = Column(Text, nullable=False, default="")
    last_incoming = Column(Float, nullable=False, default=0)
    last_sent = Column(Float, nullable=False, default=0)
    revision = Column(Integer, nullable=False, default=0)
    updated = Column(Float, nullable=False, default=time.time)
    __table_args__ = (
        ForeignKeyConstraint(["profile_id", "connection_id"], ["connections.profile_id", "connections.id"]),
        UniqueConstraint("connection_id", "chat_id"),
        UniqueConstraint("profile_id", "id"),
        CheckConstraint("state in ('active','paused','escalated','blocked')"),
        Index("ix_conversations_profile_updated", "profile_id", "updated"),
    )


class Message(Base):
    __tablename__ = "messages"
    id = Column(String(36), primary_key=True, default=uid)
    profile_id = Column(String(36), nullable=False)
    conversation_id = Column(String(36), nullable=False)
    telegram_id = Column(BigInteger, nullable=False)
    direction = Column(String(16), nullable=False)
    text = Column(Text, nullable=False, default="")
    media = Column(JSON, nullable=False, default=list)
    deleted = Column(Boolean, nullable=False, default=False)
    event_time = Column(Float, nullable=False, default=0)
    last_update_id = Column(BigInteger, nullable=False, default=-1)
    created = Column(Float, nullable=False, default=time.time)
    __table_args__ = (
        ForeignKeyConstraint(["profile_id", "conversation_id"], ["conversations.profile_id", "conversations.id"]),
        UniqueConstraint("conversation_id", "telegram_id"),
        Index("ix_messages_context", "profile_id", "conversation_id", "created"),
        CheckConstraint("direction in ('incoming','outgoing','owner','unsupported')"),
    )


class Memory(Base):
    __tablename__ = "memories"
    id = Column(String(36), primary_key=True, default=uid)
    profile_id = Column(String(36), nullable=False)
    conversation_id = Column(String(36), nullable=False)
    text = Column(Text, nullable=False)
    created = Column(Float, nullable=False, default=time.time)
    __table_args__ = (
        ForeignKeyConstraint(["profile_id", "conversation_id"], ["conversations.profile_id", "conversations.id"]),
    )


class Draft(Base):
    __tablename__ = "drafts"
    id = Column(String(36), primary_key=True, default=uid)
    profile_id = Column(String(36), nullable=False)
    conversation_id = Column(String(36), nullable=False)
    revision = Column(Integer, nullable=False)
    profile_version = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    media = Column(JSON, nullable=False, default=list)
    status = Column(String(20), nullable=False, default="pending")
    reason = Column(String(100), nullable=False, default="")
    approved_by = Column(ForeignKey("users.id"), nullable=True)
    created = Column(Float, nullable=False, default=time.time)
    telegram_id = Column(BigInteger, nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(["profile_id", "conversation_id"], ["conversations.profile_id", "conversations.id"]),
        CheckConstraint("status in ('pending','queued','sending','sent','rejected','stale','blocked','uncertain')"),
        Index("ix_drafts_profile_status", "profile_id", "status"),
    )


class Job(Base):
    __tablename__ = "jobs"
    id = Column(String(36), primary_key=True, default=uid)
    kind = Column(String(16), nullable=False)
    dedupe = Column(String(300), nullable=False, unique=True)
    connection_id = Column(String(256), nullable=True, index=True)
    payload = Column(JSON, nullable=False)
    status = Column(String(16), nullable=False, default="queued")
    attempts = Column(Integer, nullable=False, default=0)
    available = Column(Float, nullable=False, default=time.time)
    lease_until = Column(Float, nullable=True)
    error = Column(String(100), nullable=False, default="")
    created = Column(Float, nullable=False, default=time.time)
    __table_args__ = (Index("ix_jobs_claim", "status", "available", "created"),)


class Audit(Base):
    __tablename__ = "audit"
    id = Column(String(36), primary_key=True, default=uid)
    profile_id = Column(ForeignKey("profiles.id"), nullable=True, index=True)
    actor = Column(String(100), nullable=False)
    action = Column(String(100), nullable=False)
    target = Column(String(256), nullable=False, default="")
    created = Column(Float, nullable=False, default=time.time)


class Heartbeat(Base):
    __tablename__ = "heartbeats"
    id = Column(String(100), primary_key=True)
    seen = Column(Float, nullable=False)
