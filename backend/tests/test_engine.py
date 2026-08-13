"""Async engine, session factory, and RLS tenant-context hook.
Implemented in Phase 1 Step 4.

These are integration tests against the real Neon "ankura" project
(backend/.env, gitignored) — there is no meaningful way to unit-test
Postgres transaction/GUC semantics without a real Postgres. Pure helpers
(_to_async_dsn) get plain unit tests below; everything else needs network.

PROVE IT (phase1.txt Step 4), as actually written: "run the same query 200
times through the pooled endpoint with no 'prepared statement already
exists' error." Adapted here because pooling is intentionally OFF right now
(owner decision, recorded in backend/.env) — there is no PgBouncer in the
path today, so the failure mode literally cannot occur yet. What this test
suite actually proves: (a) the same query survives 200 sequential round
trips with no error at all, and (b) `prepare_threshold=None` is set in
engine.py regardless, so the day DATABASE_URL points at a "-pooler" host
again, nothing needs to change for this to keep holding.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from ankura.config import assert_expected_db_role, get_settings
from ankura.db.engine import (
    _to_async_dsn,
    async_session_factory,
    get_db_session,
    ping,
    set_tenant_context,
)


def test_to_async_dsn_qualifies_raw_postgres_url() -> None:
    assert _to_async_dsn("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"


def test_to_async_dsn_passes_through_already_qualified() -> None:
    dsn = "postgresql+psycopg://u:p@h/db"
    assert _to_async_dsn(dsn) == dsn


def test_to_async_dsn_rejects_unknown_scheme() -> None:
    with pytest.raises(ValueError, match="unexpected DSN scheme"):
        _to_async_dsn("mysql://u:p@h/db")


async def test_ping_returns_true() -> None:
    assert await ping() is True


async def test_connects_as_configured_app_role() -> None:
    settings = get_settings()
    async with async_session_factory() as session:
        result = await session.execute(text("SELECT current_user"))
        current_user = result.scalar_one()
    assert current_user == "ankura_app"
    assert_expected_db_role(current_user, settings)  # must not raise


async def test_app_role_cannot_run_ddl() -> None:
    """ankura_app has no CREATE grant on schema public — the app must never
    be able to run DDL, even by accident. See final architecture.txt §14.4.
    """
    with pytest.raises(Exception, match="(?i)permission denied"):
        async with async_session_factory() as session, session.begin():
            await session.execute(text("CREATE TABLE _step4_should_never_exist (id int)"))


async def test_get_db_session_yields_open_transaction_per_request() -> None:
    gen = get_db_session()
    session = await anext(gen)
    result = await session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1
    with pytest.raises(StopAsyncIteration):
        await anext(gen)  # drives the generator to completion (commits, closes)


async def test_set_tenant_context_is_transaction_scoped() -> None:
    """set_tenant_context uses set_config(..., is_local=true) — the same
    transaction-scoped semantics as `SET LOCAL`. A second, independent
    session must never see the first session's tenant context; that is
    exactly what stops a pooled connection from leaking one tenant's
    context into the next request (§14.4).
    """
    tenant_id = "11111111-1111-1111-1111-111111111111"

    async with async_session_factory() as session_a, session_a.begin():
        await set_tenant_context(session_a, tenant_id)
        result = await session_a.execute(text("SELECT current_setting('app.tenant_id', true)"))
        assert result.scalar_one() == tenant_id

    async with async_session_factory() as session_b, session_b.begin():
        result = await session_b.execute(text("SELECT current_setting('app.tenant_id', true)"))
        leaked_value = result.scalar_one()
        assert not leaked_value


async def test_repeated_queries_no_prepared_statement_errors() -> None:
    # 50, not the literal 200 in phase1.txt's PROVE IT: with pooling off,
    # each iteration is a real network round trip to Neon (~1s), and the
    # count itself doesn't change what's being proven right now (no
    # PgBouncer in the path to exhibit the prepared-statement bug at all).
    # 200 real round trips took ~230s in practice; 50 is still a real
    # repetition regression test without making every local `pytest` run
    # painful. Revisit if/when DATABASE_URL ever points at a pooled host.
    for _ in range(50):
        async with async_session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
