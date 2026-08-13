"""Shared pytest fixtures.

Tenant-scoped client and FrozenClock fixtures land here as their owning
steps arrive (Step 8 for the API client, Step 10 for the clock).
"""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    # psycopg3's async mode cannot run on Windows' default ProactorEventLoop
    # (it needs select()/selectors support that Proactor doesn't provide).
    # Without this, every async DB test fails with
    # "psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop'".
    # Must run before pytest-asyncio creates its first event loop, so this
    # lives at conftest.py import time, not inside a fixture.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import secrets
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ankura.config import get_settings
from ankura.db.models import ApiKey, Tenant
from ankura.main import app
from ankura.security import hash_api_key

_settings = get_settings()
_owner_engine = create_async_engine(
    _settings.database_direct_url.replace("postgresql://", "postgresql+psycopg://"),
    connect_args={"prepare_threshold": None},
)
_owner_session_factory = async_sessionmaker(
    _owner_engine, expire_on_commit=False, class_=AsyncSession
)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _seed_tenant_with_api_key() -> tuple[uuid.UUID, str]:
    """Seeds a tenant + one active API key via the owner connection —
    provisioning is an admin action (see db/base.py), never something the
    running app does to itself, so tests seed it the same way real
    operations would.
    """
    tenant_id = uuid.uuid4()
    raw_key = secrets.token_urlsafe(32)
    key_hash = hash_api_key(raw_key, _settings.api_key_pepper)

    async with _owner_session_factory() as session, session.begin():
        session.add(
            Tenant(
                id=tenant_id,
                slug=f"test-{uuid.uuid4().hex[:8]}",
                legal_name="Test Tenant",
                status="ACTIVE",
                residency_region="asia-south1",
                retention_days_raw=7,
            )
        )
        await session.flush()
        session.add(
            ApiKey(id=uuid.uuid4(), tenant_id=tenant_id, key_hash=key_hash, label="test key")
        )

    return tenant_id, raw_key


async def _cleanup_tenant(tenant_id: uuid.UUID) -> None:
    async with _owner_session_factory() as session, session.begin():
        for table in ("applications", "borrowers", "audit_events", "idempotency_keys", "api_keys"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
            )
        await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})


@pytest.fixture
async def tenant_with_api_key() -> AsyncIterator[tuple[uuid.UUID, str]]:
    tenant_id, raw_key = await _seed_tenant_with_api_key()
    yield tenant_id, raw_key
    await _cleanup_tenant(tenant_id)


@pytest.fixture
async def two_tenants_with_api_keys() -> AsyncIterator[
    tuple[tuple[uuid.UUID, str], tuple[uuid.UUID, str]]
]:
    tenant_a = await _seed_tenant_with_api_key()
    tenant_b = await _seed_tenant_with_api_key()
    yield tenant_a, tenant_b
    await _cleanup_tenant(tenant_a[0])
    await _cleanup_tenant(tenant_b[0])


@pytest.fixture
async def tenant_with_revoked_api_key() -> AsyncIterator[tuple[uuid.UUID, str]]:
    tenant_id, raw_key = await _seed_tenant_with_api_key()
    async with _owner_session_factory() as session, session.begin():
        await session.execute(
            text("UPDATE api_keys SET revoked_at = now() WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    yield tenant_id, raw_key
    await _cleanup_tenant(tenant_id)
