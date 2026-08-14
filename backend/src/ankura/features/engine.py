"""The feature engine — Phase 2 Step 6, this phase's centrepiece.

`compute_features(canonical_data, as_of, clock)` turns a
`CanonicalFinancialData` into a `FeatureSnapshot`. This module is
ORCHESTRATION ONLY: it windows the data, aggregates it, and calls the
Step 1 metric functions (`features.metrics`). It does not contain a
second copy of any formula — if you find yourself writing
`numerator / denominator` in this file, stop; that formula belongs in
`metrics.py`, not here (final architecture.txt §14.2).

There is NO threshold, band, or comparison-that-decides anywhere in this
module. `compute_features()` can tell you `dscr = 1.72`; it can never tell
you whether 1.72 is good. A threshold comparison here means Phase 3 scope
has leaked backward — see phase2.txt Step 6.

Windowing (Step 0 D7): trailing `WINDOW_MONTHS` calendar months relative to
`as_of`, never "the last N calendar months" and never re-derived from the
clock. `clock` is used for exactly one thing — stamping `computed_at` — and
is never consulted for windowing; an engine that windows off the clock
instead of `as_of` is not replayable, which is the entire point of P1 Step
10's clock discipline.

ASSUMPTION FLAGGED (proposed-EMI / dscr scope, same one `cohort/generator.py`
flagged at Step 4, now resolved consistently here): §14.2 says `dscr`'s
`total_debt_service` includes the proposed EMI, but `compute_features()`'s
own signature — `(canonical_data, as_of, clock)` — has no way to read a
requested loan amount/tenure (those live on `ApplicationIn`/`Out`, Phase 1,
not on `CanonicalFinancialData`). This engine therefore computes `dscr` from
EXISTING debt service only, exactly matching what the Step 4 generator
already targets — so the Step 11 regression suite comparing generated
transactions against this engine's output has a consistent definition to
regress against. Adding a genuine proposed-EMI component is Phase 3's job,
once a decision endpoint exists that actually has a requested amount/tenure
to pass in.

Convention pinned in `generator.py` (Step 4) and honored here: the
`bounce_ratio` presented-instrument count is NON-EMI debit transactions
only (EMI is an auto-debit mandate, not a presented cheque/vendor
instrument, and already has its own signal via `obligation_ratio`/`dscr`).

`data_quality.confidence` (Step 7, finalized): a documented, deterministic
function of coverage_months, source_count, and how many of the 7 §14.2
metrics came back undefined — pinned in `_compute_confidence()` below and
in `final architecture.txt` §14.2. It is NOT a probability of default and
must never be described as one anywhere (code, docstring, console copy) —
it measures how much evidence a snapshot rests on, nothing about the
borrower's likelihood of repayment.

ASSUMPTION FLAGGED (confidence vs. `archetypes.py`'s `expected_confidence`):
several archetypes (seasonal_trader, declining_business, gst_bank_mismatch,
circular_transactions, over_leveraged, recovering_from_stress) share
IDENTICAL `coverage_months`/`source_count` generation ranges (9-12 months,
2-3 sources, 0 undefined metrics) yet were assigned different
`expected_confidence` bands back at Step 3 — before this formula existed.
No function of (coverage, source, undefined-count) alone can hit every one
of those bands for every possible draw, so this engine deliberately does
NOT try to reproduce `archetypes.py`'s `expected_confidence` field.  That
field feeds the GENERATOR's own synthetic `CanonicalFinancialData.
data_quality.confidence` (`cohort/generator.py`'s `generate_borrower`) — an
upstream, provider-self-reported figure the engine already ignores by
design (Step 6: `compute_features()` never reads `canonical_data.
data_quality`). Confidence here is independently DERIVED from what the
engine can itself observe post-windowing, never trusted from the input.
Step 7's actual proof obligation — thin_file/new_to_credit clustering at
the bottom, healthy_grower at the top — is an ordering/clustering property
across the real cohort, verified in `tests/test_feature_engine.py`, not a
per-borrower match against `archetypes.py`'s `expected_confidence` range.

Step 8 (negative/fraud-like signals): `bank_gst_gap` now compares ALIGNED
windows — `_aligned_bank_credit_turnover()` restricts the bank side to
exactly the calendar months GST has filed data for, never the full
12-month bank window regardless of how much GST coverage exists (see its
own docstring for the bug this fixes). Circular-transaction ring detection
(`features/signals.py`'s `find_circular_transaction_rings()`) runs over the
same windowed transactions and returns structured evidence, never a bare
bool — see that module's docstring for the detection parameters and why
each one is set where it is. Neither signal decides anything; both are
evidence for Phase 3 (or a human reviewer) to weigh.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from typing import Any

from ankura.clock import Clock
from ankura.contracts.common import AsOf
from ankura.contracts.features import FeatureSnapshot, ProvenanceEntry
from ankura.contracts.financial import (
    BankTransaction,
    CanonicalFinancialData,
    DataQuality,
    TransactionType,
)
from ankura.features import metrics as m
from ankura.features.metrics import FEATURE_ENGINE_VERSION
from ankura.features.signals import find_circular_transaction_rings

WINDOW_MONTHS = 12
"""Trailing-window length, relative to `as_of` (Step 0 D7). Not the same
thing as an archetype's `coverage_months` target (Step 3/4) — a borrower
with only 6 months of real history still gets windowed against a 12-month
frame; `coverage_months` on the resulting `DataQuality` is how few of
those 12 months actually had data, not the window size itself."""


def _canonical_json(payload: dict[str, Any]) -> str:
    """Same stable-serialisation shape as `services/audit.py`'s
    `canonical_json` (sorted keys, fixed separators, `default=str`) —
    duplicated rather than imported because `features/` must not depend on
    `services/` (orchestration/persistence layer); a two-line helper is
    cheaper than that coupling."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_input_hash(canonical_data: CanonicalFinancialData) -> str:
    """SHA-256 hex digest of the canonicalized input — what Phase 3's
    replay endpoint checks to prove "same input, same engine version, same
    output" without ever persisting the raw payload itself (D9)."""
    canonical = _canonical_json(canonical_data.model_dump(mode="json"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _trailing_window(as_of: AsOf, months: int) -> tuple[date, date]:
    """[window_start, window_end] inclusive, `months` calendar months
    ending at `as_of`'s own calendar month — e.g. `months=12` with an
    `as_of` of 2026-08-13 windows from 2025-09-01 through 2026-08-13."""
    window_end = as_of.date()
    year, month = window_end.year, window_end.month
    for _ in range(months - 1):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    window_start = date(year, month, 1)
    return window_start, window_end


def _transactions_in_window(
    canonical_data: CanonicalFinancialData, window_start: date, window_end: date
) -> list[BankTransaction]:
    return [
        txn
        for account in canonical_data.bank_accounts
        for txn in account.transactions
        if window_start <= txn.transaction_date <= window_end
    ]


def _distinct_months_with_data(transactions: list[BankTransaction]) -> int:
    """Actual distinct calendar months with at least one transaction —
    NOT the span between the first and last transaction date (Step 7 pins
    this distinction formally; Step 6 already needs it to avoid dividing
    by a window size that has no data behind it)."""
    return len({(t.transaction_date.year, t.transaction_date.month) for t in transactions})


@dataclass(frozen=True)
class _Aggregates:
    """Intermediate sums this engine derives from windowed transactions
    before handing them to the Step 1 metric functions — the "own tested
    helpers, not inline" the plan asks for (phase2.txt Step 6)."""

    total_credits: int
    average_monthly_inflow: int
    existing_emi_outflow_monthly: int
    net_operating_surplus: int
    non_emi_debit_count: int
    bounced_count: int
    cash_deposits: int
    top_counterparty_credits: int
    top_counterparty_debits: int
    total_non_emi_debits_ok: int


def _aggregate(transactions: list[BankTransaction], coverage_months: int) -> _Aggregates:
    if coverage_months == 0:
        return _Aggregates(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    total_credits = sum(
        t.amount_paise for t in transactions if t.transaction_type is TransactionType.CREDIT
    )
    average_monthly_inflow = total_credits // coverage_months

    existing_emi_total = sum(t.amount_paise for t in transactions if t.is_debt_service)
    existing_emi_outflow_monthly = existing_emi_total // coverage_months

    non_emi_debits = [
        t
        for t in transactions
        if t.transaction_type is TransactionType.DEBIT and not t.is_debt_service
    ]
    total_non_emi_debits_ok = sum(t.amount_paise for t in non_emi_debits if not t.bounced)
    bounced_count = sum(1 for t in non_emi_debits if t.bounced)

    operating_expenses_monthly = total_non_emi_debits_ok // coverage_months
    net_operating_surplus = average_monthly_inflow - operating_expenses_monthly

    cash_deposits = sum(t.amount_paise for t in transactions if t.is_cash)

    credit_by_counterparty: dict[str, int] = {}
    for t in transactions:
        if t.transaction_type is TransactionType.CREDIT and t.counterparty_id:
            credit_by_counterparty[t.counterparty_id] = (
                credit_by_counterparty.get(t.counterparty_id, 0) + t.amount_paise
            )
    top_counterparty_credits = max(credit_by_counterparty.values(), default=0)

    debit_by_counterparty: dict[str, int] = {}
    for t in non_emi_debits:
        if t.counterparty_id and not t.bounced:
            debit_by_counterparty[t.counterparty_id] = (
                debit_by_counterparty.get(t.counterparty_id, 0) + t.amount_paise
            )
    top_counterparty_debits = max(debit_by_counterparty.values(), default=0)

    return _Aggregates(
        total_credits=total_credits,
        average_monthly_inflow=average_monthly_inflow,
        existing_emi_outflow_monthly=existing_emi_outflow_monthly,
        net_operating_surplus=net_operating_surplus,
        non_emi_debit_count=len(non_emi_debits),
        bounced_count=bounced_count,
        cash_deposits=cash_deposits,
        top_counterparty_credits=top_counterparty_credits,
        top_counterparty_debits=top_counterparty_debits,
        total_non_emi_debits_ok=total_non_emi_debits_ok,
    )


def _gst_turnover_in_window(
    canonical_data: CanonicalFinancialData, window_start: date, window_end: date
) -> tuple[int | None, list[str]]:
    """Sum of filed GST turnover whose period falls inside the same
    trailing window as the bank data. `None` (not 0) when nothing was filed
    in-window, so `bank_gst_gap` correctly comes back undefined rather than
    a fabricated 100% gap. Returns the exact `months_used` list — Step 8
    doubles this as the aligned window: `_aligned_bank_credit_turnover()`
    below restricts the BANK side of `bank_gst_gap` to exactly these same
    months, so the ratio never compares (e.g.) 12 months of bank turnover
    against 6 months of GST filings, a real and easy bug (phase2.txt Step
    8) — comparing mismatched windows would silently overstate the gap for
    any borrower whose GST filing history is shorter than its bank
    history, which real (P7) providers make no promise not to hand us."""
    months_in_window: list[str] = []
    total = 0
    found = False
    for record in canonical_data.gst_returns:
        if record.filed_on is None:
            continue
        period_start = date(int(record.period[:4]), int(record.period[5:7]), 1)
        if not (window_start <= period_start <= window_end):
            continue
        found = True
        total += record.turnover_paise
        months_in_window.append(record.period)
    if not found:
        return None, []
    return total, sorted(months_in_window)


def _month_key(transaction: BankTransaction) -> str:
    return f"{transaction.transaction_date.year:04d}-{transaction.transaction_date.month:02d}"


def _aligned_bank_credit_turnover(
    transactions: list[BankTransaction], months_used: list[str]
) -> int:
    """Bank credit turnover restricted to exactly the calendar months GST
    actually has filed data for (`months_used`, from
    `_gst_turnover_in_window`) — the Step 8 alignment fix. Deliberately a
    SEPARATE figure from `_Aggregates.total_credits` (which stays the full
    12-month bank total for every other metric): `bank_gst_gap` is the only
    ratio that compares two different sources against each other, so it is
    the only one that needs its own aligned inputs rather than the shared
    window aggregate."""
    aligned_months = set(months_used)
    return sum(
        t.amount_paise
        for t in transactions
        if t.transaction_type is TransactionType.CREDIT and _month_key(t) in aligned_months
    )


_UNDEFINED_METRIC_DENOMINATOR = 7
"""Fixed denominator for `C_defined` — the count of §14.2 metrics
(`dscr`, `obligation_ratio`, `bounce_ratio`, `bank_gst_gap`,
`cash_deposit_ratio`, `customer_concentration`, `supplier_concentration`),
pinned as a constant rather than derived dynamically from
`FeatureSnapshot`'s field count. If a future engine version adds an eighth
metric, that is a `FEATURE_ENGINE_VERSION` bump (module docstring / CLAUDE.md
rule 3) with a deliberate decision about this constant — never a silent
change to what an already-computed historical confidence score means."""


def _compute_confidence(
    coverage_months: int, source_count: int, undefined_metric_count: int
) -> float:
    """Final Step 7 confidence formula — a documented, deterministic
    function of three evidence signals, pinned once here and in
    `final architecture.txt` §14.2:

        confidence = 0.5*C_coverage + 0.3*C_source + 0.2*C_defined
          C_coverage = min(coverage_months, WINDOW_MONTHS) / WINDOW_MONTHS
          C_source   = min(source_count, 3) / 3
          C_defined  = (7 - undefined_metric_count) / 7

    Weights: coverage counts most (the strongest evidence signal — a thin
    statement history can't be offset by having many sources attached),
    source diversity second, and how many of the 7 metrics actually came
    back defined (not None) third — an archetype that produces several
    structurally-undefined metrics (Step 1's zero-denominator discipline)
    genuinely rests on less usable evidence, even with good coverage.

    Computed in `Decimal` (D5 discipline — never binary-float
    intermediates), rounded ROUND_HALF_UP to 6 decimal places, clamped to
    [0, 1], exposed as `float`. NOT a probability of default — see module
    docstring."""
    coverage_component = Decimal(min(coverage_months, WINDOW_MONTHS)) / Decimal(WINDOW_MONTHS)
    source_component = Decimal(min(source_count, 3)) / Decimal(3)
    defined_component = Decimal(_UNDEFINED_METRIC_DENOMINATOR - undefined_metric_count) / Decimal(
        _UNDEFINED_METRIC_DENOMINATOR
    )
    raw = (
        coverage_component * Decimal("0.5")
        + source_component * Decimal("0.3")
        + defined_component * Decimal("0.2")
    )
    rounded = raw.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    clamped = max(Decimal("0.0"), min(Decimal("1.0"), rounded))
    return float(clamped)


def _build_provenance(
    canonical_data: CanonicalFinancialData,
    transactions: list[BankTransaction],
    gst_months_used: list[str],
) -> list[ProvenanceEntry]:
    entries: list[ProvenanceEntry] = []
    bank_months = sorted(
        {f"{t.transaction_date.year:04d}-{t.transaction_date.month:02d}" for t in transactions}
    )
    if canonical_data.bank_accounts:
        entries.append(
            ProvenanceEntry(
                source="bank",
                source_as_of=canonical_data.as_of,
                months_used=bank_months,
            )
        )
    if gst_months_used:
        entries.append(
            ProvenanceEntry(
                source="gst",
                source_as_of=canonical_data.as_of,
                months_used=gst_months_used,
            )
        )
    if canonical_data.bureau is not None:
        entries.append(
            ProvenanceEntry(
                source="bureau",
                source_as_of=canonical_data.as_of,
                months_used=[],
            )
        )
    return entries


def compute_features(
    canonical_data: CanonicalFinancialData, as_of: AsOf, clock: Clock
) -> FeatureSnapshot:
    """Turn `canonical_data` into a versioned, provenance-carrying
    `FeatureSnapshot`. Pure orchestration: windows, aggregates, calls
    `features.metrics`. `clock` is used ONLY for `computed_at` — every
    other computation is relative to the explicit `as_of`, never the
    clock, so this function is replayable byte-for-byte (Step 6 PROVE IT)."""
    computed_at = clock.now()
    window_start, window_end = _trailing_window(as_of, WINDOW_MONTHS)

    transactions = _transactions_in_window(canonical_data, window_start, window_end)
    coverage_months = _distinct_months_with_data(transactions)
    agg = _aggregate(transactions, coverage_months)
    gst_turnover, gst_months_used = _gst_turnover_in_window(
        canonical_data, window_start, window_end
    )

    dscr = m.dscr(agg.net_operating_surplus, agg.existing_emi_outflow_monthly)
    obligation_ratio = m.obligation_ratio(
        agg.existing_emi_outflow_monthly, agg.average_monthly_inflow
    )
    bounce_ratio = m.bounce_ratio(agg.bounced_count, agg.non_emi_debit_count)
    bank_gst_gap = (
        m.bank_gst_gap(_aligned_bank_credit_turnover(transactions, gst_months_used), gst_turnover)
        if gst_turnover is not None
        else None
    )
    cash_deposit_ratio = m.cash_deposit_ratio(agg.cash_deposits, agg.total_credits)
    customer_concentration = m.customer_concentration(
        agg.top_counterparty_credits, agg.total_credits
    )
    supplier_concentration = m.supplier_concentration(
        agg.top_counterparty_debits, agg.total_non_emi_debits_ok
    )

    source_count = (
        (1 if canonical_data.bank_accounts else 0)
        + (1 if gst_turnover is not None else 0)
        + (1 if canonical_data.bureau is not None else 0)
    )
    computed_metrics = (
        dscr,
        obligation_ratio,
        bounce_ratio,
        bank_gst_gap,
        cash_deposit_ratio,
        customer_concentration,
        supplier_concentration,
    )
    undefined_metric_count = sum(1 for value in computed_metrics if value is None)
    data_quality = DataQuality(
        coverage_months=coverage_months,
        source_count=source_count,
        confidence=_compute_confidence(coverage_months, source_count, undefined_metric_count),
    )

    provenance = _build_provenance(canonical_data, transactions, gst_months_used)
    circular_transaction_findings = find_circular_transaction_rings(transactions)

    return FeatureSnapshot(
        application_id=canonical_data.application_id,
        as_of=as_of,
        computed_at=computed_at,
        feature_engine_version=FEATURE_ENGINE_VERSION,
        input_hash=compute_input_hash(canonical_data),
        dscr=dscr,
        obligation_ratio=obligation_ratio,
        bounce_ratio=bounce_ratio,
        bank_gst_gap=bank_gst_gap,
        cash_deposit_ratio=cash_deposit_ratio,
        customer_concentration=customer_concentration,
        supplier_concentration=supplier_concentration,
        data_quality=data_quality,
        provenance=provenance,
        circular_transaction_findings=circular_transaction_findings,
    )
