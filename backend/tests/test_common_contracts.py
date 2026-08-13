"""contracts/common.py: MoneyPaise, AsOf, EntityType, LoanPurpose.
Implemented in Phase 1 Step 5.

Bare `Annotated` types aren't validated on their own — TypeAdapter is the
idiomatic Pydantic v2 way to exercise one outside a full model.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from ankura.contracts.common import AsOf, EntityType, LoanPurpose, MoneyPaise

money_adapter: TypeAdapter[int] = TypeAdapter(MoneyPaise)
asof_adapter: TypeAdapter[datetime] = TypeAdapter(AsOf)


def test_money_paise_accepts_non_negative_int() -> None:
    assert money_adapter.validate_python(0) == 0
    assert money_adapter.validate_python(500_000_00) == 500_000_00


def test_money_paise_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        money_adapter.validate_python(-1)


def test_asof_accepts_utc_datetime() -> None:
    dt = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)
    assert asof_adapter.validate_python(dt) == dt


def test_asof_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        asof_adapter.validate_python(datetime(2026, 8, 13, 12, 0, 0))


def test_asof_rejects_non_utc_aware_datetime() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    with pytest.raises(ValidationError, match="must be UTC"):
        asof_adapter.validate_python(datetime(2026, 8, 13, 12, 0, 0, tzinfo=ist))


def test_entity_type_has_exactly_four_members() -> None:
    assert {e.value for e in EntityType} == {
        "PROPRIETORSHIP",
        "PARTNERSHIP",
        "LLP",
        "PVT_LTD",
    }


def test_loan_purpose_members_are_all_working_capital_shaped() -> None:
    # No term-loan/invoice-finance-sounding members — v1 scope guard (D4).
    forbidden_substrings = ("TERM_LOAN", "INVOICE_DISCOUNT", "VEHICLE", "HOME", "PERSONAL")
    for purpose in LoanPurpose:
        assert not any(bad in purpose.value for bad in forbidden_substrings)
