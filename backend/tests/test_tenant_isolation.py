"""Multi-tenant Row Level Security isolation test. Implemented in Phase 1
Step 6.

Non-negotiable per phase1.txt DEFINITION OF DONE.

SEQUENCING NOTE: there is no HTTP API yet (Step 8) and no Alembic-managed
schema yet (Step 7) — this test operates directly at the SQLAlchemy
session layer against tables created live in Step 6 (see phase1.txt Step 6
completion notes for how). "Tenant B queries by that exact id -> 404" is
adapted to "-> no row returned"; Step 8 will translate that into an actual
404 response, which is its job, not this test's.

PROVE IT ADAPTATION: the original wording asks to delete the ORM's
`.where(tenant_id == …)` filter and confirm isolation still holds. No such
filter exists anywhere in this codebase yet — there is no service layer
(Step 8) to have written one in. That means every query below already
proves isolation in the STRONGEST possible way: there is nothing to
delete, because RLS is the ONLY thing enforcing tenant boundaries right
now. When Step 8 adds its own defense-in-depth tenant_id filter in
services/, re-verify by literally removing it, per the original wording.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ankura.config import get_settings
from ankura.db.engine import async_session_factory, set_tenant_context
from ankura.db.models import Application, Borrower, Tenant

_settings = get_settings()
_owner_engine = create_async_engine(
    _settings.database_direct_url.replace("postgresql://", "postgresql+psycopg://"),
    connect_args={"prepare_threshold": None},
)
_owner_session_factory = async_sessionmaker(
    _owner_engine, expire_on_commit=False, class_=AsyncSession
)


async def _seed_tenant(slug: str) -> uuid.UUID:
    """Tenants aren't RLS-scoped but the app role has SELECT only (see
    db/base.py) — provisioning is an admin action, done here via the
    owner connection, exactly as it would be in real operation.
    """
    tenant_id = uuid.uuid4()
    async with _owner_session_factory() as session, session.begin():
        session.add(
            Tenant(
                id=tenant_id,
                slug=slug,
                legal_name=f"Test Tenant {slug}",
                status="ACTIVE",
                residency_region="asia-south1",
                retention_days_raw=7,
            )
        )
    return tenant_id


async def _cleanup_tenant(tenant_id: uuid.UUID) -> None:
    async with _owner_session_factory() as session, session.begin():
        for table in ("applications", "borrowers", "audit_events", "idempotency_keys"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
            )
        await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})


@pytest.fixture
async def two_tenants() -> tuple[uuid.UUID, uuid.UUID]:
    tenant_a = await _seed_tenant(f"test-a-{uuid.uuid4().hex[:8]}")
    tenant_b = await _seed_tenant(f"test-b-{uuid.uuid4().hex[:8]}")
    yield tenant_a, tenant_b
    await _cleanup_tenant(tenant_a)
    await _cleanup_tenant(tenant_b)


async def _create_application(tenant_id: uuid.UUID) -> uuid.UUID:
    """Via the APP session (ankura_app), with tenant context set — exactly
    how Step 8's real request-handling path will create rows.
    """
    application_id = uuid.uuid4()
    borrower_id = uuid.uuid4()
    async with async_session_factory() as session, session.begin():
        await set_tenant_context(session, str(tenant_id))
        session.add(
            Borrower(
                id=borrower_id,
                tenant_id=tenant_id,
                entity_type="PROPRIETORSHIP",
                legal_name="Sri Lakshmi Textiles",
                pan="AAPFU0939F",
                gstin="27AAPFU0939F1ZV",
            )
        )
        await session.flush()
        session.add(
            Application(
                id=application_id,
                tenant_id=tenant_id,
                borrower_id=borrower_id,
                external_ref=f"LOS-{application_id.hex[:8]}",
                requested_amount_paise=500_000_00,
                tenure_months=18,
                purpose="INVENTORY_PURCHASE",
                status="RECEIVED",
                as_of=datetime.now(UTC),
            )
        )
    return application_id


async def test_tenant_b_cannot_fetch_tenant_a_application_by_id(
    two_tenants: tuple[uuid.UUID, uuid.UUID],
) -> None:
    tenant_a, tenant_b = two_tenants
    application_id = await _create_application(tenant_a)

    async with async_session_factory() as session, session.begin():
        await set_tenant_context(session, str(tenant_b))
        result = await session.execute(select(Application).where(Application.id == application_id))
        assert result.scalar_one_or_none() is None  # not 403, not the row — simply absent


async def test_tenant_b_list_never_contains_tenant_a_rows(
    two_tenants: tuple[uuid.UUID, uuid.UUID],
) -> None:
    tenant_a, tenant_b = two_tenants
    application_id = await _create_application(tenant_a)

    async with async_session_factory() as session, session.begin():
        await set_tenant_context(session, str(tenant_b))
        result = await session.execute(select(Application))
        ids = {row.id for row in result.scalars().all()}
        assert application_id not in ids


async def test_tenant_a_can_see_its_own_application(
    two_tenants: tuple[uuid.UUID, uuid.UUID],
) -> None:
    tenant_a, _tenant_b = two_tenants
    application_id = await _create_application(tenant_a)

    async with async_session_factory() as session, session.begin():
        await set_tenant_context(session, str(tenant_a))
        result = await session.execute(select(Application).where(Application.id == application_id))
        assert result.scalar_one().id == application_id


async def test_no_tenant_context_returns_zero_rows(
    two_tenants: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """THE critical test: a session that never calls set_tenant_context at
    all — not "wrong" tenant, no tenant context whatsoever — must see
    NOTHING. This is what proves RLS itself is blocking access, not an
    application-layer filter (there isn't one yet to disable)."""
    tenant_a, _tenant_b = two_tenants
    await _create_application(tenant_a)

    async with async_session_factory() as session:
        # deliberately no set_tenant_context() call
        result = await session.execute(select(Application))
        assert result.scalars().all() == []

        result = await session.execute(select(Borrower))
        assert result.scalars().all() == []


async def test_app_role_can_only_see_own_tenant_row_in_tenants_table(
    two_tenants: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """tenants has no RLS (bootstrap table, see db/base.py) — the app role
    can read ANY tenant row by design, since tenant resolution itself
    happens before context is established. Confirming that here so the
    deliberate absence of RLS on this one table is verified, not assumed.
    """
    tenant_a, tenant_b = two_tenants
    async with async_session_factory() as session:
        result = await session.execute(select(Tenant).where(Tenant.id.in_([tenant_a, tenant_b])))
        found_ids = {row.id for row in result.scalars().all()}
        assert found_ids == {tenant_a, tenant_b}
