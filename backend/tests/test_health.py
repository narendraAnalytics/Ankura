"""Health/readiness endpoint tests. Implemented in Phase 1 Step 8."""

from __future__ import annotations

from httpx import AsyncClient


async def test_healthz_returns_ok_without_db(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_returns_ready_with_live_db(client: AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_openapi_docs_render(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    body = response.json()
    assert "/v1/applications" in body["paths"]
