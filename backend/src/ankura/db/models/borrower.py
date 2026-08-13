"""Borrower model.

Implemented in Phase 1 Step 6. Row Level Security applies in full — see
db/base.py's module docstring.

primary_mobile_hash is nullable: contracts/application.py's ApplicationIn
(Step 5) does not currently collect a mobile number, so this column isn't
populated by the present intake flow. Reserved for a future KYC/mobile-
verification step rather than retrofitting Step 5's already-tested
contract mid-Step-6 — flagged here so it isn't mistaken for an oversight.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ankura.contracts.common import EntityType
from ankura.db.base import Base, TimestampMixin
from ankura.db.models.tenant import Tenant

_ENTITY_TYPE_CHECK_SQL = "entity_type IN (" + ", ".join(f"'{e.value}'" for e in EntityType) + ")"


class Borrower(Base, TimestampMixin):
    __tablename__ = "borrowers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "pan", name="uq_borrowers_tenant_pan"),
        UniqueConstraint("tenant_id", "gstin", name="uq_borrowers_tenant_gstin"),
        CheckConstraint(_ENTITY_TYPE_CHECK_SQL, name="ck_borrowers_entity_type"),
        CheckConstraint("length(pan) = 10", name="ck_borrowers_pan_length"),
        CheckConstraint("length(gstin) = 15", name="ck_borrowers_gstin_length"),
        # tenant_id MUST be the leading column of every index on a
        # tenant-scoped table (final architecture.txt §14.4) — the unique
        # constraints above already put it first; this index covers plain
        # tenant-scoped lookups/lists that don't hit the unique constraints.
        Index("ix_borrowers_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(Tenant.id), nullable=False)

    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(256), nullable=False)
    pan: Mapped[str] = mapped_column(String(10), nullable=False)
    gstin: Mapped[str] = mapped_column(String(15), nullable=False)
    udyam: Mapped[str | None] = mapped_column(String(19))
    primary_mobile_hash: Mapped[str | None] = mapped_column(String(128))
