"""Archetype definitions — the SPEC for the synthetic cohort (phase2.txt
Step 3). `generator.py` (Step 4) is the implementation; this module is
declarative and reads standalone: a reviewer who has never seen the
generator should be able to read a single `ArchetypeSpec` here and predict,
for each §14.2 metric, which way it should move for a faithful example of
that archetype (phase2.txt Step 3 PROVE IT).

Every expected signature is a RANGE or DIRECTION (`FeatureExpectation`),
never an exact value — an exact value would just re-encode the generator's
own arithmetic and prove nothing (phase2.txt Step 3). The one deliberate
exception is `new_to_credit`'s `obligation_ratio`, pinned to exactly
`[0.0, 0.0]` — that IS the claim being tested (a real, measured zero, not
an undefined metric; see `features/metrics.py`'s zero-denominator
docstrings and phase2.txt Step 0 D4).

Mix (Step 0 D2, sums to the 200-borrower cohort — Step 0 D1):
healthy_grower 50, seasonal_trader 30, declining_business 25,
over_leveraged 25, recovering_from_stress 20, thin_file 20,
new_to_credit 15, gst_bank_mismatch 10, circular_transactions 5.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ArchetypeName(StrEnum):
    HEALTHY_GROWER = "HEALTHY_GROWER"
    SEASONAL_TRADER = "SEASONAL_TRADER"
    DECLINING_BUSINESS = "DECLINING_BUSINESS"
    THIN_FILE = "THIN_FILE"
    GST_BANK_MISMATCH = "GST_BANK_MISMATCH"
    CIRCULAR_TRANSACTIONS = "CIRCULAR_TRANSACTIONS"
    OVER_LEVERAGED = "OVER_LEVERAGED"
    RECOVERING_FROM_STRESS = "RECOVERING_FROM_STRESS"
    NEW_TO_CREDIT = "NEW_TO_CREDIT"


class InflowTrend(StrEnum):
    """Direction of monthly bank inflow over the coverage window. A
    generation-time intent, not a computed §14.2 metric — the feature
    engine (Step 6) never computes a "trend" field; this only tells
    `generator.py` which way to slope the synthetic transaction stream."""

    GROWING = "GROWING"
    FLAT = "FLAT"
    DECLINING = "DECLINING"
    SEASONAL = "SEASONAL"
    RECOVERING = "RECOVERING"


class Volatility(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class GstBankRelationship(StrEnum):
    ALIGNED = "ALIGNED"
    MISMATCHED = "MISMATCHED"


@dataclass(frozen=True)
class Range:
    """An inclusive [min, max] band — used for BOTH generation-parameter
    targets (what the generator aims for) and expected-signature checks
    (what the regression suite, Step 11, asserts against the result)."""

    min: float
    max: float

    def __post_init__(self) -> None:
        if self.min > self.max:
            raise ValueError(f"Range min {self.min} > max {self.max}")

    def contains(self, value: float) -> bool:
        return self.min <= value <= self.max


@dataclass(frozen=True)
class GenerationParams:
    """What `generator.py` (Step 4) aims to produce. These are TARGETS the
    generator solves for — e.g. "emi_load 0.45-0.80" means the generator
    picks an EMI that lands obligation_ratio in that band — never hand-typed
    output values (§14.2 / phase2.txt Step 4)."""

    inflow_trend: InflowTrend
    volatility: Volatility
    bounce_rate: Range
    """Target share of presented instruments that bounce."""
    emi_load: Range
    """Target obligation_ratio band the generator solves the EMI for."""
    gst_bank_relationship: GstBankRelationship
    coverage_months: Range
    """Months of usable bank-statement history to generate."""
    source_count: Range
    """How many independent sources (bank / GST / bureau) to attach."""
    has_circular_transactions: bool = False
    """True only for the fraud archetype whose defining feature IS a
    circular-transaction ring (Step 8)."""


@dataclass(frozen=True)
class FeatureExpectation:
    """A range/direction check against one FeatureSnapshot field. `matches`
    is the single implementation Step 11's regression suite calls — do not
    re-implement this comparison logic a second time in the test file."""

    min: float | None = None
    max: float | None = None
    allow_undefined: bool = False
    """True if `None` (undefined, Step 1) is an acceptable outcome for this
    metric on this archetype, alongside an in-range defined value."""
    must_be_undefined: bool = False
    """True if this metric MUST come back `None` for this archetype to be
    faithful — e.g. thin_file's unfiled GST turnover."""

    def __post_init__(self) -> None:
        if self.must_be_undefined and (self.min is not None or self.max is not None):
            raise ValueError("must_be_undefined is exclusive with min/max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"FeatureExpectation min {self.min} > max {self.max}")

    def matches(self, value: float | None) -> bool:
        if value is None:
            return self.allow_undefined or self.must_be_undefined
        if self.must_be_undefined:
            return False
        if self.min is not None and value < self.min:
            return False
        return not (self.max is not None and value > self.max)


@dataclass(frozen=True)
class ArchetypeSpec:
    name: ArchetypeName
    count: int
    story: str
    """The economic story, in plain English — what kind of MSME this is and
    why its numbers should look the way `expected_features` says."""
    params: GenerationParams
    expected_features: dict[str, FeatureExpectation]
    """Keyed by the exact FeatureSnapshot field name (contracts/features.py):
    dscr, obligation_ratio, bounce_ratio, bank_gst_gap, cash_deposit_ratio,
    customer_concentration, supplier_concentration."""
    expected_coverage_months: Range
    expected_confidence: Range
    expect_circular_ring: bool = False
    """True only for the archetype the Step 8 ring detector must trip on;
    every OTHER archetype must NOT trip it (false-positive honesty, Step 8)."""


_METRIC_FIELDS = (
    "dscr",
    "obligation_ratio",
    "bounce_ratio",
    "bank_gst_gap",
    "cash_deposit_ratio",
    "customer_concentration",
    "supplier_concentration",
)


def _expectations(**kwargs: FeatureExpectation) -> dict[str, FeatureExpectation]:
    """Guard against a typo'd metric key silently being ignored by the
    regression suite (Step 11) — fail at import time instead."""
    unknown = set(kwargs) - set(_METRIC_FIELDS)
    if unknown:
        raise ValueError(f"Unknown metric field(s) in expected_features: {sorted(unknown)}")
    return kwargs


ARCHETYPES: dict[ArchetypeName, ArchetypeSpec] = {
    ArchetypeName.HEALTHY_GROWER: ArchetypeSpec(
        name=ArchetypeName.HEALTHY_GROWER,
        count=50,
        story=(
            "An established MSME with steadily growing revenue, consistent "
            "formal banking, low existing debt, and clean GST filings that "
            "track bank turnover closely. The ordinary, unremarkable "
            "majority of a realistic loan book."
        ),
        params=GenerationParams(
            inflow_trend=InflowTrend.GROWING,
            volatility=Volatility.LOW,
            bounce_rate=Range(0.0, 0.02),
            emi_load=Range(0.10, 0.25),
            gst_bank_relationship=GstBankRelationship.ALIGNED,
            coverage_months=Range(10, 12),
            source_count=Range(2, 3),
        ),
        expected_features=_expectations(
            dscr=FeatureExpectation(min=1.5, max=3.0),
            obligation_ratio=FeatureExpectation(min=0.0, max=0.30),
            bounce_ratio=FeatureExpectation(min=0.0, max=0.03),
            bank_gst_gap=FeatureExpectation(min=0.0, max=0.10),
            cash_deposit_ratio=FeatureExpectation(min=0.0, max=0.15),
            customer_concentration=FeatureExpectation(min=0.0, max=0.35),
            supplier_concentration=FeatureExpectation(min=0.0, max=0.35),
        ),
        expected_coverage_months=Range(10, 12),
        expected_confidence=Range(0.85, 1.0),
    ),
    ArchetypeName.SEASONAL_TRADER: ArchetypeSpec(
        name=ArchetypeName.SEASONAL_TRADER,
        count=30,
        story=(
            "A trading/retail business with genuinely seasonal cash flow: an "
            "Indian-FY festive peak (Sep-Nov) and a lean trough (Feb-Apr) — "
            "Step 0 D7. Cash-heavy and customer-diversified, viable across "
            "the full year even though any single month looks volatile."
        ),
        params=GenerationParams(
            inflow_trend=InflowTrend.SEASONAL,
            volatility=Volatility.HIGH,
            bounce_rate=Range(0.02, 0.05),
            emi_load=Range(0.15, 0.30),
            gst_bank_relationship=GstBankRelationship.ALIGNED,
            coverage_months=Range(9, 12),
            source_count=Range(2, 3),
        ),
        expected_features=_expectations(
            dscr=FeatureExpectation(min=1.1, max=2.2),
            obligation_ratio=FeatureExpectation(min=0.0, max=0.35),
            bounce_ratio=FeatureExpectation(min=0.0, max=0.08),
            bank_gst_gap=FeatureExpectation(min=0.0, max=0.12),
            cash_deposit_ratio=FeatureExpectation(min=0.15, max=0.45),
            customer_concentration=FeatureExpectation(min=0.0, max=0.45),
            supplier_concentration=FeatureExpectation(min=0.0, max=0.45),
        ),
        expected_coverage_months=Range(9, 12),
        expected_confidence=Range(0.75, 0.95),
    ),
    ArchetypeName.DECLINING_BUSINESS: ArchetypeSpec(
        name=ArchetypeName.DECLINING_BUSINESS,
        count=25,
        story=(
            "Revenue genuinely shrinking month over month, bounces creeping "
            "up as obligations increasingly crowd out a thinning surplus. "
            "Still a real, filing, operating business — not a fraud "
            "archetype — just one under real financial stress."
        ),
        params=GenerationParams(
            inflow_trend=InflowTrend.DECLINING,
            volatility=Volatility.MEDIUM,
            bounce_rate=Range(0.05, 0.15),
            emi_load=Range(0.30, 0.50),
            gst_bank_relationship=GstBankRelationship.ALIGNED,
            coverage_months=Range(9, 12),
            source_count=Range(2, 3),
        ),
        expected_features=_expectations(
            # Step 0 D4: "negative inflow trend AND dscr below 1.2".
            dscr=FeatureExpectation(min=0.6, max=1.2),
            obligation_ratio=FeatureExpectation(min=0.30, max=0.55),
            bounce_ratio=FeatureExpectation(min=0.05, max=0.20),
            bank_gst_gap=FeatureExpectation(min=0.0, max=0.15),
            cash_deposit_ratio=FeatureExpectation(min=0.0, max=0.30),
            customer_concentration=FeatureExpectation(min=0.0, max=0.50),
            supplier_concentration=FeatureExpectation(min=0.0, max=0.50),
        ),
        expected_coverage_months=Range(9, 12),
        expected_confidence=Range(0.70, 0.90),
    ),
    ArchetypeName.THIN_FILE: ArchetypeSpec(
        name=ArchetypeName.THIN_FILE,
        count=20,
        story=(
            "A genuinely young business: 1-3 months of usable bank history, "
            "no GST returns filed yet, no bureau record. Must exercise the "
            "undefined-metric paths from Step 1 — that IS half its value as "
            "test data, not a bug to smooth over."
        ),
        params=GenerationParams(
            inflow_trend=InflowTrend.FLAT,
            volatility=Volatility.MEDIUM,
            bounce_rate=Range(0.0, 0.10),
            emi_load=Range(0.0, 0.20),
            gst_bank_relationship=GstBankRelationship.ALIGNED,
            coverage_months=Range(1, 3),
            source_count=Range(1, 1),
        ),
        expected_features=_expectations(
            dscr=FeatureExpectation(min=0.5, max=3.0, allow_undefined=True),
            obligation_ratio=FeatureExpectation(min=0.0, max=0.40, allow_undefined=True),
            bounce_ratio=FeatureExpectation(min=0.0, max=0.20, allow_undefined=True),
            # No GST returns filed yet at 1-3 months old -> gst_turnover == 0.
            bank_gst_gap=FeatureExpectation(must_be_undefined=True),
            cash_deposit_ratio=FeatureExpectation(min=0.0, max=0.50, allow_undefined=True),
            customer_concentration=FeatureExpectation(min=0.0, max=1.0, allow_undefined=True),
            supplier_concentration=FeatureExpectation(min=0.0, max=1.0, allow_undefined=True),
        ),
        expected_coverage_months=Range(1, 3),
        expected_confidence=Range(0.0, 0.50),
    ),
    ArchetypeName.GST_BANK_MISMATCH: ArchetypeSpec(
        name=ArchetypeName.GST_BANK_MISMATCH,
        count=10,
        story=(
            "FRAUD ARCHETYPE. Bank credit turnover and GST-filed turnover "
            "materially diverge — the classic under-reporting-to-the-taxman "
            "(or bank-side window-dressing) pattern. The mismatch itself is "
            "the signal; other metrics look otherwise unremarkable so the "
            "gap can't be explained away by general business stress."
        ),
        params=GenerationParams(
            inflow_trend=InflowTrend.FLAT,
            volatility=Volatility.LOW,
            bounce_rate=Range(0.0, 0.05),
            emi_load=Range(0.15, 0.30),
            gst_bank_relationship=GstBankRelationship.MISMATCHED,
            coverage_months=Range(9, 12),
            source_count=Range(2, 3),
        ),
        expected_features=_expectations(
            dscr=FeatureExpectation(min=1.0, max=2.5),
            obligation_ratio=FeatureExpectation(min=0.0, max=0.35),
            bounce_ratio=FeatureExpectation(min=0.0, max=0.05),
            bank_gst_gap=FeatureExpectation(min=0.40, max=None),
            cash_deposit_ratio=FeatureExpectation(min=0.0, max=0.30),
            customer_concentration=FeatureExpectation(min=0.0, max=0.50),
            supplier_concentration=FeatureExpectation(min=0.0, max=0.50),
        ),
        expected_coverage_months=Range(9, 12),
        expected_confidence=Range(0.70, 0.95),
    ),
    ArchetypeName.CIRCULAR_TRANSACTIONS: ArchetypeSpec(
        name=ArchetypeName.CIRCULAR_TRANSACTIONS,
        count=5,
        story=(
            "FRAUD ARCHETYPE. Money moves in a ring — A pays B, B pays C, C "
            "pays A — near-equal amounts, short windows, small counterparty "
            "set. Apparent turnover and DSCR look inflated/healthy precisely "
            "BECAUSE the flow is fake, and GST filings (reflecting only the "
            "real underlying business) fall well short of that inflated "
            "bank turnover. Looking artificially healthy is the tell, not "
            "looking distressed."
        ),
        params=GenerationParams(
            inflow_trend=InflowTrend.FLAT,
            volatility=Volatility.LOW,
            bounce_rate=Range(0.0, 0.02),
            emi_load=Range(0.10, 0.25),
            gst_bank_relationship=GstBankRelationship.MISMATCHED,
            coverage_months=Range(9, 12),
            source_count=Range(2, 3),
            has_circular_transactions=True,
        ),
        expected_features=_expectations(
            dscr=FeatureExpectation(min=1.4, max=None),
            obligation_ratio=FeatureExpectation(min=0.0, max=0.30),
            bounce_ratio=FeatureExpectation(min=0.0, max=0.02),
            bank_gst_gap=FeatureExpectation(min=0.25, max=None),
            cash_deposit_ratio=FeatureExpectation(min=0.0, max=0.20),
            customer_concentration=FeatureExpectation(min=0.25, max=None),
            supplier_concentration=FeatureExpectation(min=0.25, max=None),
        ),
        expected_coverage_months=Range(9, 12),
        expected_confidence=Range(0.70, 0.95),
        expect_circular_ring=True,
    ),
    ArchetypeName.OVER_LEVERAGED: ArchetypeSpec(
        name=ArchetypeName.OVER_LEVERAGED,
        count=25,
        story=(
            "A real, operating business whose EMI outflow genuinely crowds "
            "out surplus — too much existing debt for its income, not "
            "revenue collapse. Distinct from declining_business: inflow is "
            "flat-to-healthy, the obligation load is what breaks it."
        ),
        params=GenerationParams(
            inflow_trend=InflowTrend.FLAT,
            volatility=Volatility.MEDIUM,
            bounce_rate=Range(0.05, 0.15),
            emi_load=Range(0.45, 0.80),
            gst_bank_relationship=GstBankRelationship.ALIGNED,
            coverage_months=Range(9, 12),
            source_count=Range(2, 3),
        ),
        expected_features=_expectations(
            dscr=FeatureExpectation(min=0.4, max=1.0),
            obligation_ratio=FeatureExpectation(min=0.45, max=0.85),
            bounce_ratio=FeatureExpectation(min=0.05, max=0.20),
            bank_gst_gap=FeatureExpectation(min=0.0, max=0.15),
            cash_deposit_ratio=FeatureExpectation(min=0.0, max=0.25),
            customer_concentration=FeatureExpectation(min=0.0, max=0.45),
            supplier_concentration=FeatureExpectation(min=0.0, max=0.45),
        ),
        expected_coverage_months=Range(9, 12),
        expected_confidence=Range(0.75, 0.95),
    ),
    ArchetypeName.RECOVERING_FROM_STRESS: ArchetypeSpec(
        name=ArchetypeName.RECOVERING_FROM_STRESS,
        count=20,
        story=(
            "A business that went through a stress period and is now on the "
            "mend: inflow trending back up, bounces tapering off but not yet "
            "zero, DSCR crossing back over the coverage line without being "
            "comfortably above it. The evidence of past stress is still "
            "visible, not erased."
        ),
        params=GenerationParams(
            inflow_trend=InflowTrend.RECOVERING,
            volatility=Volatility.MEDIUM,
            bounce_rate=Range(0.02, 0.08),
            emi_load=Range(0.25, 0.40),
            gst_bank_relationship=GstBankRelationship.ALIGNED,
            coverage_months=Range(9, 12),
            source_count=Range(2, 3),
        ),
        expected_features=_expectations(
            dscr=FeatureExpectation(min=1.0, max=1.4),
            obligation_ratio=FeatureExpectation(min=0.25, max=0.40),
            bounce_ratio=FeatureExpectation(min=0.0, max=0.08),
            bank_gst_gap=FeatureExpectation(min=0.0, max=0.15),
            cash_deposit_ratio=FeatureExpectation(min=0.0, max=0.30),
            customer_concentration=FeatureExpectation(min=0.0, max=0.45),
            supplier_concentration=FeatureExpectation(min=0.0, max=0.45),
        ),
        expected_coverage_months=Range(9, 12),
        expected_confidence=Range(0.60, 0.80),
    ),
    ArchetypeName.NEW_TO_CREDIT: ArchetypeSpec(
        name=ArchetypeName.NEW_TO_CREDIT,
        count=15,
        story=(
            "An operating business with real bank/GST history but no prior "
            "borrowing — no existing EMI, no bureau record. Distinct from "
            "thin_file: this business isn't young, it's simply never "
            "borrowed before. obligation_ratio must be a real, MEASURED "
            "zero (existing_emi_outflow genuinely 0), not undefined — a "
            "second, DIFFERENT way of exercising Step 1's zero-denominator "
            "discipline from thin_file's genuinely-undefined bank_gst_gap. "
            "ASSUMPTION FLAGGED: phase2.txt Step 3 groups thin_file and "
            "new_to_credit under one 'genuinely short coverage' bullet, but "
            "D2 names them as separate archetypes with separate economic "
            "stories (short OPERATING history vs. no CREDIT history) — read "
            "literally, forcing new_to_credit's coverage_months down to "
            "thin_file's band would make the two indistinguishable and "
            "collapse a real distinction the mix was designed to test. "
            "Coverage here (6-12 months, allow_undefined GST-bank gap) is "
            "shorter/thinner than healthy_grower but not as short as "
            "thin_file's 1-3 months; the low bureau-driven confidence band "
            "below is what actually makes this borrower 'thin' in the "
            "credit-file sense the archetype name promises."
        ),
        params=GenerationParams(
            inflow_trend=InflowTrend.FLAT,
            volatility=Volatility.LOW,
            bounce_rate=Range(0.0, 0.03),
            emi_load=Range(0.0, 0.0),
            gst_bank_relationship=GstBankRelationship.ALIGNED,
            coverage_months=Range(6, 9),
            source_count=Range(1, 2),
        ),
        expected_features=_expectations(
            dscr=FeatureExpectation(min=1.2, max=None, allow_undefined=True),
            obligation_ratio=FeatureExpectation(min=0.0, max=0.0),
            bounce_ratio=FeatureExpectation(min=0.0, max=0.05),
            bank_gst_gap=FeatureExpectation(min=0.0, max=0.15, allow_undefined=True),
            cash_deposit_ratio=FeatureExpectation(min=0.0, max=0.30),
            customer_concentration=FeatureExpectation(min=0.0, max=0.50),
            supplier_concentration=FeatureExpectation(min=0.0, max=0.50),
        ),
        expected_coverage_months=Range(6, 9),
        expected_confidence=Range(0.40, 0.70),
    ),
}

COHORT_SIZE = sum(spec.count for spec in ARCHETYPES.values())
if COHORT_SIZE != 200:
    raise AssertionError(f"Archetype mix must sum to 200 (Step 0 D1), got {COHORT_SIZE}")

FRAUD_ARCHETYPES = frozenset({ArchetypeName.GST_BANK_MISMATCH, ArchetypeName.CIRCULAR_TRANSACTIONS})
"""Archetypes whose defining trait is a Step 8 negative/fraud-like signal.
Every OTHER archetype is a false-positive-honesty check: it must NOT trip
those signals (Step 8)."""
