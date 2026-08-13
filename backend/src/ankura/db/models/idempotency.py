"""Idempotency key model.

Implemented in Phase 1 Step 6 (table) and Step 9 (behaviour). Columns per
phase1.txt Step 6: id, tenant_id, key, request_fingerprint, response_status,
response_body, created_at, expires_at. UNIQUE (tenant_id, key). Written in
the same transaction as the entity it protects — see phase1.txt Step 9.
"""
