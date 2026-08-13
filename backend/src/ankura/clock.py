"""The only permitted source of "now" in this codebase.

Implemented in Phase 1 Step 10 (as-of time discipline): a Clock protocol with
SystemClock and FrozenClock (tests) implementations, injected via FastAPI
dependency. `datetime.now()` / `utcnow()` / `date.today()` / `time.time()`
are banned everywhere outside this module — see backend/CLAUDE.md.
"""
