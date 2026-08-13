"""POST/GET /v1/applications routes.

Implemented in Phase 1 Step 8: create (idempotent — Step 9), fetch one, and
cursor-paginated list with status/date filters. Intake validation here is
hygiene (identifier format, ticket band, duplicate external_ref) — it is
NOT credit policy. See phase1.txt Step 8.
"""
