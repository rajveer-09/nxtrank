# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
from pathlib import Path

import orjson

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


def normalize_url(database_url: str):
    """Plain `postgresql://` URLs (as Neon, Supabase etc. hand out) would make SQLAlchemy
    look for psycopg2; use the installed psycopg 3 driver instead."""
    url = make_url(database_url)
    if url.drivername in ("postgresql", "postgres"):
        url = url.set(drivername="postgresql+psycopg")
    return url


def make_engine(database_url: str) -> Engine:
    url = normalize_url(database_url)
    if url.get_backend_name() == "sqlite":
        if url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url)

        @event.listens_for(engine, "connect")
        def _sqlite_fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    connect_args = {}
    if url.host and "-pooler" in url.host:
        # Neon's pooled endpoint runs PgBouncer in transaction mode: don't rely on
        # server-side prepared statements surviving between transactions.
        connect_args["prepare_threshold"] = None
    # small warm pool per process; pre_ping avoids errors after the database restarts or idles
    # orjson parses JSON columns several times faster than the standard library
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10,
                         pool_recycle=1800, pool_timeout=10, connect_args=connect_args,
                         json_deserializer=orjson.loads)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    from app.services import summaries  # here, not at the top: app.services imports app.db

    factory = sessionmaker(engine, expire_on_commit=False)
    summaries.track(factory)  # analytics summaries and data_version follow every commit
    return factory
