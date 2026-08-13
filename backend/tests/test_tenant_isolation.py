"""Multi-tenant Row Level Security isolation test. Implemented in Phase 1
Step 6.

This test must still pass with the ORM's own `tenant_id` filter temporarily
removed — that is what proves Postgres RLS, not application code, is the
actual isolation boundary. See phase1.txt Step 6 PROVE IT and
final architecture.txt §14.4. Non-negotiable per phase1.txt DEFINITION OF DONE.
"""
