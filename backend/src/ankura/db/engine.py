"""Async SQLAlchemy engine, session factory, and the RLS tenant-context hook.

Only the APP's engine lives here (DATABASE_URL / APP_DB_ROLE). Alembic
(Step 7) builds its own engine from DATABASE_DIRECT_URL / neondb_owner
independently — migrations need owner privileges to run DDL and are never
subject to Row Level Security.

Connection pooling is intentionally off for both URLs right now (owner
decision, see backend/.env) — there is currently no PgBouncer in the path.
`prepare_threshold=None` is still set defensively: if DATABASE_URL is ever
pointed at a pooled ("-pooler") endpoint without someone remembering to
revisit this file, prepared statements silently breaking is exactly the
failure mode final architecture.txt §14.3 describes, and this setting is
what prevents it either way.

See phase1.txt Step 4 and final architecture.txt §14.3 / §14.4.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ankura.config import get_settings


def _to_async_dsn(raw_url: str) -> str:
    """Qualify a raw `postgresql://` DSN (Neon's own format) with the
    psycopg3 driver so SQLAlchemy's async engine picks the right dialect.
    Already-qualified URLs pass through unchanged.
    """
    if raw_url.startswith("postgresql+psycopg://"):
        return raw_url
    if raw_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw_url[len("postgresql://") :]
    # config.py's field_validator already rejects anything else reaching here.
    raise ValueError(f"unexpected DSN scheme: {raw_url!r}")


def _build_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        _to_async_dsn(settings.database_url),
        connect_args={"prepare_threshold": None},
        pool_pre_ping=True,
    )


# Built once at import time. Cheap: create_async_engine does not connect —
# it only configures the pool; the first real connection happens lazily on
# first use (or explicitly, e.g. in a readiness check).
engine: AsyncEngine = _build_engine()

async_session_factory = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one transaction per request.

    `session.begin()` commits on clean exit and rolls back on exception —
    there is exactly one transaction boundary per request, which is what
    Step 6's `SET LOCAL`-equivalent tenant context (set_tenant_context
    below) depends on to stay scoped to that single request.
    """
    async with async_session_factory() as session, session.begin():
        yield session


async def set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    """Scope every subsequent query on this session's current transaction
    to one tenant, via Postgres Row Level Security.

    Uses `set_config(name, value, is_local=true)` rather than a literal
    `SET LOCAL app.tenant_id = '...'` string for two reasons: it is safely
    parameterized (tenant_id never gets string-interpolated into SQL), and
    `is_local=true` gives the exact same transaction-scoped semantics as
    `SET LOCAL` — required so a pooled connection can never leak one
    tenant's context into the next request. See final architecture.txt
    §14.4. Must be called inside an open transaction (i.e. after
    `get_db_session()` has already started one via `session.begin()`).
    """
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


async def ping() -> bool:
    """Real `SELECT 1` round trip. Used by Step 8's /readyz — liveness
    should not depend on the database, readiness should.
    """
    async with async_session_factory() as session:
        result = await session.execute(text("SELECT 1"))
        return bool(result.scalar_one() == 1)
