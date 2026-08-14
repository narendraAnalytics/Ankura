"""Deterministic cohort generator. Implemented in Phase 2 Step 4.

Covers the Step 4 PROVE IT (same-process AND cross-process byte-identical
regeneration) plus the "derived from the formula, never hand-typed" claim:
every one of the 200 borrowers is fed through the real
`features.metrics.*` functions (recomputing the same aggregates a Step 6
engine would independently derive from the transactions) and checked
against its own archetype's `expected_features` from archetypes.py.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime

import pytest

from ankura.cohort.archetypes import ARCHETYPES, ArchetypeName
from ankura.cohort.generator import (
    ARCHETYPE_ASSIGNMENT,
    DEFAULT_COHORT_AS_OF,
    generate_borrower,
    generate_cohort,
)
from ankura.contracts.financial import TransactionType
from ankura.features import metrics as m

_AS_OF = datetime(2026, 8, 13, tzinfo=UTC)


def test_archetype_assignment_matches_the_200_borrower_mix() -> None:
    assert len(ARCHETYPE_ASSIGNMENT) == 200
    counts: dict[ArchetypeName, int] = {}
    for name in ARCHETYPE_ASSIGNMENT:
        counts[name] = counts.get(name, 0) + 1
    assert counts == {name: spec.count for name, spec in ARCHETYPES.items()}


def test_same_process_regeneration_is_byte_identical() -> None:
    first = [b.model_dump_json() for b in generate_cohort(DEFAULT_COHORT_AS_OF)]
    second = [b.model_dump_json() for b in generate_cohort(DEFAULT_COHORT_AS_OF)]
    assert first == second


def test_cross_process_regeneration_is_byte_identical() -> None:
    """Step 4 PROVE IT: generate in two SEPARATE processes, not just twice
    in the same one — catches any accidental dependence on process-local
    state (e.g. Python's salted `hash()`, which this module deliberately
    avoids in favor of `hashlib.sha256`)."""
    script = (
        "from ankura.cohort.generator import generate_cohort, DEFAULT_COHORT_AS_OF\n"
        "import hashlib\n"
        "cohort = generate_cohort(DEFAULT_COHORT_AS_OF)\n"
        "digest = hashlib.sha256(''.join(b.model_dump_json() for b in cohort).encode())\n"
        "print(digest.hexdigest())\n"
    )
    first = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    second = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert first.stdout.strip() == second.stdout.strip()
    assert len(first.stdout.strip()) == 64  # a real sha256 hex digest, not an empty run


def test_generate_borrower_rejects_naive_as_of() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        generate_borrower(0, ArchetypeName.HEALTHY_GROWER, datetime(2026, 8, 13))  # noqa: DTZ001


@pytest.mark.parametrize("archetype", list(ArchetypeName))
def test_one_borrower_per_archetype_matches_its_own_expected_signature(
    archetype: ArchetypeName,
) -> None:
    """Every archetype gets at least one concrete, formula-verified check
    here; the exhaustive all-200 sweep lives in
    test_full_cohort_matches_expected_signatures below."""
    borrower_index = ARCHETYPE_ASSIGNMENT.index(archetype)
    _assert_matches_signature(borrower_index, archetype)


def test_full_cohort_matches_expected_signatures() -> None:
    failures: list[tuple[int, ArchetypeName, str, float | None]] = []
    for index, archetype in enumerate(ARCHETYPE_ASSIGNMENT):
        failures.extend(_signature_failures(index, archetype))
    assert not failures, failures[:10]


def _assert_matches_signature(borrower_index: int, archetype: ArchetypeName) -> None:
    failures = _signature_failures(borrower_index, archetype)
    assert not failures, failures


def _signature_failures(
    borrower_index: int, archetype: ArchetypeName
) -> list[tuple[int, ArchetypeName, str, float | None]]:
    """Recompute every §14.2 metric from the generated transactions using
    the SAME pinned formulas (features/metrics.py) a real engine would
    call, and check each against the archetype's declared expected_features
    — the empirical half of Step 4's "derived from the formula" claim."""
    borrower = generate_borrower(borrower_index, archetype, _AS_OF)
    spec = ARCHETYPES[archetype]
    txns = borrower.bank_accounts[0].transactions
    n = borrower.data_quality.coverage_months

    total_credits = sum(
        t.amount_paise for t in txns if t.transaction_type is TransactionType.CREDIT
    )
    non_emi_debits = [
        t for t in txns if t.transaction_type is TransactionType.DEBIT and not t.is_debt_service
    ]
    total_non_emi_debits_ok = sum(t.amount_paise for t in non_emi_debits if not t.bounced)
    cash = sum(t.amount_paise for t in txns if t.is_cash)
    bounced_count = sum(1 for t in non_emi_debits if t.bounced)
    emi_monthly = sum(t.amount_paise for t in txns if t.is_debt_service) // n
    average_monthly_inflow = total_credits // n
    net_operating_surplus = average_monthly_inflow - (total_non_emi_debits_ok // n)

    def _top(counterparties: list[str | None], amounts_by_cp: dict[str, int]) -> int:
        return max(amounts_by_cp.values(), default=0)

    credit_by_cp: dict[str, int] = {}
    for t in txns:
        if t.transaction_type is TransactionType.CREDIT and t.counterparty_id:
            credit_by_cp[t.counterparty_id] = (
                credit_by_cp.get(t.counterparty_id, 0) + t.amount_paise
            )
    debit_by_cp: dict[str, int] = {}
    for t in non_emi_debits:
        if t.counterparty_id and not t.bounced:
            debit_by_cp[t.counterparty_id] = debit_by_cp.get(t.counterparty_id, 0) + t.amount_paise

    gst_turnover = sum(g.turnover_paise for g in borrower.gst_returns)

    computed = {
        "dscr": m.dscr(net_operating_surplus, emi_monthly),
        "obligation_ratio": m.obligation_ratio(emi_monthly, average_monthly_inflow),
        "bounce_ratio": m.bounce_ratio(bounced_count, len(non_emi_debits)),
        "bank_gst_gap": (
            m.bank_gst_gap(total_credits, gst_turnover) if borrower.gst_returns else None
        ),
        "cash_deposit_ratio": m.cash_deposit_ratio(cash, total_credits),
        "customer_concentration": m.customer_concentration(
            _top(list(credit_by_cp), credit_by_cp), total_credits
        ),
        "supplier_concentration": (
            m.supplier_concentration(_top(list(debit_by_cp), debit_by_cp), total_non_emi_debits_ok)
            if total_non_emi_debits_ok
            else None
        ),
    }

    failures: list[tuple[int, ArchetypeName, str, float | None]] = []
    for field, value in computed.items():
        expectation = spec.expected_features[field]
        if not expectation.matches(value):
            failures.append((borrower_index, archetype, field, value))
    return failures


def test_circular_transactions_archetype_actually_contains_a_ring() -> None:
    borrower_index = ARCHETYPE_ASSIGNMENT.index(ArchetypeName.CIRCULAR_TRANSACTIONS)
    borrower = generate_borrower(borrower_index, ArchetypeName.CIRCULAR_TRANSACTIONS, _AS_OF)
    ring_counterparties = {"RING-1", "RING-2", "RING-3"}
    ring_txns = [
        t
        for t in borrower.bank_accounts[0].transactions
        if t.counterparty_id in ring_counterparties
    ]
    assert len(ring_txns) == 3
    dates = sorted(t.transaction_date for t in ring_txns)
    assert (dates[-1] - dates[0]).days <= 6  # short window, per Step 3/4's ring requirement
    amounts = [t.amount_paise for t in ring_txns]
    assert (max(amounts) - min(amounts)) / max(amounts) < 0.02  # near-equal amounts


def test_thin_file_borrower_has_no_gst_returns() -> None:
    borrower_index = ARCHETYPE_ASSIGNMENT.index(ArchetypeName.THIN_FILE)
    borrower = generate_borrower(borrower_index, ArchetypeName.THIN_FILE, _AS_OF)
    assert borrower.gst_returns == []


def test_generated_borrowers_are_indistinguishable_in_shape_from_a_real_provider() -> None:
    """Nothing about a synthetic CanonicalFinancialData should be
    recognizable as synthetic by the feature engine (Step 4's own
    requirement) — the strongest check available before Step 6 exists is
    that it round-trips through the exact same contract with no extra
    fields and no missing required ones."""
    from ankura.contracts.financial import CanonicalFinancialData

    borrower = generate_borrower(0, ArchetypeName.HEALTHY_GROWER, _AS_OF)
    round_tripped = CanonicalFinancialData.model_validate_json(borrower.model_dump_json())
    assert round_tripped == borrower
