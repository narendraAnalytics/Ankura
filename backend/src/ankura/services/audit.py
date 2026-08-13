"""Append-only audit event writer + hash-chain verification.

Implemented in Phase 1 Step 11. No update/delete path exists in this module
by design. Canonical JSON serialisation must be stable (sorted keys, fixed
separators) or the hash chain breaks across a Python version bump — see
phase1.txt Step 11. No PII in payload_json — store references, not values.
"""
