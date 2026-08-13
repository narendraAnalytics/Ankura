"""row level security — enable/force RLS + tenant_isolation policy on the
four genuinely tenant-scoped tables (borrowers, applications, audit_events,
idempotency_keys); tighten default-privilege grants on the two bootstrap
tables (tenants, api_keys) down to SELECT-only, and drop UPDATE on
audit_events (append-only). Hand-written raw SQL — Alembic does not
autogenerate any of this. Mirrors exactly what's live in Neon's
"production" branch from Phase 1 Step 6 (grants/policy read back live and
pinned here, not re-derived from memory) — see final architecture.txt
§14.4 and db/base.py's module docstring for the RLS scope decision.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-13 16:30:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RLS_TABLES = ("borrowers", "applications", "audit_events", "idempotency_keys")

# NULLIF(..., '')::uuid, not bare current_setting(...) — see
# final architecture.txt §14.4 for the live bug this avoids: a custom GUC
# that's ever been touched in a session defaults to '' afterward, not
# NULL/unset, so a reused connection with no tenant context set yet would
# otherwise raise a raw DataError on the ::uuid cast instead of cleanly
# returning zero rows.
_TENANT_POLICY_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    """Upgrade schema."""
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_TENANT_POLICY_EXPR}) WITH CHECK ({_TENANT_POLICY_EXPR})"
        )

    # audit_events is append-only at the database level, not just by
    # omission in application code — REVOKE UPDATE specifically; DELETE was
    # never granted to any table (Step 4's default privileges only ever
    # included SELECT/INSERT/UPDATE), so no DELETE revoke is needed here.
    op.execute("REVOKE UPDATE ON audit_events FROM ankura_app")

    # tenants/api_keys are bootstrap/auth tables, deliberately NOT
    # RLS-scoped (see db/base.py) — provisioning a tenant or issuing/
    # revoking an API key is an admin/operator action, never something the
    # running app does to itself. Step 4's default privileges grant
    # SELECT/INSERT/UPDATE to every new table; narrow these two back down
    # to SELECT-only.
    op.execute("REVOKE INSERT, UPDATE ON tenants FROM ankura_app")
    op.execute("REVOKE INSERT, UPDATE ON api_keys FROM ankura_app")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("GRANT INSERT, UPDATE ON api_keys TO ankura_app")
    op.execute("GRANT INSERT, UPDATE ON tenants TO ankura_app")
    op.execute("GRANT UPDATE ON audit_events TO ankura_app")

    for table in _RLS_TABLES:
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
