"""Idempotency key model.

Implemented in Phase 1 Step 6 (table + RLS) — the behaviour (fingerprint
comparison, replay, conflict handling) lands in Step 9. Row Level Security
applies in full: unlike tenants/api_keys, idempotency lookups always
happen AFTER tenant context is already resolved (auth via api_keys runs
first), so there is no bootstrap circularity here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ankura.db.base import Base
from ankura.db.models.tenant import Tenant


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_idempotency_keys_tenant_key"),
        Index("ix_idempotency_keys_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(Tenant.id), nullable=False)

    key: Mapped[str] = mapped_column(String(256), nullable=False)
    """The raw Idempotency-Key header value."""
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    """Hash of the request body — a replay with the same key but a
    different body is a conflict, not a replay. See phase1.txt Step 9."""

    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
