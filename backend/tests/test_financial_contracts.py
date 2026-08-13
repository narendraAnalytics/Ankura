"""Canonical financial data contract shapes. Implemented in Phase 1 Step 5.

Shapes only — no logic to test beyond "the shape is constructible and
enforces its own constraints". Phase 2 will exercise these for real.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ankura.contracts.financial import (
    BankAccountSummary,
    BankTransaction,
    BureauSummary,
    CanonicalFinancialData,
    DataQuality,
    GstReturnRecord,
    GstReturnType,
    TransactionType,
)


def test_canonical_financial_data_constructs_with_full_shape() -> None:
    data = CanonicalFinancialData(
        application_id=uuid4(),
        borrower_pan="AAPFU0939F",
        bank_accounts=[
            BankAccountSummary(
                account_id="acc-masked-1234",
                bank_name="Example Bank",
                statement_period_start=date(2026, 1, 1),
                statement_period_end=date(2026, 6, 30),
                opening_balance_paise=100_000_00,
                closing_balance_paise=150_000_00,
                transactions=[
                    BankTransaction(
                        transaction_date=date(2026, 1, 5),
                        transaction_type=TransactionType.CREDIT,
                        description="ABC DISTRIBUTORS",
                        amount_paise=85_000_00,
                    ),
                    BankTransaction(
                        transaction_date=date(2026, 1, 10),
                        transaction_type=TransactionType.DEBIT,
                        description="EMI",
                        amount_paise=24_000_00,
                        bounced=True,
                    ),
                ],
            )
        ],
        gst_returns=[
            GstReturnRecord(
                return_type=GstReturnType.GSTR_3B,
                period="2026-01",
                filed_on=date(2026, 2, 15),
                turnover_paise=800_000_00,
            )
        ],
        bureau=BureauSummary(
            bureau_name="CIBIL MSME Rank",
            score=650,
            report_date=date(2026, 8, 1),
        ),
        data_quality=DataQuality(coverage_months=6, source_count=2, confidence=0.85),
        as_of=datetime(2026, 8, 13, tzinfo=UTC),
    )
    assert data.bank_accounts[0].transactions[1].bounced is True


def test_gst_return_period_must_be_yyyy_mm() -> None:
    with pytest.raises(ValidationError):
        GstReturnRecord(
            return_type=GstReturnType.GSTR_1,
            period="2026/01",
            turnover_paise=100_00,
        )


def test_gst_return_allows_unfiled_period() -> None:
    record = GstReturnRecord(
        return_type=GstReturnType.GSTR_1,
        period="2026-03",
        filed_on=None,
        turnover_paise=0,
    )
    assert record.filed_on is None


def test_data_quality_confidence_bounded_zero_to_one() -> None:
    with pytest.raises(ValidationError):
        DataQuality(coverage_months=6, source_count=1, confidence=1.5)


def test_extra_fields_forbidden_on_canonical_financial_data() -> None:
    with pytest.raises(ValidationError):
        CanonicalFinancialData(
            application_id=uuid4(),
            borrower_pan="AAPFU0939F",
            data_quality=DataQuality(coverage_months=0, source_count=0, confidence=0.0),
            as_of=datetime(2026, 8, 13, tzinfo=UTC),
            unexpected_field="nope",  # type: ignore[call-arg]
        )
