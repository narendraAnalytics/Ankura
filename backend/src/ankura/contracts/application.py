"""Application intake contracts: ApplicationIn, ApplicationOut,
ApplicationStatus.

Implemented in Phase 1 Step 5.

Ticket-size and tenure bands (phase1.txt Step 0): "Rs 2L / 5L / 10L / 15L /
25L" and "6-36 months" are read here as a MIN-MAX RANGE (₹2,00,000 to
₹25,00,000; 6 to 36 months), not five discrete allowed amounts — a fixed
five-tier ticket size would be unusual for MSME working-capital lending and
nothing in Step 0's answers said "discrete tiers only". Flagging this
reading explicitly since the slash-separated list is genuinely ambiguous;
revisit here if that assumption turns out wrong.

GSTIN is REQUIRED on ApplicationIn, not optional: v1's underwriting
approach is GST-turnover-centric (ankuraworkflow.txt §5.2/§6), so a
non-GST-registered business is out of v1 scope by design, not an oversight.
Udyam is optional — useful corroborating evidence, not load-bearing.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ankura.contracts.common import (
    GSTIN,
    PAN,
    AsOf,
    EntityType,
    LoanPurpose,
    MoneyPaise,
    UdyamRegistrationNumber,
    UtcDatetime,
)

MIN_TICKET_PAISE = 200_000_00  # Rs 2,00,000
MAX_TICKET_PAISE = 2_500_000_00  # Rs 25,00,000
MIN_TENURE_MONTHS = 6
MAX_TENURE_MONTHS = 36

# NOTE: constraints must be layered via NESTED Annotated (Annotated[MoneyPaise,
# Field(...)]), not by assigning `field: MoneyPaise = Field(ge=..., le=...)`
# at the attribute site — the latter silently drops MoneyPaise's own
# embedded constraints in Pydantic v2 rather than merging with them
# (verified while writing this file: `= Field(ge=MIN_TICKET_PAISE, ...)`
# let amounts below MIN_TICKET_PAISE through uncaught).
TicketAmountPaise = Annotated[MoneyPaise, Field(ge=MIN_TICKET_PAISE, le=MAX_TICKET_PAISE)]
TenureMonths = Annotated[int, Field(ge=MIN_TENURE_MONTHS, le=MAX_TENURE_MONTHS)]


class ApplicationStatus(StrEnum):
    """Full application lifecycle, declared up front per final
    architecture.txt §14.1 even though Phase 1 only legally transitions
    through the first three. Enforcing legal transitions is a Step 8
    service concern, not this enum's job — PHASE_1_LEGAL below is just a
    reference constant for that later logic."""

    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    REJECTED_INTAKE = "REJECTED_INTAKE"
    CONSENT_PENDING = "CONSENT_PENDING"
    CONSENT_GRANTED = "CONSENT_GRANTED"
    CONSENT_REJECTED = "CONSENT_REJECTED"
    DATA_FETCHING = "DATA_FETCHING"
    DATA_READY = "DATA_READY"
    UNDERWRITING_IN_PROGRESS = "UNDERWRITING_IN_PROGRESS"
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    DECIDED = "DECIDED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


PHASE_1_LEGAL_STATUSES = frozenset(
    {
        ApplicationStatus.RECEIVED,
        ApplicationStatus.VALIDATED,
        ApplicationStatus.REJECTED_INTAKE,
    }
)


class ApplicationIn(BaseModel):
    """External LOS-facing request contract. Intake validation here is
    hygiene (identifier format, ticket/tenure band, required fields) — it
    is NOT credit policy. See backend/CLAUDE.md."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    external_ref: str = Field(min_length=1, max_length=128)
    """The lender's own identifier for this application, for idempotent
    correlation on their side. Unique per tenant — enforced at the DB
    layer (Step 6), not here."""

    borrower_pan: PAN
    borrower_gstin: GSTIN
    borrower_udyam: UdyamRegistrationNumber | None = None

    entity_type: EntityType
    legal_name: str = Field(min_length=1, max_length=256)

    requested_amount_paise: TicketAmountPaise
    tenure_months: TenureMonths
    purpose: LoanPurpose

    as_of: AsOf | None = None
    """Business time this application concerns. Optional here: callers
    replaying/backfilling supply it explicitly; a live intake omits it and
    Step 8's API layer stamps it once, at the edge, from Clock (Step 10).
    Never re-derived deeper in the stack — see backend/CLAUDE.md."""


class ApplicationOut(BaseModel):
    """Response contract. Every field is server-resolved — by the time
    this is returned, as_of has always been stamped one way or another."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    tenant_id: UUID
    external_ref: str
    status: ApplicationStatus

    borrower_pan: PAN
    borrower_gstin: GSTIN
    borrower_udyam: UdyamRegistrationNumber | None
    entity_type: EntityType
    legal_name: str

    requested_amount_paise: TicketAmountPaise
    tenure_months: TenureMonths
    purpose: LoanPurpose

    as_of: AsOf
    received_at: UtcDatetime
    """Wall-clock time the row was written — distinct from as_of. See
    contracts/common.py's UtcDatetime docstring."""
