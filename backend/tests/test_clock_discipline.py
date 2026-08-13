"""Clock discipline test. Implemented in Phase 1 Step 10.

Belt-and-suspenders with the ruff TID251 banned-api rule (pyproject.toml):
greps the source tree and fails on any banned time call (datetime.now,
datetime.utcnow, date.today, time.time) outside clock.py, then proves the
Clock dependency actually reaches request handling by overriding it with
FrozenClock and checking the stamped as_of is deterministic. See
phase1.txt Step 10 PROVE IT.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient

from ankura.clock import FrozenClock, get_clock
from ankura.main import app

_SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "ankura"
_EXEMPT_FILE = _SRC_ROOT / "clock.py"

_BANNED_PATTERNS = [
    re.compile(r"\bdatetime\.now\("),
    re.compile(r"\.utcnow\("),
    re.compile(r"\bdate\.today\("),
    re.compile(r"\btime\.time\("),
]

VALID_GSTIN = "27AAPFU0939F1ZV"
VALID_PAN = "AAPFU0939F"


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


def test_no_banned_time_calls_outside_clock_module() -> None:
    violations: list[str] = []
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        if path == _EXEMPT_FILE:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for pattern in _BANNED_PATTERNS:
                if pattern.search(line):
                    violations.append(
                        f"{path.relative_to(_SRC_ROOT.parent.parent)}:{lineno}: {line.strip()}"
                    )
    assert not violations, "banned time call(s) found outside clock.py:\n" + "\n".join(violations)


async def test_frozen_clock_produces_deterministic_as_of(
    tenant_with_api_key: tuple[uuid.UUID, str],
) -> None:
    """PROVE IT: freeze the clock, create an application twice (without
    supplying as_of) and the stamped as_of is identical both times."""
    _, raw_key = tenant_with_api_key
    frozen = FrozenClock(datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC))
    app.dependency_overrides[get_clock] = lambda: frozen
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/v1/applications", json=_payload(), headers=_headers(raw_key)
            )
            second = await client.post(
                "/v1/applications", json=_payload(), headers=_headers(raw_key)
            )
        assert first.status_code == second.status_code == 201
        assert first.json()["as_of"] == second.json()["as_of"] == "2026-01-01T12:00:00Z"
    finally:
        app.dependency_overrides.pop(get_clock, None)


async def test_explicit_as_of_overrides_the_clock(
    tenant_with_api_key: tuple[uuid.UUID, str],
) -> None:
    """A caller-supplied as_of is honoured end to end, never re-derived
    from the clock deeper in the stack — even with a frozen clock active."""
    _, raw_key = tenant_with_api_key
    frozen = FrozenClock(datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC))
    app.dependency_overrides[get_clock] = lambda: frozen
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/applications",
                json=_payload(as_of="2020-06-15T00:00:00Z"),
                headers=_headers(raw_key),
            )
        assert response.status_code == 201
        assert response.json()["as_of"] == "2020-06-15T00:00:00Z"
    finally:
        app.dependency_overrides.pop(get_clock, None)
