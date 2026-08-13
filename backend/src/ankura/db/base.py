"""Declarative base and shared model mixins.

Implemented in Phase 1 Step 6 (multi-tenant schema + row level security),
alongside the models in db/models/. Any shared mixin (e.g. tenant_id column,
created_at/updated_at timestamps) belongs here so every model inherits the
same RLS-ready shape.
"""
