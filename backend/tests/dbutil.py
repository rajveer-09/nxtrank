# Author: Rajveer Sharma
# © NxtWave
# Date: 15 October 2026
"""The database each test uses: a new SQLite file, or with TEST_DATABASE_URL a local
PostgreSQL that is wiped before every test (only localhost is accepted):

    docker run -d --name dash-pg-test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=dash_test \\
        -p 127.0.0.1:55432:5432 --tmpfs /var/lib/postgresql/data postgres:17-alpine -c fsync=off
    TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:55432/dash_test pytest
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.db.session import normalize_url

PG_URL = os.environ.get("TEST_DATABASE_URL")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

needs_postgres = pytest.mark.skipif(not PG_URL, reason="needs TEST_DATABASE_URL (PostgreSQL)")


def fresh_url(tmp_path, name: str = "test.db") -> str:
    """The URL of an empty database for this test (no tables yet)."""
    if not PG_URL:
        return f"sqlite:///{(tmp_path / name).as_posix()}"
    url = normalize_url(PG_URL)
    if url.host not in LOCAL_HOSTS:
        raise RuntimeError(f"TEST_DATABASE_URL must be a local database (the tests wipe it), not {url.host}")
    engine = create_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as c:
            # connections left open by earlier tests' engines would block DROP SCHEMA
            c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                           "WHERE datname = current_database() AND pid <> pg_backend_pid()"))
            c.execute(text("DROP SCHEMA public CASCADE"))
            c.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()
    return PG_URL
