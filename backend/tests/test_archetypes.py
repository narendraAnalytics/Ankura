"""Archetype spec self-consistency. Implemented in Phase 2 Step 3.

`generator.py`/`engine.py` don't exist yet (Steps 4/6) so there is no
FeatureSnapshot to regress against — that's Step 11's job. What CAN be
tested now, standalone, is that `archetypes.py` is internally faithful to
its own stated rules: the mix sums to 200 (Step 0 D1/D2), every fraud
archetype is structurally distinguishable from every non-fraud one on
`bank_gst_gap` (Step 3's "structurally real, not cosmetic" requirement),
`declining_business` actually encodes D4's own worked example, and
`FeatureExpectation`/`Range` reject the malformed inputs they document.
"""

from __future__ import annotations

import pytest

from ankura.cohort.archetypes import (
    ARCHETYPES,
    COHORT_SIZE,
    FRAUD_ARCHETYPES,
    ArchetypeName,
    FeatureExpectation,
    Range,
)


def test_cohort_size_is_200() -> None:
    assert COHORT_SIZE == 200


def test_archetype_mix_matches_step_0_d2() -> None:
    expected_counts = {
        ArchetypeName.HEALTHY_GROWER: 50,
        ArchetypeName.SEASONAL_TRADER: 30,
        ArchetypeName.DECLINING_BUSINESS: 25,
        ArchetypeName.OVER_LEVERAGED: 25,
        ArchetypeName.RECOVERING_FROM_STRESS: 20,
        ArchetypeName.THIN_FILE: 20,
        ArchetypeName.NEW_TO_CREDIT: 15,
        ArchetypeName.GST_BANK_MISMATCH: 10,
        ArchetypeName.CIRCULAR_TRANSACTIONS: 5,
    }
    assert {name: spec.count for name, spec in ARCHETYPES.items()} == expected_counts


def test_every_archetype_declares_every_metric() -> None:
    metric_fields = {
        "dscr",
        "obligation_ratio",
        "bounce_ratio",
        "bank_gst_gap",
        "cash_deposit_ratio",
        "customer_concentration",
        "supplier_concentration",
    }
    for name, spec in ARCHETYPES.items():
        assert set(spec.expected_features) == metric_fields, name


def test_declining_business_encodes_step_0_d4_worked_example() -> None:
    spec = ARCHETYPES[ArchetypeName.DECLINING_BUSINESS]
    dscr_expectation = spec.expected_features["dscr"]
    assert dscr_expectation.max is not None
    assert dscr_expectation.max <= 1.2
    assert spec.params.inflow_trend.value == "DECLINING"


def test_new_to_credit_obligation_ratio_is_a_real_zero_not_undefined() -> None:
    spec = ARCHETYPES[ArchetypeName.NEW_TO_CREDIT]
    expectation = spec.expected_features["obligation_ratio"]
    assert expectation.matches(0.0) is True
    assert expectation.matches(None) is False  # must be a MEASURED zero
    assert expectation.matches(0.1) is False


def test_thin_file_requires_bank_gst_gap_undefined() -> None:
    spec = ARCHETYPES[ArchetypeName.THIN_FILE]
    expectation = spec.expected_features["bank_gst_gap"]
    assert expectation.matches(None) is True
    assert expectation.matches(0.05) is False  # a defined value would be a bug


@pytest.mark.parametrize("name", list(FRAUD_ARCHETYPES))
def test_fraud_archetypes_require_materially_elevated_bank_gst_gap(
    name: ArchetypeName,
) -> None:
    spec = ARCHETYPES[name]
    expectation = spec.expected_features["bank_gst_gap"]
    assert expectation.min is not None
    assert expectation.min >= 0.25


@pytest.mark.parametrize("name", [n for n in ArchetypeName if n not in FRAUD_ARCHETYPES])
def test_non_fraud_archetypes_keep_bank_gst_gap_low(name: ArchetypeName) -> None:
    spec = ARCHETYPES[name]
    expectation = spec.expected_features["bank_gst_gap"]
    if expectation.must_be_undefined:
        # thin_file: no GST returns filed yet -> gap is undefined, not
        # merely small. Still cannot be confused with the fraud archetypes'
        # materially-elevated, DEFINED gap.
        return
    # A non-fraud archetype's gap ceiling must stay well under the fraud
    # archetypes' floor, or the false-positive-honesty check (Step 8) is
    # meaningless.
    assert expectation.max is not None
    assert expectation.max <= 0.15


def test_circular_transactions_is_the_only_ring_expecting_archetype() -> None:
    ring_expecting = {name for name, spec in ARCHETYPES.items() if spec.expect_circular_ring}
    assert ring_expecting == {ArchetypeName.CIRCULAR_TRANSACTIONS}


def test_over_leveraged_dscr_below_one_and_high_obligation() -> None:
    spec = ARCHETYPES[ArchetypeName.OVER_LEVERAGED]
    assert spec.expected_features["dscr"].max is not None
    assert spec.expected_features["dscr"].max <= 1.0
    assert spec.expected_features["obligation_ratio"].min is not None
    assert spec.expected_features["obligation_ratio"].min >= 0.45


def test_range_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError, match="min .* > max"):
        Range(min=1.0, max=0.5)


def test_feature_expectation_rejects_must_be_undefined_with_bounds() -> None:
    with pytest.raises(ValueError, match="exclusive"):
        FeatureExpectation(min=0.0, must_be_undefined=True)


def test_unknown_metric_field_rejected_at_import_time() -> None:
    from ankura.cohort.archetypes import _expectations

    with pytest.raises(ValueError, match="Unknown metric field"):
        _expectations(not_a_real_metric=FeatureExpectation())
