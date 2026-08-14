"""Circular-transaction ring detection. Implemented in Phase 2 Step 8.

Hand-built `BankTransaction` fixtures, not the generator's own output —
this is the unit-level counterpart to Step 8's PROVE IT (the cohort-level
false-positive-honesty check lives in `test_feature_engine.py`, run
against the real committed cohort through the real engine).
"""

from __future__ import annotations

from datetime import date, timedelta

from ankura.contracts.financial import BankTransaction, TransactionType
from ankura.features.signals import (
    RING_AMOUNT_TOLERANCE_FRACTION,
    RING_MAX_COUNTERPARTIES,
    RING_WINDOW_DAYS,
    find_circular_transaction_rings,
)

_DAY_0 = date(2026, 3, 10)


def _txn(
    day_offset: int,
    transaction_type: TransactionType,
    counterparty_id: str | None,
    amount_paise: int,
) -> BankTransaction:
    return BankTransaction(
        transaction_date=_DAY_0 + timedelta(days=day_offset),
        transaction_type=transaction_type,
        description="test fixture",
        amount_paise=amount_paise,
        counterparty_id=counterparty_id,
    )


def test_a_clean_three_leg_ring_is_detected() -> None:
    """Same shape as `cohort/generator.py`'s `_build_ring`: 3 legs, near-
    equal amounts, 3 distinct counterparties, alternating CREDIT/DEBIT,
    within a couple of days."""
    txns = [
        _txn(0, TransactionType.CREDIT, "RING-1", 1_00_000_00),
        _txn(1, TransactionType.DEBIT, "RING-2", 99_800_00),
        _txn(2, TransactionType.CREDIT, "RING-3", 99_900_00),
    ]
    findings = find_circular_transaction_rings(txns)
    assert len(findings) == 1
    finding = findings[0]
    assert len(finding.legs) == 3
    assert {leg.counterparty_id for leg in finding.legs} == {"RING-1", "RING-2", "RING-3"}
    assert finding.max_amount_paise == 1_00_000_00
    assert finding.min_amount_paise == 99_800_00


def test_only_two_legs_does_not_trip_the_detector() -> None:
    """RING_MIN_LEGS = 3 — two near-equal, alternating-direction payments
    between two parties is ordinary business, not a round-trip."""
    txns = [
        _txn(0, TransactionType.CREDIT, "A", 50_000_00),
        _txn(1, TransactionType.DEBIT, "B", 49_900_00),
    ]
    assert find_circular_transaction_rings(txns) == []


def test_amounts_outside_tolerance_do_not_trip_the_detector() -> None:
    """3 legs, alternating direction, small counterparty set — but the
    amounts diverge well past RING_AMOUNT_TOLERANCE_FRACTION (2%), so this
    is 3 unrelated transactions that happen to land in the same window,
    not near-equal round-tripping."""
    assert RING_AMOUNT_TOLERANCE_FRACTION < 1  # sanity on the fixture below
    txns = [
        _txn(0, TransactionType.CREDIT, "A", 1_00_000_00),
        _txn(1, TransactionType.DEBIT, "B", 60_000_00),
        _txn(2, TransactionType.CREDIT, "C", 30_000_00),
    ]
    assert find_circular_transaction_rings(txns) == []


def test_all_same_direction_does_not_trip_the_detector() -> None:
    """False-positive honesty: paying three suppliers similar amounts in
    the same week is ordinary business (all DEBIT, no round-trip
    evidence), and must not be flagged as a ring."""
    txns = [
        _txn(0, TransactionType.DEBIT, "SUPPLIER-A", 40_000_00),
        _txn(1, TransactionType.DEBIT, "SUPPLIER-B", 39_900_00),
        _txn(2, TransactionType.DEBIT, "SUPPLIER-C", 40_050_00),
    ]
    assert find_circular_transaction_rings(txns) == []


def test_a_diffuse_cluster_is_capped_at_the_counterparty_bound() -> None:
    """RING_MAX_COUNTERPARTIES bounds the SIZE of any one finding, not
    whether a diffuse tight cluster gets flagged at all — a wider cluster
    of near-equal, type-mixed, distinct-counterparty transactions still
    contains a genuine small ring inside it (each leg here has a unique
    counterparty, same as the generator's own ring shape), so the detector
    correctly reports the largest valid sub-ring rather than nothing."""
    counterparty_count = RING_MAX_COUNTERPARTIES + 2
    txns = [
        _txn(
            i,
            TransactionType.CREDIT if i % 2 == 0 else TransactionType.DEBIT,
            f"CP-{i}",
            1_00_000_00,
        )
        for i in range(counterparty_count)
    ]
    findings = find_circular_transaction_rings(txns)
    assert len(findings) == 1
    assert len(findings[0].legs) == RING_MAX_COUNTERPARTIES
    assert len({leg.counterparty_id for leg in findings[0].legs}) == RING_MAX_COUNTERPARTIES


def test_legs_outside_the_window_are_not_included() -> None:
    """A leg landing after RING_WINDOW_DAYS from the earliest candidate
    breaks the ring — near-equal amounts spread across months is not a
    short-window round-trip."""
    txns = [
        _txn(0, TransactionType.CREDIT, "RING-1", 1_00_000_00),
        _txn(1, TransactionType.DEBIT, "RING-2", 99_900_00),
        _txn(RING_WINDOW_DAYS + 5, TransactionType.CREDIT, "RING-3", 99_950_00),
    ]
    assert find_circular_transaction_rings(txns) == []


def test_transactions_without_a_counterparty_are_ignored() -> None:
    """Cash deposits/withdrawals (counterparty_id=None) can never be a ring
    leg — there is no counterparty to form a round-trip with."""
    txns = [
        _txn(0, TransactionType.CREDIT, None, 1_00_000_00),
        _txn(1, TransactionType.DEBIT, None, 99_900_00),
        _txn(2, TransactionType.CREDIT, None, 99_950_00),
    ]
    assert find_circular_transaction_rings(txns) == []


def test_each_transaction_claimed_by_at_most_one_finding() -> None:
    """Two independent 3-leg rings, far enough apart to be un-ambiguous,
    each produce their own finding — no transaction is double-counted."""
    txns = [
        _txn(0, TransactionType.CREDIT, "RING-1", 1_00_000_00),
        _txn(1, TransactionType.DEBIT, "RING-2", 99_900_00),
        _txn(2, TransactionType.CREDIT, "RING-3", 99_950_00),
        _txn(30, TransactionType.CREDIT, "RING-4", 50_000_00),
        _txn(31, TransactionType.DEBIT, "RING-5", 49_900_00),
        _txn(32, TransactionType.CREDIT, "RING-6", 49_950_00),
    ]
    findings = find_circular_transaction_rings(txns)
    assert len(findings) == 2
    claimed_dates = {leg.transaction_date for f in findings for leg in f.legs}
    assert claimed_dates == {t.transaction_date for t in txns}
