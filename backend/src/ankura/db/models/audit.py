"""Audit event model — append-only, hash-chained.

Implemented in Phase 1 Step 6 (table + RLS) — the writer service and hash
chain function itself land in Step 11. Row Level Security applies in full.
No UPDATE grant to the app role at the DATABASE level (Step 6 completion
notes) — append-only is enforced by the database, not just by omission in
application code.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ankura.db.base import Base
from ankura.db.models.tenant import Tenant

_ACTOR_TYPE_CHECK_SQL = "actor_type IN ('api_key', 'system')"
"""Small, deliberately minimal set for Phase 1 — extend via a proper
migration (not a silent app-level assumption) when Step 4/human-review
introduces a 'human_reviewer' actor in a later milestone."""


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(_ACTOR_TYPE_CHECK_SQL, name="ck_audit_events_actor_type"),
        Index("ix_audit_events_tenant_id", "tenant_id"),
        Index("ix_audit_events_tenant_id_entity", "tenant_id", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(Tenant.id), nullable=False)

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128))

    payload_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    """No PII, no PAN/GSTIN/mobile/account values — references only. See
    backend/CLAUDE.md and final architecture.txt §6.2."""

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    prev_hash: Mapped[str | None] = mapped_column(String(64))
    """NULL only for the very first event in a tenant's chain."""
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
