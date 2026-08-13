"""Audit event model — append-only, hash-chained.

Implemented in Phase 1 Step 6 (table) and Step 11 (hash chain + writer
service). Columns per phase1.txt Step 6: id, tenant_id, entity_type,
entity_id, event_type, actor_type, actor_id, payload_json, occurred_at,
recorded_at, prev_hash, event_hash. No UPDATE/DELETE grant to the app role —
enforced at the database role level, not just by omission in the ORM.
"""
