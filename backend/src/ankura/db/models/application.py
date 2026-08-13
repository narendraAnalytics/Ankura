"""Application model.

Implemented in Phase 1 Step 6. Columns per phase1.txt Step 6: id, tenant_id,
borrower_id, external_ref (LOS id), requested_amount_paise, tenure_months,
purpose, status, as_of, received_at, created_at, updated_at.
UNIQUE (tenant_id, external_ref). Status enum lives in
contracts/application.py (ApplicationStatus) and is shared with this model.
"""
