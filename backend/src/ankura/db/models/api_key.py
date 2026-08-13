"""Tenant API key model.

Implemented in Phase 1 Step 6 (table) and Step 8 (auth). Columns per
phase1.txt Step 6: id, tenant_id, key_hash (peppered), label, last_used_at,
revoked_at, created_at. Compared constant-time against the peppered hash;
raw keys are never stored.
"""
