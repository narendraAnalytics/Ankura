"""Hand-computed expected values, worked out on paper BEFORE this file was
written — same discipline as Phase 1's GSTIN Mod-36 checksum test. Every
§14.2 metric gets at least one worked example plus its zero-denominator
case. See phase2.txt Step 1 PROVE IT.

Worked examples (amounts in paise, computed by hand):

  dscr(20_000_000, 15_000_000)
    = 20,000,000 / 15,000,000 = 1.3333333... -> round HALF_UP 6dp -> 1.333333

  obligation_ratio(5_000_000, 20_000_000)
    = 5,000,000 / 20,000,000 = 0.25 exactly

  bounce_ratio(3, 40)
    = 3 / 40 = 0.075 exactly

  bank_gst_gap(9_000_000, 6_500_000)
    = |9,000,000 - 6,500,000| / 6,500,000 = 2,500,000 / 6,500,000
    = 0.3846153846... -> round HALF_UP 6dp -> 0.384615

  cash_deposit_ratio(1_200_000, 8_000_000)
    = 1,200,000 / 8,000,000 = 0.15 exactly

  customer_concentration(3_200_000, 8_000_000)
    = 3,200,000 / 8,000,000 = 0.4 exactly

  supplier_concentration(2_400_000, 6_000_000)
    = 2,400,000 / 6,000,000 = 0.4 exactly
"""

from __future__ import annotations

from ankura.features.metrics import (
    bank_gst_gap,
    bounce_ratio,
    cash_deposit_ratio,
    customer_concentration,
    dscr,
    obligation_ratio,
    supplier_concentration,
)


def test_dscr_worked_example() -> None:
    assert dscr(20_000_000, 15_000_000) == 1.333333


def test_dscr_zero_debt_service_is_undefined() -> None:
    assert dscr(20_000_000, 0) is None


def test_obligation_ratio_worked_example() -> None:
    assert obligation_ratio(5_000_000, 20_000_000) == 0.25


def test_obligation_ratio_zero_emi_is_a_real_zero() -> None:
    assert obligation_ratio(0, 20_000_000) == 0.0


def test_obligation_ratio_zero_inflow_is_undefined() -> None:
    assert obligation_ratio(5_000_000, 0) is None


def test_bounce_ratio_worked_example() -> None:
    assert bounce_ratio(3, 40) == 0.075


def test_bounce_ratio_zero_bounces_with_instruments_is_a_real_zero() -> None:
    assert bounce_ratio(0, 40) == 0.0


def test_bounce_ratio_no_instruments_presented_is_undefined() -> None:
    assert bounce_ratio(0, 0) is None


def test_bank_gst_gap_worked_example() -> None:
    assert bank_gst_gap(9_000_000, 6_500_000) == 0.384615


def test_bank_gst_gap_bank_below_gst_still_absolute() -> None:
    # |6,500,000 - 9,000,000| / 9,000,000 = 2,500,000 / 9,000,000 = 0.277778
    assert bank_gst_gap(6_500_000, 9_000_000) == 0.277778


def test_bank_gst_gap_zero_gst_turnover_is_undefined() -> None:
    assert bank_gst_gap(9_000_000, 0) is None


def test_cash_deposit_ratio_worked_example() -> None:
    assert cash_deposit_ratio(1_200_000, 8_000_000) == 0.15


def test_cash_deposit_ratio_zero_total_credits_is_undefined() -> None:
    assert cash_deposit_ratio(0, 0) is None


def test_customer_concentration_worked_example() -> None:
    assert customer_concentration(3_200_000, 8_000_000) == 0.4


def test_customer_concentration_single_counterparty_is_one() -> None:
    assert customer_concentration(8_000_000, 8_000_000) == 1.0


def test_customer_concentration_zero_total_credits_is_undefined() -> None:
    assert customer_concentration(0, 0) is None


def test_supplier_concentration_worked_example() -> None:
    assert supplier_concentration(2_400_000, 6_000_000) == 0.4


def test_supplier_concentration_zero_total_debits_is_undefined() -> None:
    assert supplier_concentration(0, 0) is None
