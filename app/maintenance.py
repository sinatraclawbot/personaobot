"""Periodic privacy cleanup. Also exposed through `python -m app.cli purge`."""

import logging
import signal
import threading
import time
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import settings
from .db import engine
from .models import Audit, Conversation, Job, LoginAttempt, LoginSession
from .services import RetryJob
from .worker import connection_lock


def purge():
    from .cli import purge_conversation

    cutoff = time.time() - settings().retention_days * 86400
    with Session(engine()) as db:
        rows = list(
            db.execute(
                select(Conversation.id, Conversation.connection_id)
                .where(Conversation.updated < cutoff, Conversation.reason != "data_erased")
                .limit(500)
            )
        )
    count = 0
    for cid, connection_id in rows:
        try:
            with connection_lock(connection_id) as db:
                conv = db.get(Conversation, cid)
                if conv.updated >= cutoff:
                    continue
                purge_conversation(db, conv)
                db.commit()
                count += 1
        except RetryJob:
            continue
    with Session(engine()) as db, db.begin():
        for job in db.scalars(
            select(Job).where(Job.created < cutoff, Job.status != "running").with_for_update(skip_locked=True)
        ):
            job.payload = {}
            if job.status in ("queued", "dead"):
                job.status = "done"
        db.query(LoginSession).filter(LoginSession.expires < time.time()).delete()
        db.query(LoginAttempt).filter(LoginAttempt.since < time.time() - 86400).delete()
        db.query(Audit).filter(Audit.created < time.time() - 365 * 86400).delete()
    return count


def main():
    logging.basicConfig(level=logging.INFO)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    while not stop.is_set():
        try:
            logging.info("retention_erased count=%s", purge())
        except Exception:
            logging.error("retention_failed")
        stop.wait(3600)


if __name__ == "__main__":
    main()
