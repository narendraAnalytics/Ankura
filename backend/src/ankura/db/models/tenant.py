"""Tenant model.

Implemented in Phase 1 Step 6. NOT Row Level Security-scoped — see
db/base.py's module docstring for why. App role (ankura_app) has SELECT
only; provisioning a tenant is an admin/operator action.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ankura.db.base import Base, TimestampMixin

_VALID_STATUSES = ("ACTIVE", "SUSPENDED", "OFFBOARDED")
_STATUS_CHECK_SQL = "status IN (" + ", ".join(f"'{s}'" for s in _VALID_STATUSES) + ")"


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(_STATUS_CHECK_SQL, name="ck_tenants_status"),
        CheckConstraint("retention_days_raw > 0", name="ck_tenants_retention_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    legal_name: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    residency_region: Mapped[str] = mapped_column(String(32), nullable=False)
    """e.g. "asia-south1" — mirrors the residency guard in config.py §13,
    at the tenant record level rather than only the deployment level."""
    retention_days_raw: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    """Raw financial payload retention window, per tenant. Default 7 per
    ankuraworkflow.txt §6.2."""
