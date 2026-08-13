"""Shared canonical types: Money, PAN, GSTIN, Udyam, AsOf, shared enums.

Implemented in Phase 1 Step 5 — see phase1.txt Step 5 for the checklist.
Written BEFORE any database table, per final architecture.txt §14.1.

Every identifier type here delegates its actual validation to
validators/identifiers.py and only wraps it as a reusable Pydantic
Annotated type — the checksum/structure logic lives in exactly one place.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, Field

from ankura.validators.identifiers import validate_gstin, validate_pan, validate_udyam

# --- Identifiers -----------------------------------------------------------

PAN = Annotated[str, AfterValidator(validate_pan)]
"""10-character Indian PAN. Structure + entity-type letter validated; the
10th character IS a checksum but the algorithm is undisclosed by the
Income Tax Department, so only structural validation is possible."""

GSTIN = Annotated[str, AfterValidator(validate_gstin)]
"""15-character Indian GSTIN. Structure, active state code, embedded-PAN
structure, and the Mod-36 checksum digit are all validated."""

UdyamRegistrationNumber = Annotated[str, AfterValidator(validate_udyam)]
"""19-character Udyam registration number: UDYAM-XX-00-0000000."""


# --- Money -------------------------------------------------------------

MoneyPaise = Annotated[
    int,
    Field(
        ge=0,
        description=(
            "Amount in paise (1 INR = 100 paise). Indian Rupees ONLY — "
            "there is no currency field anywhere in this system and none "
            "is planned; multi-currency is explicitly out of scope. "
            "Never a float — see backend/CLAUDE.md."
        ),
    ),
]


# --- Time ----------------------------------------------------------------


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError(
            "must be timezone-aware — naive datetimes are not accepted (as_of "
            "discipline, see final architecture.txt §14 / phase1.txt Step 10)"
        )
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"must be UTC (offset 0), got offset {value.utcoffset()}")
    return value


AsOf = Annotated[datetime, AfterValidator(_require_utc)]
"""Timezone-aware UTC datetime representing BUSINESS time — "the time the
decision reasons about". Required wherever used; this type has no default
and no caller may give it one. See backend/CLAUDE.md clock discipline."""

UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
"""Timezone-aware UTC datetime for WALL-CLOCK timestamps (recorded_at,
created_at, updated_at, ...) — identical validation to AsOf, named
separately so field names stay self-documenting about which kind of time
they hold. See phase1.txt Step 10: as_of vs recorded_at are never the
same field."""


# --- Shared enums ----------------------------------------------------------


class EntityType(StrEnum):
    """Borrower's legal entity type. Exactly these four for MSME
    working-capital v1 — see final architecture.txt recommendations table
    and phase1.txt Step 0 D4."""

    PROPRIETORSHIP = "PROPRIETORSHIP"
    PARTNERSHIP = "PARTNERSHIP"
    LLP = "LLP"
    PVT_LTD = "PVT_LTD"


class LoanPurpose(StrEnum):
    """Working-capital loan purposes only — v1 scope is MSME working
    capital exclusively (phase1.txt Step 0 D4). Term loans, invoice
    finance, and other product lines are out of scope until a later
    milestone; do not add non-working-capital purposes here without
    revisiting D4."""

    INVENTORY_PURCHASE = "INVENTORY_PURCHASE"
    RAW_MATERIAL_PURCHASE = "RAW_MATERIAL_PURCHASE"
    RECEIVABLES_FINANCING = "RECEIVABLES_FINANCING"
    OPERATING_EXPENSES = "OPERATING_EXPENSES"
    SEASONAL_WORKING_CAPITAL = "SEASONAL_WORKING_CAPITAL"
    BUSINESS_EXPANSION = "BUSINESS_EXPANSION"
    OTHER_WORKING_CAPITAL = "OTHER_WORKING_CAPITAL"
