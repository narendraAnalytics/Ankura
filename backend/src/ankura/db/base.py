"""Declarative base and shared model mixins.

Implemented in Phase 1 Step 6, alongside the models in db/models/.

RLS SCOPE DECISION (researched before writing any model — see phase1.txt
Step 6 for the search notes): `tenants` and `api_keys` do NOT get Row
Level Security, even though api_keys has a tenant_id column. Both are
"bootstrap" tables used to ESTABLISH tenant identity, not to operate
within it — RLS-gating the table that resolves "who is this caller" on a
tenant_id you don't have yet is circular (current_setting('app.tenant_id')
is unset at exactly the moment you're trying to find out what it should
be). This is the standard, documented pattern: a separate lookup mechanism
runs before RLS policies apply, then sets tenant context for everything
after. api_keys' real security boundary is the peppered hash comparison
(`WHERE key_hash = :computed_hash`), not row-level tenant secrecy — seeing
a hashed row leaks nothing exploitable. Both tables get SELECT-only grants
for the app role instead (see Step 6 completion notes in phase1.txt):
provisioning tenants and issuing/revoking API keys are admin/operator
actions, never something the running app does to itself.

RLS applies in full (ENABLE + FORCE, tenant_id leading index, policy
against current_setting('app.tenant_id')) to the four genuinely
tenant-SCOPED operational tables: borrowers, applications, audit_events,
idempotency_keys. See final architecture.txt §14.4.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """created_at / updated_at, both DB-defaulted and timezone-aware.
    Not a substitute for as_of/recorded_at business-time discipline
    (Step 10) — these are ordinary bookkeeping columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
