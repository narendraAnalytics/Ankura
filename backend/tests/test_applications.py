"""Application intake API tests. Implemented in Phase 1 Step 8.

Covers create / fetch / list / duplicate-external_ref / bad-PAN /
bad-GSTIN-checksum / out-of-band-amount — see phase1.txt Step 8 PROVE IT.
"""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient

# Same known-good GSTIN pinned in tests/test_identifiers.py (Step 5) — hand-
# verified Mod-36 checksum, and its embedded PAN (positions 3-12) matches
# VALID_PAN exactly, so happy-path tests never trip the identifier-
# consistency warning by accident.
VALID_GSTIN = "27AAPFU0939F1ZV"
VALID_PAN = "AAPFU0939F"


def _headers(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}


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


async def test_create_application_succeeds(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    tenant_id, raw_key = tenant_with_api_key
    response = await client.post("/v1/applications", json=_payload(), headers=_headers(raw_key))
    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"] == str(tenant_id)
    assert body["status"] == "RECEIVED"
    assert body["borrower_pan"] == VALID_PAN
    assert body["borrower_gstin"] == VALID_GSTIN
    assert body["as_of"] is not None
    assert body["received_at"] is not None


async def test_create_application_honours_supplied_as_of(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    _, raw_key = tenant_with_api_key
    as_of = "2026-01-15T00:00:00Z"
    response = await client.post(
        "/v1/applications", json=_payload(as_of=as_of), headers=_headers(raw_key)
    )
    assert response.status_code == 201
    assert response.json()["as_of"] == "2026-01-15T00:00:00Z"


async def test_fetch_application_by_id(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    _, raw_key = tenant_with_api_key
    created = await client.post("/v1/applications", json=_payload(), headers=_headers(raw_key))
    application_id = created.json()["id"]

    response = await client.get(f"/v1/applications/{application_id}", headers=_headers(raw_key))
    assert response.status_code == 200
    assert response.json()["id"] == application_id


async def test_fetch_nonexistent_application_returns_404(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    _, raw_key = tenant_with_api_key
    response = await client.get(f"/v1/applications/{uuid.uuid4()}", headers=_headers(raw_key))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "APPLICATION_NOT_FOUND"


async def test_fetch_application_cross_tenant_returns_404(
    client: AsyncClient,
    two_tenants_with_api_keys: tuple[tuple[uuid.UUID, str], tuple[uuid.UUID, str]],
) -> None:
    (_, raw_key_a), (_, raw_key_b) = two_tenants_with_api_keys
    created = await client.post("/v1/applications", json=_payload(), headers=_headers(raw_key_a))
    application_id = created.json()["id"]

    response = await client.get(f"/v1/applications/{application_id}", headers=_headers(raw_key_b))
    assert response.status_code == 404


async def test_list_applications_returns_created_application(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    _, raw_key = tenant_with_api_key
    created = await client.post("/v1/applications", json=_payload(), headers=_headers(raw_key))
    application_id = created.json()["id"]

    response = await client.get("/v1/applications", headers=_headers(raw_key))
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert application_id in ids


async def test_list_applications_never_contains_other_tenant_rows(
    client: AsyncClient,
    two_tenants_with_api_keys: tuple[tuple[uuid.UUID, str], tuple[uuid.UUID, str]],
) -> None:
    (_, raw_key_a), (_, raw_key_b) = two_tenants_with_api_keys
    created = await client.post("/v1/applications", json=_payload(), headers=_headers(raw_key_a))
    application_id = created.json()["id"]

    response = await client.get("/v1/applications", headers=_headers(raw_key_b))
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert application_id not in ids


async def test_list_applications_filters_by_status(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    _, raw_key = tenant_with_api_key
    await client.post("/v1/applications", json=_payload(), headers=_headers(raw_key))

    response = await client.get(
        "/v1/applications", params={"status": "REJECTED_INTAKE"}, headers=_headers(raw_key)
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_list_applications_cursor_pagination_covers_all_rows_once(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    _, raw_key = tenant_with_api_key
    created_ids = set()
    for _ in range(3):
        response = await client.post("/v1/applications", json=_payload(), headers=_headers(raw_key))
        created_ids.add(response.json()["id"])

    seen_ids: set[str] = set()
    cursor: str | None = None
    for _ in range(len(created_ids)):  # bounded: one page per created row
        params = {"limit": 1}
        if cursor is not None:
            params["cursor"] = cursor
        response = await client.get("/v1/applications", params=params, headers=_headers(raw_key))
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 1
        seen_ids.add(body["items"][0]["id"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert created_ids <= seen_ids


async def test_list_applications_rejects_invalid_cursor(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    _, raw_key = tenant_with_api_key
    response = await client.get(
        "/v1/applications", params={"cursor": "not-a-real-cursor"}, headers=_headers(raw_key)
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CURSOR"


async def test_list_applications_respects_max_page_size(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    _, raw_key = tenant_with_api_key
    response = await client.get(
        "/v1/applications", params={"limit": 101}, headers=_headers(raw_key)
    )
    assert response.status_code == 422


async def test_duplicate_external_ref_returns_409_with_existing_id(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    _, raw_key = tenant_with_api_key
    payload = _payload()
    first = await client.post("/v1/applications", json=payload, headers=_headers(raw_key))
    application_id = first.json()["id"]

    second = await client.post("/v1/applications", json=payload, headers=_headers(raw_key))
    assert second.status_code == 409
    body = second.json()
    assert body["error"]["code"] == "DUPLICATE_EXTERNAL_REF"
    assert body["error"]["details"][0]["existing_application_id"] == application_id


async def test_same_pan_reuses_same_borrower_across_applications(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    """Borrower upserted by (tenant_id, pan) — two applications for the
    same PAN must not create two borrower rows (only observable indirectly
    here: both creates succeed without a uq_borrowers_tenant_pan
    violation, since the second would 500 if a plain INSERT were used)."""
    _, raw_key = tenant_with_api_key
    first = await client.post("/v1/applications", json=_payload(), headers=_headers(raw_key))
    second = await client.post("/v1/applications", json=_payload(), headers=_headers(raw_key))
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


async def test_bad_pan_returns_422(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    _, raw_key = tenant_with_api_key
    response = await client.post(
        "/v1/applications",
        json=_payload(borrower_pan="BADPAN123"),
        headers=_headers(raw_key),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_bad_gstin_checksum_returns_422(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    _, raw_key = tenant_with_api_key
    response = await client.post(
        "/v1/applications",
        # Same GSTIN as VALID_GSTIN but with the checksum char flipped
        # (V -> W) — structurally valid, checksum wrong.
        json=_payload(borrower_gstin="27AAPFU0939F1ZW"),
        headers=_headers(raw_key),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_amount_out_of_ticket_band_returns_422(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    _, raw_key = tenant_with_api_key
    response = await client.post(
        "/v1/applications",
        json=_payload(requested_amount_paise=100_00),
        headers=_headers(raw_key),
    )
    assert response.status_code == 422


async def test_tenure_out_of_band_returns_422(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str]
) -> None:
    _, raw_key = tenant_with_api_key
    response = await client.post(
        "/v1/applications", json=_payload(tenure_months=1), headers=_headers(raw_key)
    )
    assert response.status_code == 422


async def test_missing_auth_header_returns_401(client: AsyncClient) -> None:
    response = await client.post("/v1/applications", json=_payload())
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_MISSING"


async def test_invalid_api_key_returns_401(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/applications", json=_payload(), headers=_headers("not-a-real-key")
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_INVALID"


async def test_revoked_api_key_returns_401(
    client: AsyncClient, tenant_with_revoked_api_key: tuple[uuid.UUID, str]
) -> None:
    _, raw_key = tenant_with_revoked_api_key
    response = await client.post("/v1/applications", json=_payload(), headers=_headers(raw_key))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REVOKED"


async def test_identifier_consistency_mismatch_is_warned_not_rejected(
    client: AsyncClient, tenant_with_api_key: tuple[uuid.UUID, str], caplog: Any
) -> None:
    """GSTIN's embedded PAN (positions 3-12) not matching the supplied
    borrower_pan is a warning, never a rejection — phase1.txt Step 8."""
    _, raw_key = tenant_with_api_key
    mismatched_pan = "AAAAA1234A"
    with caplog.at_level("WARNING"):
        response = await client.post(
            "/v1/applications",
            json=_payload(borrower_pan=mismatched_pan),
            headers=_headers(raw_key),
        )
    assert response.status_code == 201
    assert any("identifier_consistency_warning" in record.message for record in caplog.records)
