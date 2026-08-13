"""Audit event skeleton tests. Implemented in Phase 1 Step 11.

Covers: append-only writer + chain linkage, hash-chain verification over
100 events, tamper detection naming the first broken link (PROVE IT), the
six P1 event types actually getting emitted end to end, and the PII rule
(no raw PAN/GSTIN in payload_json). See phase1.txt Step 11.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ankura.clock import SystemClock
from ankura.config import get_settings
from ankura.db.engine import async_session_factory, set_tenant_context
from ankura.db.models import AuditEvent
from ankura.services import audit as audit_service

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


def _headers(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}", "Idempotency-Key": str(uuid.uuid4())}


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


async def _events_for(tenant_id: uuid.UUID) -> list[AuditEvent]:
    async with _owner_session_factory() as session:
        result = await session.execute(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == tenant_id)
            .order_by(AuditEvent.recorded_at.asc())
        )
        return list(result.scalars().all())


async def test_append_event_chains_onto_the_previous_event(
    tenant_with_api_key: tuple[uuid.UUID, str],
) -> None:
    tenant_id, _ = tenant_with_api_key
    now = SystemClock().now()

    first = await audit_service.append_event(
        tenant_id,
        entity_type="application",
        entity_id=uuid.uuid4(),
        event_type="APPLICATION_RECEIVED",
        actor_type="api_key",
        actor_id=str(uuid.uuid4()),
        payload={"external_ref": "LOS-1"},
        occurred_at=now,
    )
    second = await audit_service.append_event(
        tenant_id,
        entity_type="application",
        entity_id=uuid.uuid4(),
        event_type="APPLICATION_VALIDATED",
        actor_type="api_key",
        actor_id=str(uuid.uuid4()),
        payload={"external_ref": "LOS-1"},
        occurred_at=now,
    )

    assert first.prev_hash is None
    assert second.prev_hash == first.event_hash

    result = await audit_service.verify_chain(tenant_id)
    assert result.ok
    assert result.first_broken_event_id is None


async def test_chain_verification_over_100_events(
    tenant_with_api_key: tuple[uuid.UUID, str],
) -> None:
    tenant_id, _ = tenant_with_api_key
    now = SystemClock().now()

    for i in range(100):
        await audit_service.append_event(
            tenant_id,
            entity_type="application",
            entity_id=uuid.uuid4(),
            event_type="APPLICATION_RECEIVED",
            actor_type="api_key",
            actor_id=str(uuid.uuid4()),
            payload={"n": i},
            occurred_at=now,
        )

    events = await _events_for(tenant_id)
    assert len(events) == 100

    result = await audit_service.verify_chain(tenant_id)
    assert result.ok
    assert result.first_broken_event_id is None


async def test_tampering_is_detected_and_names_the_first_broken_link(
    tenant_with_api_key: tuple[uuid.UUID, str],
) -> None:
    """PROVE IT: tamper with one stored event's payload; verification
    detects it and names the first broken link."""
    tenant_id, _ = tenant_with_api_key
    now = SystemClock().now()

    await audit_service.append_event(
        tenant_id,
        entity_type="application",
        entity_id=uuid.uuid4(),
        event_type="APPLICATION_RECEIVED",
        actor_type="api_key",
        actor_id=str(uuid.uuid4()),
        payload={"external_ref": "LOS-1"},
        occurred_at=now,
    )
    target = await audit_service.append_event(
        tenant_id,
        entity_type="application",
        entity_id=uuid.uuid4(),
        event_type="APPLICATION_VALIDATED",
        actor_type="api_key",
        actor_id=str(uuid.uuid4()),
        payload={"external_ref": "LOS-1"},
        occurred_at=now,
    )
    await audit_service.append_event(
        tenant_id,
        entity_type="application",
        entity_id=uuid.uuid4(),
        event_type="APPLICATION_RECEIVED",
        actor_type="api_key",
        actor_id=str(uuid.uuid4()),
        payload={"external_ref": "LOS-2"},
        occurred_at=now,
    )

    # Only an owner-role connection can do this — the app role has no
    # UPDATE grant on audit_events (append-only enforced by the database,
    # not just by omission in application code). Tampering this way is
    # exactly the class of event integrity verification exists to catch.
    async with _owner_session_factory() as session, session.begin():
        await session.execute(
            update(AuditEvent)
            .where(AuditEvent.id == target.id)
            .values(payload_json={"external_ref": "TAMPERED"})
        )

    result = await audit_service.verify_chain(tenant_id)
    assert result.ok is False
    assert result.first_broken_event_id == target.id


async def test_app_role_cannot_update_audit_events(
    tenant_with_api_key: tuple[uuid.UUID, str],
) -> None:
    tenant_id, _ = tenant_with_api_key
    event = await audit_service.append_event(
        tenant_id,
        entity_type="application",
        entity_id=uuid.uuid4(),
        event_type="APPLICATION_RECEIVED",
        actor_type="api_key",
        actor_id=str(uuid.uuid4()),
        payload={"external_ref": "LOS-1"},
        occurred_at=SystemClock().now(),
    )

    with pytest.raises(DBAPIError):
        async with async_session_factory() as session, session.begin():
            await set_tenant_context(session, str(tenant_id))
            await session.execute(
                update(AuditEvent).where(AuditEvent.id == event.id).values(payload_json={})
            )


async def test_payload_excludes_raw_pan_and_gstin(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    tenant_id, raw_key = tenant_with_api_key
    response = await client.post("/v1/applications", json=_payload(), headers=_headers(raw_key))
    assert response.status_code == 201

    events = await _events_for(tenant_id)
    for event in events:
        blob = str(event.payload_json)
        assert VALID_PAN not in blob
        assert VALID_GSTIN not in blob


async def test_application_create_emits_received_and_validated_events(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    tenant_id, raw_key = tenant_with_api_key
    response = await client.post("/v1/applications", json=_payload(), headers=_headers(raw_key))
    application_id = response.json()["id"]

    events = await _events_for(tenant_id)
    event_types = [e.event_type for e in events]

    assert "TENANT_CONTEXT_SET" in event_types
    assert "APPLICATION_RECEIVED" in event_types
    assert "APPLICATION_VALIDATED" in event_types
    validated = [e for e in events if e.event_type == "APPLICATION_VALIDATED"]
    assert all(str(e.entity_id) == application_id for e in validated)

    result = await audit_service.verify_chain(tenant_id)
    assert result.ok


async def test_duplicate_external_ref_emits_rejected_intake_event(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    tenant_id, raw_key = tenant_with_api_key
    payload = _payload()
    first = await client.post("/v1/applications", json=payload, headers=_headers(raw_key))
    assert first.status_code == 201

    second = await client.post("/v1/applications", json=payload, headers=_headers(raw_key))
    assert second.status_code == 409

    events = await _events_for(tenant_id)
    assert "APPLICATION_REJECTED_INTAKE" in [e.event_type for e in events]


async def test_idempotent_replay_emits_audit_event(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    tenant_id, raw_key = tenant_with_api_key
    key = str(uuid.uuid4())
    payload = _payload()
    headers = {"Authorization": f"Bearer {raw_key}", "Idempotency-Key": key}

    first = await client.post("/v1/applications", json=payload, headers=headers)
    assert first.status_code == 201
    second = await client.post("/v1/applications", json=payload, headers=headers)
    assert second.status_code == 201

    events = await _events_for(tenant_id)
    assert "IDEMPOTENT_REPLAY" in [e.event_type for e in events]


async def test_revoked_api_key_emits_auth_failed_event(
    client: AsyncClient, tenant_with_revoked_api_key: tuple[uuid.UUID, str]
) -> None:
    tenant_id, raw_key = tenant_with_revoked_api_key
    response = await client.post("/v1/applications", json=_payload(), headers=_headers(raw_key))
    assert response.status_code == 401

    events = await _events_for(tenant_id)
    assert [e.event_type for e in events] == ["AUTH_FAILED"]
