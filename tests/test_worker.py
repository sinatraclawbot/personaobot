import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select
from app.db import engine
from app.models import Draft, Job, Memory, Message
from app.services import RetryJob, enqueue
from app.worker import claim, connection_lock, run_once
from conftest import FakeAI, FakeTelegram
from test_pipeline import incoming, create_draft


def test_durable_update_job_processes_once(db, scope):
    _, conn, conv = scope
    enqueue(db, "update", "update:10", conn.id, incoming(conn))
    db.commit()
    assert run_once()
    db.expire_all()
    job = db.scalar(select(Job).where(Job.dedupe == "update:10"))
    assert job.status == "done" and job.payload == {}
    assert (
        len(list(db.scalars(select(Message).where(Message.conversation_id == conv.id, Message.telegram_id == 2)))) == 1
    )


def test_worker_reclaims_expired_lease(db):
    job = Job(kind="update", dedupe="expired", payload={"update_id": 1}, status="running", lease_until=time.time() - 1)
    db.add(job)
    db.commit()
    assert claim()[0] == job.id


def test_dead_letter_after_failed_retries(db, monkeypatch):
    import app.worker as worker

    job = Job(kind="update", dedupe="error", payload={"update_id": 1}, attempts=5)
    db.add(job)
    db.commit()

    def broken(*args):
        raise RuntimeError("This must never appear in persistent errors: secret")

    monkeypatch.setattr(worker, "process_update", broken)
    assert run_once()
    db.expire_all()
    assert db.get(Job, job.id).status == "dead"
    assert db.get(Job, job.id).error == "RuntimeError"


def test_contention_does_not_exhaust_retries(db, monkeypatch):
    import app.worker as worker

    job = Job(kind="update", dedupe="busy", payload={"update_id": 1}, attempts=5)
    db.add(job)
    db.commit()

    def busy(*args):
        raise RetryJob("connection_busy", 1)

    monkeypatch.setattr(worker, "process_update", busy)
    assert run_once()
    db.expire_all()
    assert db.get(Job, job.id).status == "queued" and db.get(Job, job.id).attempts == 5


def test_full_webhook_to_worker_to_send(db, scope, monkeypatch):
    import app.services as services
    from fastapi.testclient import TestClient
    from app.main import app
    from app.config import settings

    p, conn, conv = scope
    p.mode = "auto"
    db.commit()
    telegram, ai = FakeTelegram(conn), FakeAI()
    monkeypatch.setattr(services, "Telegram", lambda: telegram)
    monkeypatch.setattr(services, "AI", lambda: ai)
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/telegram",
            json=incoming(conn),
            headers={"x-telegram-bot-api-secret-token": settings().telegram_webhook_secret},
        )
        assert response.status_code == 200
    assert run_once()  # ingress
    assert run_once()  # generation
    assert run_once()  # permission check and send
    assert not run_once()
    db.expire_all()
    assert db.scalar(select(Draft)).status == "sent" and len(telegram.sent) == 1
    assert telegram.sent[0][:2] == (conn.id, conv.chat_id)


def test_retention_erases_content_but_retains_tombstones(db, scope):
    from app.cli import purge_conversation

    p, conn, conv = scope
    draft, _ = create_draft(db, p, conv)
    db.add(Memory(profile_id=p.id, conversation_id=conv.id, text="private note"))
    db.add(Job(kind="update", dedupe="retain", connection_id=conn.id, payload=incoming(conn)))
    db.commit()
    purge_conversation(db, conv)
    db.commit()
    assert conv.state == "paused" and not conv.consent and not conv.adult_verified
    assert draft.text == ""
    assert all(m.text == "" and m.deleted for m in db.scalars(select(Message)))
    assert not db.scalar(select(Memory))
    assert db.scalar(select(Job)).payload == {}


@pytest.mark.postgres
def test_postgres_skip_locked_and_advisory_locks(db, scope):
    if engine().dialect.name != "postgresql":
        pytest.skip("Set TEST_POSTGRES_URL to a disposable PostgreSQL database")
    _, conn, _ = scope
    for i in range(8):
        db.add(Job(kind="update", dedupe=f"parallel-{i}", payload={"update_id": i}, connection_id=conn.id))
    db.commit()
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: claim(), range(8)))
    assert len({item[0] for item in claims}) == 8
    with connection_lock(conn.id):
        with pytest.raises(RetryJob, match="connection_busy"):
            with connection_lock(conn.id):
                pass


@pytest.mark.postgres
def test_profile_lock_survives_send_intent_commit(db, scope):
    if engine().dialect.name != "postgresql":
        pytest.skip("Set TEST_POSTGRES_URL to a disposable PostgreSQL database")
    _, conn, _ = scope
    with connection_lock(conn.id) as locked:
        locked.commit()
        with pytest.raises(RetryJob):
            with connection_lock(conn.id):
                pass
    with connection_lock(conn.id):
        pass
