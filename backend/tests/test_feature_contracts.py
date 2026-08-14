"""FeatureSnapshot contract shapes. Implemented in Phase 2 Step 2.

Shapes only — no engine logic to test yet (that's Step 6). Confirms the
contract is constructible, every §14.2 metric field is representable as
undefined (None, never a silently-coerced 0.0), and extra fields are
rejected same as every other contract in this repo.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ankura.contracts.features import FeatureSnapshot, ProvenanceEntry
from ankura.contracts.financial import DataQuality


def _snapshot(**overrides: object) -> FeatureSnapshot:
    fields: dict[str, object] = {
        "application_id": uuid4(),
        "as_of": datetime(2026, 8, 13, tzinfo=UTC),
        "computed_at": datetime(2026, 8, 14, tzinfo=UTC),
        "feature_engine_version": "1.0.0",
        "input_hash": "a" * 64,
        "dscr": 1.333333,
        "obligation_ratio": 0.25,
        "bounce_ratio": 0.075,
        "bank_gst_gap": 0.384615,
        "cash_deposit_ratio": 0.15,
        "customer_concentration": 0.4,
        "supplier_concentration": 0.4,
        "data_quality": DataQuality(coverage_months=12, source_count=2, confidence=0.9),
        "provenance": [
            ProvenanceEntry(
                source="bank",
                source_as_of=datetime(2026, 8, 13, tzinfo=UTC),
                months_used=["2026-01", "2026-02"],
            )
        ],
    }
    fields.update(overrides)
    return FeatureSnapshot(**fields)  # type: ignore[arg-type]


def test_feature_snapshot_constructs_with_full_shape() -> None:
    snapshot = _snapshot()
    assert snapshot.dscr == 1.333333
    assert snapshot.provenance[0].source == "bank"


def test_feature_snapshot_allows_every_metric_undefined() -> None:
    snapshot = _snapshot(
        dscr=None,
        obligation_ratio=None,
        bounce_ratio=None,
        bank_gst_gap=None,
        cash_deposit_ratio=None,
        customer_concentration=None,
        supplier_concentration=None,
    )
    assert snapshot.dscr is None
    assert snapshot.supplier_concentration is None


def test_feature_snapshot_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _snapshot(unexpected_field="nope")


def test_input_hash_must_be_64_hex_chars() -> None:
    with pytest.raises(ValidationError):
        _snapshot(input_hash="too-short")


def test_provenance_entry_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ProvenanceEntry(
            source="bank",
            source_as_of=datetime(2026, 8, 13, tzinfo=UTC),
            unexpected_field="nope",  # type: ignore[call-arg]
        )
