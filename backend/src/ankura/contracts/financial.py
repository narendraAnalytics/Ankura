"""Canonical financial data shapes — defined now, unused until Phase 7.

Implemented in Phase 1 Step 5. Shapes only — no provider client calls this
yet, and no feature-engine logic reads it yet (that's Phase 2). This is the
target contract Phase 2's feature engine will read and what Phase 7's real
providers (Setu AA, GST, bureau) must normalize into, regardless of source.
See ankuraworkflow.txt §5.2 (provider abstraction) and §6.2 (data classes).

Deliberately moderate detail: enough structure to be a real target for
Phase 2/7, not a guess at every field a bank statement or bureau report
could ever contain. Expect this to grow when Phase 2 actually consumes it.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ankura.contracts.common import PAN, AsOf, MoneyPaise


class TransactionType(StrEnum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class BankTransaction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    transaction_date: date
    transaction_type: TransactionType
    description: str = Field(max_length=512)
    amount_paise: MoneyPaise
    balance_after_paise: MoneyPaise | None = None
    bounced: bool = False
    """True for a returned/bounced instrument — direct input to the
    bounce_ratio formula (final architecture.txt §14.2)."""

    counterparty_id: str | None = Field(default=None, max_length=128)
    """Normalized counterparty identifier, assigned by the PROVIDER layer
    (Setu AA / mock) from whatever raw payee/payer data it receives — never
    parsed out of `description` at feature time. String-parsing provider
    text in the feature engine is exactly the coupling the §5.2 provider
    abstraction exists to prevent. None when the transaction has no
    identifiable counterparty (e.g. a cash deposit/withdrawal, or the
    provider genuinely could not resolve one) — customer/supplier
    concentration formulas only ever sum transactions that HAVE this set."""

    is_cash: bool = False
    """True for a cash deposit or cash withdrawal, as opposed to a
    transfer/electronic credit or debit. A provider-level classification
    from the source instrument type, not inferred later — needed by
    cash_deposit_ratio (final architecture.txt §14.2), which must not
    conflate "a transfer that happens to be unlabeled" with "a cash
    deposit"."""

    is_debt_service: bool = False
    """True for a debit that is loan/EMI repayment (existing debt service),
    as opposed to any other kind of outflow. Feeds obligation_ratio's
    existing_emi_outflow and dscr's total_debt_service inputs (final
    architecture.txt §14.2) — the feature engine sums flagged debits rather
    than re-deriving "which debits look like an EMI" from description text."""


class BankAccountSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(min_length=1, max_length=64)
    """Provider-issued or masked account reference — never a raw account
    number (final architecture.txt §6.2/§14.5: raw payloads are short
    retention and never land in a durable, widely-queried table)."""

    bank_name: str = Field(min_length=1, max_length=128)
    statement_period_start: date
    statement_period_end: date
    opening_balance_paise: MoneyPaise
    closing_balance_paise: MoneyPaise
    transactions: list[BankTransaction] = Field(default_factory=list)


class GstReturnType(StrEnum):
    GSTR_1 = "GSTR_1"
    GSTR_3B = "GSTR_3B"


class GstReturnRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    return_type: GstReturnType
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    """Filing period as YYYY-MM."""

    filed_on: date | None = None
    """None means not yet filed for this period — a filing-regularity
    signal in its own right, not missing data to be silently dropped."""

    turnover_paise: MoneyPaise
    tax_paid_paise: MoneyPaise | None = None


class BureauSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bureau_name: str = Field(min_length=1, max_length=64)
    """e.g. "CIBIL MSME Rank", "CRIF", "Experian" — see final
    architecture.txt §8.2 Change 2: bureau is in the data model from the
    start even though the real integration is Phase 7."""

    score: int
    report_date: date
    existing_obligations_paise: MoneyPaise | None = None
    enquiries_last_6_months: int | None = Field(default=None, ge=0)


class DataQuality(BaseModel):
    """Coverage/confidence metadata travelling WITH the data it describes.
    A feature computed from 2 months of statements is not the same object
    as one computed from 12 — final architecture.txt §5 Stage D6."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    coverage_months: int = Field(ge=0)
    source_count: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)


class CanonicalFinancialData(BaseModel):
    """The object Phase 2's feature engine reads. Every provider (mock,
    Setu AA, future ULI) must normalize into exactly this shape — nothing
    downstream ever reads a provider payload directly (§5.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    application_id: UUID
    borrower_pan: PAN
    bank_accounts: list[BankAccountSummary] = Field(default_factory=list)
    gst_returns: list[GstReturnRecord] = Field(default_factory=list)
    bureau: BureauSummary | None = None
    data_quality: DataQuality
    as_of: AsOf
