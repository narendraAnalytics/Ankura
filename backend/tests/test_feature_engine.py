"""The feature engine. Implemented in Phase 2 Step 6.

Covers the Step 6 PROVE IT (feed one cohort member through twice; the two
FeatureSnapshots are byte-identical including input_hash, differ only in
computed_at), the windowing/clock-discipline rules, and that all 200
committed cohort borrowers process without error and land inside their own
archetype's expected_features when run through this real engine — not the
hand-rolled aggregate recomputation test_generator.py used before this
engine existed.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ankura.clock import FrozenClock, SystemClock
from ankura.cohort.archetypes import ARCHETYPES, ArchetypeName
from ankura.cohort.generator import ARCHETYPE_ASSIGNMENT, DEFAULT_COHORT_AS_OF, generate_borrower
from ankura.features.engine import compute_features
from ankura.features.metrics import FEATURE_ENGINE_VERSION

_METRIC_FIELDS = (
    "dscr",
    "obligation_ratio",
    "bounce_ratio",
    "bank_gst_gap",
    "cash_deposit_ratio",
    "customer_concentration",
    "supplier_concentration",
)


def test_same_input_twice_is_byte_identical_except_computed_at() -> None:
    """Step 6 PROVE IT. Uses two FrozenClocks at different instants rather
    than two real SystemClock() calls — real wall-clock resolution can
    occasionally return the same timestamp for two calls microseconds
    apart, which would make this assertion flaky for a reason that has
    nothing to do with what it's actually proving (that computed_at is the
    ONLY field the clock is allowed to influence)."""
    borrower = generate_borrower(0, ArchetypeName.HEALTHY_GROWER, DEFAULT_COHORT_AS_OF)
    first = compute_features(
        borrower, DEFAULT_COHORT_AS_OF, FrozenClock(datetime(2026, 8, 14, tzinfo=UTC))
    )
    second = compute_features(
        borrower, DEFAULT_COHORT_AS_OF, FrozenClock(datetime(2026, 8, 15, tzinfo=UTC))
    )

    first_dump = first.model_dump()
    second_dump = second.model_dump()
    differing_fields = {k for k in first_dump if first_dump[k] != second_dump[k]}

    assert differing_fields == {"computed_at"}
    assert first.input_hash == second.input_hash


def test_computed_at_comes_from_clock_not_wall_clock() -> None:
    borrower = generate_borrower(0, ArchetypeName.HEALTHY_GROWER, DEFAULT_COHORT_AS_OF)
    frozen_at = datetime(2030, 1, 1, tzinfo=UTC)
    snapshot = compute_features(borrower, DEFAULT_COHORT_AS_OF, FrozenClock(frozen_at))
    assert snapshot.computed_at == frozen_at
    assert snapshot.as_of == DEFAULT_COHORT_AS_OF


def test_feature_engine_version_matches_metrics_module() -> None:
    borrower = generate_borrower(0, ArchetypeName.HEALTHY_GROWER, DEFAULT_COHORT_AS_OF)
    snapshot = compute_features(borrower, DEFAULT_COHORT_AS_OF, SystemClock())
    assert snapshot.feature_engine_version == FEATURE_ENGINE_VERSION


def test_input_hash_changes_when_as_of_changes() -> None:
    """as_of is part of CanonicalFinancialData itself, so a different as_of
    on an otherwise-identical borrower must hash differently — input_hash
    is a hash of the INPUT, not just the transaction list."""
    borrower_a = generate_borrower(0, ArchetypeName.HEALTHY_GROWER, DEFAULT_COHORT_AS_OF)
    borrower_b = borrower_a.model_copy(
        update={"as_of": datetime(2026, 9, 13, tzinfo=UTC)}, deep=True
    )
    snap_a = compute_features(borrower_a, DEFAULT_COHORT_AS_OF, SystemClock())
    snap_b = compute_features(borrower_b, DEFAULT_COHORT_AS_OF, SystemClock())
    assert snap_a.input_hash != snap_b.input_hash


def test_no_bank_data_in_window_yields_undefined_metrics_not_zero() -> None:
    """A borrower with zero transactions in the trailing window must come
    back with undefined (None) ratios, never a fabricated 0.0 — the same
    discipline features/metrics.py enforces at the formula level must
    survive all the way through the engine."""
    borrower = generate_borrower(0, ArchetypeName.HEALTHY_GROWER, DEFAULT_COHORT_AS_OF)
    far_future_as_of = datetime(2040, 1, 1, tzinfo=UTC)  # 12mo window has no data at all
    snapshot = compute_features(borrower, far_future_as_of, SystemClock())
    assert snapshot.data_quality.coverage_months == 0
    for field in _METRIC_FIELDS:
        assert getattr(snapshot, field) is None, field


@pytest.mark.parametrize("archetype", list(ArchetypeName))
def test_one_borrower_per_archetype_matches_its_expected_signature_via_the_real_engine(
    archetype: ArchetypeName,
) -> None:
    borrower_index = ARCHETYPE_ASSIGNMENT.index(archetype)
    _assert_snapshot_matches_signature(borrower_index, archetype)


def test_full_cohort_matches_expected_signatures_via_the_real_engine() -> None:
    failures: list[tuple[int, ArchetypeName, str, float | None]] = []
    for index, archetype in enumerate(ARCHETYPE_ASSIGNMENT):
        failures.extend(_signature_failures(index, archetype))
    assert not failures, failures[:10]


def _assert_snapshot_matches_signature(borrower_index: int, archetype: ArchetypeName) -> None:
    failures = _signature_failures(borrower_index, archetype)
    assert not failures, failures


def _signature_failures(
    borrower_index: int, archetype: ArchetypeName
) -> list[tuple[int, ArchetypeName, str, float | None]]:
    borrower = generate_borrower(borrower_index, archetype, DEFAULT_COHORT_AS_OF)
    snapshot = compute_features(borrower, DEFAULT_COHORT_AS_OF, SystemClock())
    spec = ARCHETYPES[archetype]
    failures: list[tuple[int, ArchetypeName, str, float | None]] = []
    for field in _METRIC_FIELDS:
        value = getattr(snapshot, field)
        expectation = spec.expected_features[field]
        if not expectation.matches(value):
            failures.append((borrower_index, archetype, field, value))
    return failures
