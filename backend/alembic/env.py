"""Alembic environment — Step 7.

Always connects via DATABASE_DIRECT_URL (unpooled, neondb_owner), never
DATABASE_URL — migrations run DDL and are never subject to Row Level
Security; the running app must never see this connection. See
final architecture.txt §14.3 and db/engine.py's own docstring for why the
app's engine is built completely separately.
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from ankura.config import get_settings
from ankura.db.base import Base

# Importing db.models (not just db.base) populates Base.metadata with every
# table — required for autogenerate to see the whole schema.
from ankura.db.models import (  # noqa: F401
    ApiKey,
    Application,
    AuditEvent,
    Borrower,
    IdempotencyKey,
    Tenant,
)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _to_async_dsn(raw_url: str) -> str:
    """Same qualification rule as db/engine.py's _to_async_dsn — kept as an
    independent copy since Alembic's env.py runs standalone, outside the
    app's own import graph, and is not itself the app engine.
    """
    if raw_url.startswith("postgresql+psycopg://"):
        return raw_url
    if raw_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw_url[len("postgresql://") :]
    raise ValueError(f"unexpected DSN scheme: {raw_url!r}")


# DATABASE_DIRECT_URL only — see module docstring. Overrides whatever
# placeholder is in alembic.ini so the real secret never has to live there.
config.set_main_option("sqlalchemy.url", _to_async_dsn(get_settings().database_direct_url))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"prepare_threshold": None},
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    # psycopg3's async mode cannot run on Windows' default ProactorEventLoop
    # — same gotcha documented in tests/conftest.py for Step 4's engine tests.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
