"""Standard error envelope and exception handlers.

Implemented in Phase 1 Step 8. Single envelope shape:
{error: {code, message, details[], request_id}}. Every rejection carries a
machine-readable `code` — this vocabulary is what Phase 3's Decision Record
reason codes extend, so treat it as a real contract, not a convenience.
"""
