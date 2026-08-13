"""Application model.

Implemented in Phase 1 Step 6. Row Level Security applies in full — see
db/base.py's module docstring. Status/purpose enums are shared with
contracts/application.py — the CHECK constraints below are generated
from those same Python enums so the DB and the contract can never
silently drift apart.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ankura.contracts.application import ApplicationStatus
from ankura.contracts.common import LoanPurpose
from ankura.db.base import Base, TimestampMixin
from ankura.db.models.borrower import Borrower
from ankura.db.models.tenant import Tenant

_PURPOSE_CHECK_SQL = "purpose IN (" + ", ".join(f"'{p.value}'" for p in LoanPurpose) + ")"
_STATUS_CHECK_SQL = "status IN (" + ", ".join(f"'{s.value}'" for s in ApplicationStatus) + ")"


class Application(Base, TimestampMixin):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_ref", name="uq_applications_tenant_external_ref"),
        CheckConstraint(_PURPOSE_CHECK_SQL, name="ck_applications_purpose"),
        CheckConstraint(_STATUS_CHECK_SQL, name="ck_applications_status"),
        CheckConstraint("requested_amount_paise >= 0", name="ck_applications_amount_non_negative"),
        CheckConstraint("tenure_months > 0", name="ck_applications_tenure_positive"),
        Index("ix_applications_tenant_id", "tenant_id"),
        Index("ix_applications_tenant_id_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(Tenant.id), nullable=False)
    borrower_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(Borrower.id), nullable=False)

    external_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tenure_months: Mapped[int] = mapped_column(Integer, nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ApplicationStatus.RECEIVED.value
    )

    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """Business time — see contracts/common.py AsOf. Distinct from
    received_at (wall-clock) and TimestampMixin's created_at."""

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
