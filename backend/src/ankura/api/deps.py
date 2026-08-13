"""Shared FastAPI dependencies: auth, tenant resolution, DB session, clock,
as-of timestamp.

Implemented in Phase 1 Step 8. Tenant API key auth resolves tenant_id and
sets it on the DB session immediately (before any query runs) — see
phase1.txt Step 8 and final architecture.txt §14.4. Firebase Auth is NOT
wired here; that's for the human-facing consoles starting Phase 4.
"""
