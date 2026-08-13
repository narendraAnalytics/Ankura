"""GET /v1/tenants/me — auth smoke test. Implemented in Phase 1 Step 8."""

from __future__ import annotations

import uuid

from httpx import AsyncClient


async def test_me_returns_resolved_tenant(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    tenant_id, raw_key = tenant_with_api_key
    response = await client.get("/v1/tenants/me", headers={"Authorization": f"Bearer {raw_key}"})
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(tenant_id)
    assert body["status"] == "ACTIVE"


async def test_me_without_auth_header_returns_401(client: AsyncClient) -> None:
    response = await client.get("/v1/tenants/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_MISSING"


async def test_me_with_wrong_key_returns_401(client: AsyncClient) -> None:
    response = await client.get(
        "/v1/tenants/me", headers={"Authorization": "Bearer not-a-real-key"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_INVALID"
