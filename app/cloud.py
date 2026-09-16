"""Cloud entry point with serialized schema upgrades and platform port support."""
import argparse
import os
import sys
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from .db import engine


def migrate():
    db = engine()
    if db.dialect.name != 'postgresql':
        raise RuntimeError('Cloud deployment requires PostgreSQL')
    # Every service can start independently; only one migrator proceeds at a time.
    with db.connect().execution_options(isolation_level='AUTOCOMMIT') as lock:
        lock.execute(text("SET statement_timeout = '120s'"))
        lock.execute(text('SELECT pg_advisory_lock(682017413)'))
        try:
            command.upgrade(Config('alembic.ini'), 'head')
        finally:
            lock.execute(text('SELECT pg_advisory_unlock(682017413)'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('role', choices=['web', 'worker', 'purge'])
    role = parser.parse_args().role
    migrate()
    if role == 'web':
        args = ['-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0',
                '--port', str(int(os.environ.get('PORT', '10000'))),
                '--no-access-log', '--no-proxy-headers']
    elif role == 'worker':
        args = ['-m', 'app.worker']
    else:
        args = ['-m', 'app.cli', 'purge']
    os.execv(sys.executable, [sys.executable, *args])


if __name__ == '__main__':
    main()
