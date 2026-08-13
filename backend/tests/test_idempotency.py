"""Idempotency-Key tests. Implemented in Phase 1 Step 9.

Covers: missing key -> 400, byte-identical replay, exactly one row after
repeated replays, mismatched body -> 409, and a genuine concurrent-duplicate
-request race creating exactly one application. See phase1.txt Step 9 PROVE
IT (run the concurrency case 20x in CI).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ankura.clock import FrozenClock, SystemClock
from ankura.config import get_settings
from ankura.db.models import Application, IdempotencyKey
from ankura.main import app
from ankura.services import idempotency as idempotency_service

VALID_GSTIN = "27AAPFU0939F1ZV"
VALID_PAN = "AAPFU0939F"

_settings = get_settings()
_owner_engine = create_async_engine(
    _settings.database_direct_url.replace("postgresql://", "postgresql+psycopg://"),
    connect_args={"prepare_threshold": None},
)
_owner_session_factory = async_sessionmaker(
    _owner_engine, expire_on_commit=False, class_=AsyncSession
)


def _headers(raw_key: str, idempotency_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}", "Idempotency-Key": idempotency_key}


def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "external_ref": f"LOS-{uuid.uuid4().hex[:10]}",
        "borrower_pan": VALID_PAN,
        "borrower_gstin": VALID_GSTIN,
        "entity_type": "PROPRIETORSHIP",
        "legal_name": "Sri Lakshmi Textiles",
        "requested_amount_paise": 500_000_00,
        "tenure_months": 18,
        "purpose": "INVENTORY_PURCHASE",
    }
    base.update(overrides)
    return base


async def _count_applications(tenant_id: uuid.UUID) -> int:
    async with _owner_session_factory() as session:
        result = await session.execute(
            select(func.count()).select_from(Application).where(Application.tenant_id == tenant_id)
        )
        return int(result.scalar_one())


async def test_missing_idempotency_key_returns_400(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    _, raw_key = tenant_with_api_key
    response = await client.post(
        "/v1/applications", json=_payload(), headers={"Authorization": f"Bearer {raw_key}"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_MISSING"


async def test_replay_returns_byte_identical_body_and_status(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    _, raw_key = tenant_with_api_key
    key = str(uuid.uuid4())
    payload = _payload()

    first = await client.post("/v1/applications", json=payload, headers=_headers(raw_key, key))
    second = await client.post("/v1/applications", json=payload, headers=_headers(raw_key, key))

    assert first.status_code == second.status_code == 201
    assert first.content == second.content


async def test_five_replays_leave_exactly_one_application_row(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    tenant_id, raw_key = tenant_with_api_key
    key = str(uuid.uuid4())
    payload = _payload()

    for _ in range(5):
        response = await client.post(
            "/v1/applications", json=payload, headers=_headers(raw_key, key)
        )
        assert response.status_code == 201

    assert await _count_applications(tenant_id) == 1


async def test_same_key_different_body_returns_409(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    _, raw_key = tenant_with_api_key
    key = str(uuid.uuid4())

    first = await client.post("/v1/applications", json=_payload(), headers=_headers(raw_key, key))
    assert first.status_code == 201

    second = await client.post(
        "/v1/applications",
        json=_payload(legal_name="A Different Legal Name"),
        headers=_headers(raw_key, key),
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSE"


async def test_concurrent_identical_requests_create_exactly_one_application(
    tenant_with_api_key: tuple[uuid.UUID, str],
) -> None:
    tenant_id, raw_key = tenant_with_api_key
    key = str(uuid.uuid4())
    payload = _payload()

    async def _post() -> Any:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            return await ac.post("/v1/applications", json=payload, headers=_headers(raw_key, key))

    responses = await asyncio.gather(*(_post() for _ in range(8)))

    assert all(r.status_code == 201 for r in responses)
    bodies = {r.content for r in responses}
    assert len(bodies) == 1, "every concurrent replay must return the identical winning body"
    assert await _count_applications(tenant_id) == 1


async def test_purge_expired_deletes_only_keys_past_their_ttl(
    tenant_with_api_key: tuple[uuid.UUID, str],
) -> None:
    tenant_id, _ = tenant_with_api_key
    now = SystemClock().now()

    async with _owner_session_factory() as session, session.begin():
        session.add_all(
            [
                IdempotencyKey(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    key="expired",
                    request_fingerprint="f1",
                    response_status=201,
                    response_body={},
                    expires_at=now - timedelta(hours=1),
                ),
                IdempotencyKey(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    key="live",
                    request_fingerprint="f2",
                    response_status=201,
                    response_body={},
                    expires_at=now + timedelta(hours=1),
                ),
            ]
        )

    async with _owner_session_factory() as session, session.begin():
        deleted = await idempotency_service.purge_expired(session, FrozenClock(now))

    assert deleted == 1
    async with _owner_session_factory() as session:
        result = await session.execute(
            select(IdempotencyKey.key).where(IdempotencyKey.tenant_id == tenant_id)
        )
        assert {row.key for row in result} == {"live"}
