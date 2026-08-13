"""ApplicationIn / ApplicationOut / ApplicationStatus.
Implemented in Phase 1 Step 5.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ankura.contracts.application import (
    MAX_TENURE_MONTHS,
    MAX_TICKET_PAISE,
    MIN_TENURE_MONTHS,
    MIN_TICKET_PAISE,
    PHASE_1_LEGAL_STATUSES,
    ApplicationIn,
    ApplicationOut,
    ApplicationStatus,
)
from ankura.contracts.common import EntityType, LoanPurpose

VALID_PAN = "AAPFU0939F"
VALID_GSTIN = "27AAPFU0939F1ZV"

BASE_KWARGS = dict(
    external_ref="LOS-REF-0001",
    borrower_pan=VALID_PAN,
    borrower_gstin=VALID_GSTIN,
    entity_type=EntityType.PROPRIETORSHIP,
    legal_name="Sri Lakshmi Textiles",
    requested_amount_paise=500_000_00,
    tenure_months=18,
    purpose=LoanPurpose.INVENTORY_PURCHASE,
)


def test_valid_application_in_constructs() -> None:
    app = ApplicationIn(**BASE_KWARGS)
    assert app.borrower_udyam is None
    assert app.as_of is None


def test_application_in_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ApplicationIn(**{**BASE_KWARGS, "not_a_real_field": 1})


def test_application_in_requires_gstin() -> None:
    kwargs = dict(BASE_KWARGS)
    del kwargs["borrower_gstin"]
    with pytest.raises(ValidationError):
        ApplicationIn(**kwargs)


@pytest.mark.parametrize(
    "amount",
    [MIN_TICKET_PAISE - 1, MAX_TICKET_PAISE + 1, -1],
)
def test_application_in_rejects_amount_outside_ticket_band(amount: int) -> None:
    with pytest.raises(ValidationError):
        ApplicationIn(**{**BASE_KWARGS, "requested_amount_paise": amount})


@pytest.mark.parametrize("amount", [MIN_TICKET_PAISE, MAX_TICKET_PAISE])
def test_application_in_accepts_ticket_band_boundaries(amount: int) -> None:
    app = ApplicationIn(**{**BASE_KWARGS, "requested_amount_paise": amount})
    assert app.requested_amount_paise == amount


@pytest.mark.parametrize("tenure", [MIN_TENURE_MONTHS - 1, MAX_TENURE_MONTHS + 1, 0])
def test_application_in_rejects_tenure_outside_band(tenure: int) -> None:
    with pytest.raises(ValidationError):
        ApplicationIn(**{**BASE_KWARGS, "tenure_months": tenure})


@pytest.mark.parametrize("tenure", [MIN_TENURE_MONTHS, MAX_TENURE_MONTHS])
def test_application_in_accepts_tenure_band_boundaries(tenure: int) -> None:
    app = ApplicationIn(**{**BASE_KWARGS, "tenure_months": tenure})
    assert app.tenure_months == tenure


def test_application_in_accepts_optional_udyam() -> None:
    app = ApplicationIn(**{**BASE_KWARGS, "borrower_udyam": "UDYAM-MH-19-0000001"})
    assert app.borrower_udyam == "UDYAM-MH-19-0000001"


def test_application_in_rejects_invalid_pan() -> None:
    with pytest.raises(ValidationError):
        ApplicationIn(**{**BASE_KWARGS, "borrower_pan": "TOOSHORT"})


def test_application_out_requires_as_of_and_received_at() -> None:
    out = ApplicationOut(
        id=uuid4(),
        tenant_id=uuid4(),
        external_ref="LOS-REF-0001",
        status=ApplicationStatus.RECEIVED,
        borrower_pan=VALID_PAN,
        borrower_gstin=VALID_GSTIN,
        borrower_udyam=None,
        entity_type=EntityType.PROPRIETORSHIP,
        legal_name="Sri Lakshmi Textiles",
        requested_amount_paise=500_000_00,
        tenure_months=18,
        purpose=LoanPurpose.INVENTORY_PURCHASE,
        as_of=datetime(2026, 8, 13, tzinfo=UTC),
        received_at=datetime(2026, 8, 13, tzinfo=UTC),
    )
    assert out.status == ApplicationStatus.RECEIVED


def test_phase_1_legal_statuses_is_exactly_the_documented_three() -> None:
    assert {
        ApplicationStatus.RECEIVED,
        ApplicationStatus.VALIDATED,
        ApplicationStatus.REJECTED_INTAKE,
    } == PHASE_1_LEGAL_STATUSES


def test_application_status_has_full_lifecycle_declared() -> None:
    # Guards against someone quietly deleting a not-yet-used status.
    expected = {
        "RECEIVED",
        "VALIDATED",
        "REJECTED_INTAKE",
        "CONSENT_PENDING",
        "CONSENT_GRANTED",
        "CONSENT_REJECTED",
        "DATA_FETCHING",
        "DATA_READY",
        "UNDERWRITING_IN_PROGRESS",
        "PENDING_HUMAN_REVIEW",
        "DECIDED",
        "WITHDRAWN",
        "EXPIRED",
    }
    assert {s.value for s in ApplicationStatus} == expected
