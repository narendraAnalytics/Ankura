"""Borrower model.

Implemented in Phase 1 Step 6. Columns per phase1.txt Step 6: id, tenant_id,
entity_type, legal_name, pan, gstin, udyam, primary_mobile_hash, created_at,
updated_at. UNIQUE (tenant_id, pan) and (tenant_id, gstin). RLS applies —
tenant_id is NOT NULL and the leading column of every index.
"""
