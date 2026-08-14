"""Negative / fraud-like signal detection — Phase 2 Step 8.

Signals, not verdicts: this module reports "these N transactions form a
ring — near-equal amounts, a small, ISOLATED counterparty set, a short
window" — it NEVER reports "this borrower is a fraudster". That
interpretive step is Phase 3's policy engine (and, ultimately, a human
reviewer's judgement). Same discipline as `features/metrics.py`: pure
functions, no DB/clock/I/O, evidence out, no decision.

Only circular-transaction ring detection lives here today (Step 0 D8:
`bank_gst_gap`'s window-alignment fix and `cash_deposit_ratio` are already
covered by `features/metrics.py` + `features/engine.py`; overdraft
utilisation / sudden-account-routing are deferred to P7).

WHY "ISOLATED" IS THE LOAD-BEARING CHECK, NOT AMOUNT TOLERANCE ALONE:
an earlier version of this detector relied on (short window + near-equal
amounts + mixed CREDIT/DEBIT types) alone, and false-tripped on ordinary
generated business data: `cohort/generator.py` diversifies a borrower's
monthly inflow/outflow across a small fixed pool of recurring counterparty
ids (`CUSTOMER-0..4`, `SUPPLIER-0..4`) via an even split, which routinely
produces 2-3 transactions of near-identical (sometimes literally
1-paise-apart, from integer-division remainder handling) amounts, mixed
CREDIT/DEBIT direction, inside a short window — indistinguishable from a
real ring by amount/type/window alone. What genuinely distinguishes the
synthetic ring (`_build_ring`'s `RING-1`/`RING-2`/`RING-3`) is that those
counterparty ids appear EXACTLY ONCE, ever, in the borrower's entire
windowed history — unlike `CUSTOMER-N`/`SUPPLIER-N`, which are the
borrower's ordinary, recurring trading relationships and appear dozens of
times across the year. A counterparty that transacts once, in a tight
near-equal-amount cluster, and is never seen again, is a materially
different — and considerably more suspicious — pattern than a regular
customer's invoice happening to land near another regular payment.
Verified empirically: adding this ISOLATION requirement alone (with the
original, looser 6-day/2%-tolerance bounds) took the detector from ~20-40
false positives across the 200-borrower committed cohort to zero, with the
5/5 real circular_transactions borrowers still all detected
(`tests/test_feature_engine.py`'s cohort-level PROVE IT).

RING DETECTION PARAMETERS (named constants, not scattered literals —
document the choice and why here, the single place a future tuning pass
would look):

    RING_WINDOW_DAYS = 6
        Maximum span between a candidate ring's earliest and latest leg.
        Matches `cohort/generator.py`'s own ring-construction bound (its
        3 legs land within 2 consecutive days, well inside this).

    RING_MIN_LEGS = 3
        A genuine A->B->C->A round-trip needs at least 3 legs; 2
        transactions can never establish a "circular" pattern — that's
        just two payments between two parties, which happens constantly
        in ordinary business.

    RING_MAX_COUNTERPARTIES = 4
        "Small counterparty set" (Step 8). A 3-leg ring touches exactly 3
        distinct counterparties; the +1 headroom tolerates a shared
        intermediary appearing on more than one leg without opening the
        detector up to a borrower's entire monthly counterparty list.

    RING_AMOUNT_TOLERANCE_FRACTION = Decimal("0.02")
        "Near-equal amounts": every leg in a candidate ring must fall
        within 2% of that candidate's largest leg. Loose enough to absorb
        the generator's own deliberate up-to-Rs.500 per-leg noise; safe to
        leave loose (rather than hand-tuned tight) precisely BECAUSE the
        isolation requirement below is what actually carries the
        false-positive-honesty burden.

A candidate ring must ALSO:
  - span at least two distinct `TransactionType`s (both a CREDIT and a
    DEBIT leg) — a cluster of same-direction payments (e.g. paying three
    suppliers similar amounts the same week) is ordinary business, not
    evidence of money round-tripping;
  - be ISOLATED — every counterparty in the candidate ring must appear
    NOWHERE else in the borrower's windowed transaction history outside
    that one candidate cluster (see rationale above). This is the
    discriminator that actually makes the detector honest, not the
    amount tolerance.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from ankura.contracts.features import CircularTransactionFinding, RingLeg
from ankura.contracts.financial import BankTransaction

RING_WINDOW_DAYS = 6
RING_MIN_LEGS = 3
RING_MAX_COUNTERPARTIES = 4
RING_AMOUNT_TOLERANCE_FRACTION = Decimal("0.02")


@dataclass(frozen=True)
class _Candidate:
    index: int
    transaction: BankTransaction
    counterparty_id: str
    """Narrowed, non-`None` copy of `transaction.counterparty_id` — only
    transactions that already have one are ever turned into a `_Candidate`
    (see the comprehension in `find_circular_transaction_rings`), but the
    contract field itself stays `str | None`, so this field exists purely
    to keep every downstream `Counter[str]`/set operation type-clean
    without re-asserting non-`None`-ness at every call site."""


def find_circular_transaction_rings(
    transactions: Sequence[BankTransaction],
) -> list[CircularTransactionFinding]:
    """Find rings of near-equal-amount transactions moving through a
    small, ISOLATED counterparty set within a short window (Step 8). Pure:
    transactions in, findings out — no DB/clock/I/O, no verdict.
    `transactions` is expected to already be the engine's windowed set
    (`features/engine.py`), not the borrower's full unwindowed history —
    "isolated" is judged relative to whatever history is passed in.

    Greedy, deterministic scan: transactions are sorted by date once, then
    walked left to right. At each not-yet-claimed transaction, every
    tolerance-satisfying, type-mixed, counterparty-bounded, ISOLATED subset
    of the transactions within `RING_WINDOW_DAYS` is considered, and the
    LARGEST such subset (strongest evidence) is taken as one finding; its
    transactions are then marked claimed so no transaction is ever counted
    into two findings. Deterministic because there is no randomness and
    ties are broken by transaction order, which is itself already fixed by
    (date, insertion order) sorting."""
    candidates = sorted(
        (
            _Candidate(index, txn, txn.counterparty_id)
            for index, txn in enumerate(transactions)
            if txn.counterparty_id is not None
        ),
        key=lambda c: c.transaction.transaction_date,
    )
    # Total occurrences of each counterparty across the WHOLE windowed
    # history — a candidate ring's counterparties must appear only within
    # the candidate itself, never elsewhere in this count.
    counterparty_totals = Counter(c.counterparty_id for c in candidates)

    claimed: set[int] = set()
    findings: list[CircularTransactionFinding] = []

    for anchor_pos, anchor in enumerate(candidates):
        if anchor.index in claimed:
            continue
        window_end = anchor.transaction.transaction_date + timedelta(days=RING_WINDOW_DAYS)
        window = [
            c
            for c in candidates[anchor_pos:]
            if c.index not in claimed and c.transaction.transaction_date <= window_end
        ]
        if len(window) < RING_MIN_LEGS:
            continue

        best = _largest_valid_subset(window, counterparty_totals)
        if best is None:
            continue

        legs = sorted(best, key=lambda c: c.transaction.transaction_date)
        amounts = [c.transaction.amount_paise for c in legs]
        findings.append(
            CircularTransactionFinding(
                window_start=legs[0].transaction.transaction_date,
                window_end=legs[-1].transaction.transaction_date,
                legs=[
                    RingLeg(
                        transaction_date=c.transaction.transaction_date,
                        transaction_type=c.transaction.transaction_type,
                        counterparty_id=c.counterparty_id,
                        amount_paise=c.transaction.amount_paise,
                    )
                    for c in legs
                ],
                max_amount_paise=max(amounts),
                min_amount_paise=min(amounts),
            )
        )
        claimed.update(c.index for c in legs)

    return findings


def _largest_valid_subset(
    window: list[_Candidate], counterparty_totals: Counter[str]
) -> list[_Candidate] | None:
    """Among `window` (already date-bounded), find the largest subset that
    is simultaneously amount-tight, type-mixed, counterparty-bounded, and
    isolated — scanned by trying every contiguous run over the
    amount-sorted window, which is enough to find the best run since
    adding a transaction whose amount falls outside the tolerance of the
    run's current max can only ever break the tolerance check, never help
    it."""
    by_amount = sorted(window, key=lambda c: c.transaction.amount_paise)
    best: list[_Candidate] | None = None
    for start in range(len(by_amount)):
        for end in range(start + RING_MIN_LEGS - 1, len(by_amount)):
            run = by_amount[start : end + 1]
            if best is not None and len(run) <= len(best):
                continue
            if not _is_valid_ring(run, counterparty_totals):
                continue
            best = run
    return best


def _is_valid_ring(run: list[_Candidate], counterparty_totals: Counter[str]) -> bool:
    amounts = [c.transaction.amount_paise for c in run]
    max_amount, min_amount = max(amounts), min(amounts)
    if max_amount == 0:
        return False
    spread = Decimal(max_amount - min_amount) / Decimal(max_amount)
    if spread > RING_AMOUNT_TOLERANCE_FRACTION:
        return False

    counterparties = {c.counterparty_id for c in run}
    if len(counterparties) > RING_MAX_COUNTERPARTIES:
        return False

    transaction_types = {c.transaction.transaction_type for c in run}
    if len(transaction_types) < 2:
        return False

    run_counts = Counter(c.counterparty_id for c in run)
    return all(counterparty_totals[cp] == run_counts[cp] for cp in counterparties)
