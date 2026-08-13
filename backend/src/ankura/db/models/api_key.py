"""Tenant API key model.

Implemented in Phase 1 Step 6. NOT Row Level Security-scoped — see
db/base.py's module docstring for why (bootstrap/auth table). App role has
SELECT only; issuing/revoking a key is an admin/operator action, and
key_hash's peppered comparison is the real security boundary, not RLS.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from ankura.db.base import Base
from ankura.db.models.tenant import Tenant


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (Index("ix_api_keys_tenant_id", "tenant_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(Tenant.id), nullable=False)

    key_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    """Peppered hash of the raw API key. Raw keys are never stored."""

    label: Mapped[str] = mapped_column(String(128), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
