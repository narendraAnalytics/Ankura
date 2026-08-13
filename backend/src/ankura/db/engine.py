"""Async SQLAlchemy engine, session factory, and the RLS tenant-context hook.

Implemented in Phase 1 Step 4 (database connection). Two connection strings
are required — DATABASE_URL (pooled, app role) and DATABASE_DIRECT_URL
(unpooled, migrations only) — see final architecture.txt §14.3. The session
dependency must issue `SET LOCAL app.tenant_id = …` per transaction; see
§14.4 for why this cannot be a plain `SET`.
"""
