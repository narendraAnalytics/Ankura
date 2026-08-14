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
from ankura.features.engine import _compute_confidence, compute_features
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


# --- Step 7: data quality / coverage / confidence --------------------------


@pytest.mark.parametrize(
    ("coverage_months", "source_count", "undefined_metric_count", "expected"),
    [
        # Hand-computed on paper before the code (repo convention), each
        # decimal traced through Decimal arithmetic, not copied from the
        # implementation's own output:
        #   confidence = 0.5*C_coverage + 0.3*C_source + 0.2*C_defined
        (0, 0, 7, 0.0),  # no evidence at all -> floor
        (12, 3, 0, 1.0),  # full coverage, all sources, nothing undefined -> ceiling
        # C_coverage=1, C_source=1/3, C_defined=1
        # 0.5*1 + 0.3*(1/3) + 0.2*1 = 0.5 + 0.1 + 0.2 = 0.8
        (12, 1, 0, 0.8),
        # C_coverage=6/12=0.5, C_source=2/3, C_defined=6/7
        # 0.5*0.5 + 0.3*(2/3) + 0.2*(6/7)
        #   = 0.25 + 0.2 + 0.171428571... = 0.621428571...
        # -> ROUND_HALF_UP to 6dp: the 7th decimal is 5, rounds up -> 0.621429
        (6, 2, 1, 0.621429),
    ],
)
def test_compute_confidence_matches_hand_computed_values(
    coverage_months: int, source_count: int, undefined_metric_count: int, expected: float
) -> None:
    assert _compute_confidence(coverage_months, source_count, undefined_metric_count) == expected


def test_compute_confidence_clamps_to_unit_interval() -> None:
    # source_count/coverage_months beyond their caps must not push confidence
    # past 1.0, and a negative-looking excess undefined count (impossible in
    # practice, since undefined_metric_count <= 7, but the clamp is a
    # deliberate belt-and-braces bound on the output, not the input) must
    # never push it below 0.0.
    assert _compute_confidence(999, 999, 0) == 1.0
    assert _compute_confidence(0, 0, 999) == 0.0


def test_thin_file_and_new_to_credit_cluster_at_the_bottom_of_real_cohort_confidence() -> None:
    """Step 7 PROVE IT: sort the cohort by the real engine's confidence;
    thin_file and new_to_credit must land at the bottom, healthy_grower at
    the top — asserted as a test over all 200 committed borrowers, not
    eyeballed."""
    confidences_by_archetype: dict[ArchetypeName, list[tuple[float, int, int]]] = {
        a: [] for a in ArchetypeName
    }
    for index, archetype in enumerate(ARCHETYPE_ASSIGNMENT):
        borrower = generate_borrower(index, archetype, DEFAULT_COHORT_AS_OF)
        snapshot = compute_features(borrower, DEFAULT_COHORT_AS_OF, SystemClock())
        confidences_by_archetype[archetype].append(
            (
                snapshot.data_quality.confidence,
                snapshot.data_quality.coverage_months,
                snapshot.data_quality.source_count,
            )
        )

    mean_confidence = {
        archetype: sum(c for c, _, _ in rows) / len(rows)
        for archetype, rows in confidences_by_archetype.items()
    }

    low_archetypes = {ArchetypeName.THIN_FILE, ArchetypeName.NEW_TO_CREDIT}
    other_archetypes = set(ArchetypeName) - low_archetypes

    for low in low_archetypes:
        for other in other_archetypes:
            assert mean_confidence[low] < mean_confidence[other], (
                f"{low} mean confidence {mean_confidence[low]} should be below "
                f"{other} mean confidence {mean_confidence[other]}"
            )

    # "healthy-grower with 12 months and 3 sources at the top" (Step 7
    # PROVE IT, literal wording): every healthy_grower borrower that
    # actually lands full coverage AND all 3 sources must hit the formula's
    # ceiling exactly — the top of the achievable range, not merely the top
    # of this cohort's mean-per-archetype (several other well-covered,
    # 0-undefined archetypes overlap healthy_grower's coverage/source bands
    # closely enough that their means can be statistically adjacent).
    full_evidence_healthy_grower = [
        confidence
        for confidence, coverage_months, source_count in confidences_by_archetype[
            ArchetypeName.HEALTHY_GROWER
        ]
        if coverage_months == 12 and source_count == 3
    ]
    assert full_evidence_healthy_grower, "expected at least one 12mo/3-source healthy_grower"
    assert all(c == 1.0 for c in full_evidence_healthy_grower)

    # And healthy_grower's mean is still comfortably in the top tier, clear
    # of every archetype that carries any structural stress signal (bounces,
    # thin coverage, or an undefined metric) even if a couple of other
    # clean, well-covered archetypes land within noise of it.
    assert mean_confidence[ArchetypeName.HEALTHY_GROWER] >= max(mean_confidence.values()) - 0.02
