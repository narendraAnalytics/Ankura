"""POST/GET /v1/applications routes.

Implemented in Phase 1 Step 8 (fetch one, cursor-paginated list) and Step 9
(POST is Idempotency-Key-required). Intake validation here is hygiene
(identifier format, ticket band, duplicate external_ref) — it is NOT credit
policy. See phase1.txt Step 8/9.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ankura.api.deps import TenantContext, get_current_tenant
from ankura.api.errors import NotFoundError, SemanticError
from ankura.clock import Clock, get_clock
from ankura.config import get_settings
from ankura.contracts.application import ApplicationIn, ApplicationOut, ApplicationStatus
from ankura.db.engine import get_db_session
from ankura.services import applications as applications_service

router = APIRouter(prefix="/v1/applications", tags=["applications"])


class ApplicationListOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[ApplicationOut]
    next_cursor: str | None


@router.post(
    "",
    response_model=None,
    responses={status.HTTP_201_CREATED: {"model": ApplicationOut}},
)
async def create_application(
    payload: ApplicationIn,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    tenant: TenantContext = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_db_session),
    clock: Clock = Depends(get_clock),
) -> JSONResponse:
    if not idempotency_key or not idempotency_key.strip():
        raise SemanticError(
            "IDEMPOTENCY_KEY_MISSING", "Idempotency-Key header is required on POST /v1/applications"
        )
    response_status, response_body = await applications_service.create_application_idempotent(
        session,
        tenant.tenant_id,
        idempotency_key.strip(),
        payload,
        clock,
        ttl_hours=get_settings().idempotency_key_ttl_hours,
        actor_id=str(tenant.api_key_id),
    )
    return JSONResponse(status_code=response_status, content=response_body)


@router.get("/{application_id}", response_model=ApplicationOut)
async def get_application(
    application_id: uuid.UUID,
    tenant: TenantContext = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_db_session),
) -> ApplicationOut:
    result = await applications_service.get_application(session, tenant.tenant_id, application_id)
    if result is None:
        raise NotFoundError("APPLICATION_NOT_FOUND", f"no application {application_id}")
    return result


@router.get("", response_model=ApplicationListOut)
async def list_applications(
    tenant: TenantContext = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_db_session),
    status_filter: ApplicationStatus | None = Query(default=None, alias="status"),
    created_after: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(
        default=applications_service.DEFAULT_PAGE_SIZE,
        ge=1,
        le=applications_service.MAX_PAGE_SIZE,
    ),
) -> ApplicationListOut:
    items, next_cursor = await applications_service.list_applications(
        session,
        tenant.tenant_id,
        status_filter=status_filter,
        created_after=created_after,
        created_before=created_before,
        cursor=cursor,
        limit=limit,
    )
    return ApplicationListOut(items=items, next_cursor=next_cursor)
