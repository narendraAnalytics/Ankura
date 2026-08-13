"""GET /v1/tenants/me — echoes the resolved tenant, used as the auth smoke
test.

Implemented in Phase 1 Step 8.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ankura.api.deps import TenantContext, get_current_tenant
from ankura.api.errors import NotFoundError
from ankura.db.engine import get_db_session
from ankura.db.models import Tenant

router = APIRouter(prefix="/v1/tenants", tags=["tenants"])


class TenantOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: uuid.UUID
    slug: str
    legal_name: str
    status: str


@router.get("/me", response_model=TenantOut)
async def get_current_tenant_info(
    tenant: TenantContext = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_db_session),
) -> TenantOut:
    # tenants has no RLS (bootstrap table, see db/base.py) — this SELECT is
    # scoped by the id resolved from the API key, not by RLS.
    result = await session.execute(select(Tenant).where(Tenant.id == tenant.tenant_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise NotFoundError("TENANT_NOT_FOUND", "resolved tenant no longer exists")
    return TenantOut(id=row.id, slug=row.slug, legal_name=row.legal_name, status=row.status)
