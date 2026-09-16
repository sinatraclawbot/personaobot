from functools import lru_cache
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from .config import settings


@lru_cache
def engine():
    url = settings().database_url
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    e = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(e, "connect")
        def enable_foreign_keys(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")

    return e


def session():
    with Session(engine(), expire_on_commit=False) as db:
        yield db
