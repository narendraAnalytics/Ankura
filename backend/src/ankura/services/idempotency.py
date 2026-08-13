"""Idempotency-Key handling: fingerprint, replay, conflict, concurrent-request
resolution.

Implemented in Phase 1 Step 9. The idempotency record and the entity it
protects are written in the same transaction — see phase1.txt Step 9.
"""
