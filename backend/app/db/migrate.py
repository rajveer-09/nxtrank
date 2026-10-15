# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Run Alembic migrations from code (used by the CLI; `alembic upgrade head` also works)."""

import logging

from alembic import command
from alembic.config import Config

from app.config import BACKEND_DIR
from app.db.session import make_engine, normalize_url


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    url = normalize_url(database_url).render_as_string(hide_password=False)
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False  # keep the app's logging setup
    return cfg


def upgrade(database_url: str) -> None:
    make_engine(database_url).dispose()  # creates the SQLite data directory if needed
    alembic_log = logging.getLogger("alembic")
    if alembic_log.level == logging.NOTSET:
        alembic_log.setLevel(logging.WARNING)  # per-command "Context impl ..." noise
    command.upgrade(alembic_config(database_url), "head")
    _build_summaries(database_url)


def _build_summaries(database_url: str) -> None:
    """Fill the analytics summaries the first time (after the migration that adds them,
    or on a new database). Later changes keep them current as they're committed."""
    from app.db.session import make_session_factory
    from app.services import summaries

    engine = make_engine(database_url)
    try:
        with make_session_factory(engine)() as session:
            if summaries.ensure_built(session):
                logging.getLogger(__name__).info("analytics summaries built")
    finally:
        engine.dispose()
