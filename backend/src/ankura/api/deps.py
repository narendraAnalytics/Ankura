"""Shared FastAPI dependencies: auth, tenant resolution, DB session, clock.

Tenant API key auth resolves tenant_id and sets it on the DB session
immediately (before any query runs) — see phase1.txt Step 8 and
final architecture.txt §14.4. Firebase Auth is NOT wired here; that's for
the human-facing consoles starting Phase 4.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ankura.api.errors import AuthError
from ankura.config import get_settings
from ankura.db.engine import get_db_session, set_tenant_context
from ankura.db.models import ApiKey
from ankura.security import hash_api_key, verify_api_key

__all__ = ["TenantContext", "get_current_tenant"]


@dataclass(frozen=True)
class TenantContext:
    tenant_id: uuid.UUID
    api_key_id: uuid.UUID


async def get_current_tenant(
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_db_session),
) -> TenantContext:
    if authorization is None or not authorization.startswith("Bearer "):
        raise AuthError(
            "AUTH_MISSING",
            "missing or malformed Authorization header, expected 'Bearer <key>'",
        )
    raw_key = authorization.removeprefix("Bearer ").strip()
    if not raw_key:
        raise AuthError(
            "AUTH_MISSING",
            "missing or malformed Authorization header, expected 'Bearer <key>'",
        )

    settings = get_settings()
    computed_hash = hash_api_key(raw_key, settings.api_key_pepper)

    # api_keys has no RLS (bootstrap/auth table, see db/base.py) — this
    # query runs before tenant context exists, which is exactly why: the
    # app role's SELECT grant on this table is unconditional.
    result = await session.execute(select(ApiKey).where(ApiKey.key_hash == computed_hash))
    api_key = result.scalar_one_or_none()

    if api_key is None or not verify_api_key(raw_key, api_key.key_hash, settings.api_key_pepper):
        raise AuthError("AUTH_INVALID", "invalid API key")
    if api_key.revoked_at is not None:
        raise AuthError("AUTH_REVOKED", "API key has been revoked")

    await set_tenant_context(session, str(api_key.tenant_id))
    return TenantContext(tenant_id=api_key.tenant_id, api_key_id=api_key.id)
