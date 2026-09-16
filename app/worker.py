import hashlib
import logging
import os
import random
import signal
import time
from contextlib import contextmanager
from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session
from .config import settings
from .db import engine
from .models import Heartbeat, Job
from .services import InvalidUpdate, RetryJob, generate, process_update, send_draft
from .telegram import TelegramError

log = logging.getLogger("platform.worker")


def lock_number(value):
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big", signed=True)


@contextmanager
def connection_lock(connection_id):
    # A dedicated physical DB connection keeps this session advisory lock across the send-intent commit.
    with engine().connect() as conn:
        locked = False
        try:
            if conn.dialect.name == "postgresql" and connection_id:
                locked = bool(
                    conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_number(connection_id)})
                )
                conn.commit()
                if not locked:
                    raise RetryJob("connection_busy", 1)
            with Session(bind=conn, expire_on_commit=False) as db:
                yield db
        finally:
            if locked:
                conn.rollback()
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_number(connection_id)})
                conn.commit()


def claim():
    with Session(engine(), expire_on_commit=False) as db, db.begin():
        job = db.scalar(
            select(Job)
            .where(
                or_(
                    (Job.status == "queued") & (Job.available <= time.time()),
                    (Job.status == "running") & (Job.lease_until < time.time()),
                )
            )
            .order_by((Job.kind != "update"), Job.created)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return None
        job.status, job.lease_until = "running", time.time() + settings().worker_lease_seconds
        job.attempts += 1
        return job.id, job.connection_id


def run_once():
    claimed = claim()
    if not claimed:
        return False
    jid, cid = claimed
    try:
        with connection_lock(cid) as db:
            job = db.get(Job, jid)
            if job.status != "running":
                return True
            {"update": process_update, "generate": generate, "send": send_draft}[job.kind](db, job.payload)
            job.status, job.error, job.lease_until = "done", "", None
            if job.kind == "update":
                job.payload = {}  # Inbox is transport, not an indefinite second copy of messages.
            db.commit()
    except Exception as exc:
        with Session(engine()) as db, db.begin():
            job = db.get(Job, jid)
            wait = exc.delay if isinstance(exc, RetryJob) else min(300, 2**job.attempts + random.random())
            if isinstance(exc, TelegramError) and exc.retry_after:
                wait = exc.retry_after
            # Contention and queue ordering are not failures and must not exhaust the retry budget.
            transient = isinstance(exc, RetryJob) and exc.reason in (
                "connection_busy",
                "incoming_update_pending",
                "chat_rate_limit",
                "telegram_rate_limit",
            )
            if transient:
                job.attempts -= 1
            job.status = (
                "dead" if isinstance(exc, InvalidUpdate) or job.attempts >= settings().job_max_attempts else "queued"
            )
            job.available, job.lease_until = time.time() + wait, None
            job.error = (
                exc.reason
                if isinstance(exc, RetryJob)
                else str(exc)
                if isinstance(exc, (InvalidUpdate, TelegramError))
                else type(exc).__name__
            )
            log.warning("job_result id=%s status=%s code=%s", job.id, job.status, job.error)
    return True


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    worker_id = f"{os.uname().nodename}:{os.getpid()}"
    while running:
        try:
            with Session(engine()) as db, db.begin():
                db.merge(Heartbeat(id=worker_id, seen=time.time()))
            if not run_once():
                time.sleep(0.5)
        except Exception:
            log.error("worker_database_unavailable")
            time.sleep(5)


if __name__ == "__main__":
    main()
