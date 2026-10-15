# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.db.session import normalize_url
from app.db.models import Base

config = context.config

# The CLI sets configure_logger=False so it keeps its own logging setup.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

# Plain `alembic ...` commands use $DATABASE_URL (or the default SQLite file);
# the CLI passes the URL explicitly.
if config.get_main_option("sqlalchemy.url") in (None, "", "driver://user:pass@localhost/dbname"):
    url = normalize_url(get_settings().database_url).render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # batch mode lets ALTER-style migrations work on SQLite too
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
