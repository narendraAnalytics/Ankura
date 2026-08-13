"""Application create/get/list business logic, called by api/v1/applications.py.

Implemented in Phase 1 Step 8. Intake validation here is hygiene (identifier
consistency, duplicate external_ref, borrower upsert) — it is NOT credit
policy; format/checksum/ticket-band/purpose validation already happened at
the contract layer (contracts/application.py) before this module ever runs.
"""

from __future__ import annotations

import base64
import binascii
import logging
import uuid
from datetime import datetime

from sqlalchemy import literal, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ankura.api.errors import ConflictError, SemanticError
from ankura.clock import Clock
from ankura.contracts.application import ApplicationIn, ApplicationOut, ApplicationStatus
from ankura.contracts.common import EntityType, LoanPurpose
from ankura.db.models import Application, Borrower
from ankura.services import audit as audit_service
from ankura.services import idempotency as idempotency_service

_ENTITY_TYPE_APPLICATION = "application"
_ACTOR_TYPE_API_KEY = "api_key"

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


def _to_out(
    application: Application,
    *,
    borrower_pan: str,
    borrower_gstin: str,
    borrower_udyam: str | None,
    entity_type: str,
    legal_name: str,
) -> ApplicationOut:
    return ApplicationOut(
        id=application.id,
        tenant_id=application.tenant_id,
        external_ref=application.external_ref,
        status=ApplicationStatus(application.status),
        borrower_pan=borrower_pan,
        borrower_gstin=borrower_gstin,
        borrower_udyam=borrower_udyam,
        entity_type=EntityType(entity_type),
        legal_name=legal_name,
        requested_amount_paise=application.requested_amount_paise,
        tenure_months=application.tenure_months,
        purpose=LoanPurpose(application.purpose),
        as_of=application.as_of,
        received_at=application.received_at,
    )


def _check_identifier_consistency(tenant_id: uuid.UUID, payload: ApplicationIn) -> None:
    """The "Name consistency check across supplied identifiers → warning,
    not reject" line (phase1.txt Step 8). Phase 1 has no external name source to
    check a *name* against (GST/bureau lookups arrive in later phases) —
    the one consistency Phase 1 can actually check without external data
    is structural: a GSTIN structurally embeds its holder's PAN at
    positions 3-12 (validators/identifiers.py), so that embedded PAN
    should equal the separately supplied borrower_pan. A mismatch usually
    means a data-entry error on one of the two fields; it's flagged, never
    rejected, per the checklist's own wording.
    """
    embedded_pan = payload.borrower_gstin[2:12]
    if embedded_pan != payload.borrower_pan:
        logger.warning(
            "identifier_consistency_warning: PAN embedded in GSTIN does not match "
            "supplied PAN (tenant_id=%s external_ref=%s embedded_pan=%s supplied_pan=%s)",
            tenant_id,
            payload.external_ref,
            embedded_pan,
            payload.borrower_pan,
        )


async def _upsert_borrower(
    session: AsyncSession, tenant_id: uuid.UUID, payload: ApplicationIn
) -> uuid.UUID:
    """Find-or-update by (tenant_id, pan) — "Borrower upserted by
    (tenant_id, pan); never silently duplicated" (phase1.txt Step 8).
    A single atomic INSERT ... ON CONFLICT DO UPDATE, not a SELECT-then-
    INSERT (which would race under concurrent requests for the same PAN).
    """
    stmt = (
        pg_insert(Borrower)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            entity_type=payload.entity_type.value,
            legal_name=payload.legal_name,
            pan=payload.borrower_pan,
            gstin=payload.borrower_gstin,
            udyam=payload.borrower_udyam,
        )
        .on_conflict_do_update(
            index_elements=[Borrower.tenant_id, Borrower.pan],
            set_={
                "entity_type": payload.entity_type.value,
                "legal_name": payload.legal_name,
                "gstin": payload.borrower_gstin,
                "udyam": payload.borrower_udyam,
            },
        )
        .returning(Borrower.id)
    )
    try:
        result = await session.execute(stmt)
    except IntegrityError as exc:
        # Only remaining unique constraint that can fire here is
        # uq_borrowers_tenant_gstin: this GSTIN already belongs to a
        # DIFFERENT PAN for this tenant. A genuine data conflict, not a
        # normal upsert case — surfaced as 409, not silently absorbed.
        raise ConflictError(
            "BORROWER_IDENTIFIER_CONFLICT",
            "borrower_gstin is already associated with a different PAN for this tenant",
        ) from exc
    return result.scalar_one()


async def create_application(
    session: AsyncSession, tenant_id: uuid.UUID, payload: ApplicationIn, clock: Clock, actor_id: str
) -> ApplicationOut:
    as_of = payload.as_of if payload.as_of is not None else clock.now()
    application_id = uuid.uuid4()

    await audit_service.append_event(
        tenant_id,
        entity_type=_ENTITY_TYPE_APPLICATION,
        entity_id=application_id,
        event_type="APPLICATION_RECEIVED",
        actor_type=_ACTOR_TYPE_API_KEY,
        actor_id=actor_id,
        payload={"external_ref": payload.external_ref},
        occurred_at=as_of,
    )

    existing = await session.execute(
        select(Application).where(
            Application.tenant_id == tenant_id, Application.external_ref == payload.external_ref
        )
    )
    existing_row = existing.scalar_one_or_none()
    if existing_row is not None:
        await audit_service.append_event(
            tenant_id,
            entity_type=_ENTITY_TYPE_APPLICATION,
            entity_id=existing_row.id,
            event_type="APPLICATION_REJECTED_INTAKE",
            actor_type=_ACTOR_TYPE_API_KEY,
            actor_id=actor_id,
            payload={"reason": "DUPLICATE_EXTERNAL_REF", "external_ref": payload.external_ref},
            occurred_at=as_of,
        )
        raise ConflictError(
            "DUPLICATE_EXTERNAL_REF",
            f"application with external_ref {payload.external_ref!r} already exists",
            details=[
                {
                    "field": "external_ref",
                    "existing_application_id": str(existing_row.id),
                }
            ],
        )

    _check_identifier_consistency(tenant_id, payload)

    # BORROWER_IDENTIFIER_CONFLICT (raised inside _upsert_borrower) does NOT
    # get its own APPLICATION_REJECTED_INTAKE event here: it's a borrower
    # data conflict, not an application-status rejection, and no
    # application row (real or otherwise) exists yet to anchor the event
    # to at this point — `application_id` above was only ever generated
    # for the RECEIVED event, never persisted. Flagged deliberately, same
    # spirit as this file's other ASSUMPTION FLAGGED notes.
    borrower_id = await _upsert_borrower(session, tenant_id, payload)

    application = Application(
        id=application_id,
        tenant_id=tenant_id,
        borrower_id=borrower_id,
        external_ref=payload.external_ref,
        requested_amount_paise=payload.requested_amount_paise,
        tenure_months=payload.tenure_months,
        purpose=payload.purpose.value,
        status=ApplicationStatus.RECEIVED.value,
        as_of=as_of,
    )
    session.add(application)
    await session.flush()
    await session.refresh(application)

    await audit_service.append_event(
        tenant_id,
        entity_type=_ENTITY_TYPE_APPLICATION,
        entity_id=application.id,
        event_type="APPLICATION_VALIDATED",
        actor_type=_ACTOR_TYPE_API_KEY,
        actor_id=actor_id,
        payload={"external_ref": payload.external_ref},
        occurred_at=as_of,
    )

    return _to_out(
        application,
        borrower_pan=payload.borrower_pan,
        borrower_gstin=payload.borrower_gstin,
        borrower_udyam=payload.borrower_udyam,
        entity_type=payload.entity_type.value,
        legal_name=payload.legal_name,
    )


async def create_application_idempotent(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    idempotency_key: str,
    payload: ApplicationIn,
    clock: Clock,
    ttl_hours: int,
    actor_id: str,
) -> tuple[int, dict[str, object]]:
    """Idempotency-Key-wrapped `create_application` — phase1.txt Step 9.
    Returns (status_code, response_body) so the route can serve a
    byte-identical replay on every subsequent call with the same key and
    the same request body.
    """

    async def _do_work() -> tuple[int, dict[str, object]]:
        result = await create_application(session, tenant_id, payload, clock, actor_id)
        return 201, result.model_dump(mode="json")

    try:
        result = await idempotency_service.run_idempotent(
            session,
            tenant_id,
            idempotency_key,
            payload.model_dump(mode="json"),
            clock,
            _do_work,
            ttl_hours=ttl_hours,
        )
    except idempotency_service.IdempotencyKeyReuseError as exc:
        raise ConflictError(
            "IDEMPOTENCY_KEY_REUSE",
            f"Idempotency-Key {idempotency_key!r} was already used with a different request body",
        ) from exc

    if result.replayed:
        await audit_service.append_event(
            tenant_id,
            entity_type=_ENTITY_TYPE_APPLICATION,
            entity_id=uuid.UUID(str(result.body["id"])),
            event_type="IDEMPOTENT_REPLAY",
            actor_type=_ACTOR_TYPE_API_KEY,
            actor_id=actor_id,
            payload={"idempotency_key": idempotency_key},
            occurred_at=clock.now(),
        )

    return result.status_code, result.body


async def get_application(
    session: AsyncSession, tenant_id: uuid.UUID, application_id: uuid.UUID
) -> ApplicationOut | None:
    result = await session.execute(
        select(Application, Borrower)
        .join(Borrower, Application.borrower_id == Borrower.id)
        # Defense-in-depth tenant_id filter on top of RLS — see
        # backend/CLAUDE.md: "temporarily strip the ORM's own filter and
        # confirm RLS alone still blocks cross-tenant reads" is the actual
        # test; RLS makes this filter redundant today but not optional.
        .where(Application.id == application_id, Application.tenant_id == tenant_id)
    )
    row = result.one_or_none()
    if row is None:
        return None
    application, borrower = row
    return _to_out(
        application,
        borrower_pan=borrower.pan,
        borrower_gstin=borrower.gstin,
        borrower_udyam=borrower.udyam,
        entity_type=borrower.entity_type,
        legal_name=borrower.legal_name,
    )


def _encode_cursor(created_at: datetime, application_id: uuid.UUID) -> str:
    payload = f"{created_at.isoformat()}|{application_id}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        payload = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        created_at_str, id_str = payload.split("|")
        return datetime.fromisoformat(created_at_str), uuid.UUID(id_str)
    except (ValueError, binascii.Error) as exc:
        raise SemanticError("INVALID_CURSOR", f"cursor {cursor!r} is not valid") from exc


async def list_applications(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    status_filter: ApplicationStatus | None,
    created_after: datetime | None,
    created_before: datetime | None,
    cursor: str | None,
    limit: int,
) -> tuple[list[ApplicationOut], str | None]:
    """Keyset ("cursor") pagination on (created_at, id) DESC — id breaks
    ties within the same created_at, which plain created_at ordering can't
    guarantee under concurrent inserts. See phase1.txt Step 8."""
    stmt = (
        select(Application, Borrower)
        .join(Borrower, Application.borrower_id == Borrower.id)
        .where(Application.tenant_id == tenant_id)
    )
    if status_filter is not None:
        stmt = stmt.where(Application.status == status_filter.value)
    if created_after is not None:
        stmt = stmt.where(Application.created_at >= created_after)
    if created_before is not None:
        stmt = stmt.where(Application.created_at <= created_before)
    if cursor is not None:
        cursor_created_at, cursor_id = _decode_cursor(cursor)
        stmt = stmt.where(
            tuple_(Application.created_at, Application.id)
            < tuple_(literal(cursor_created_at), literal(cursor_id))
        )

    stmt = stmt.order_by(Application.created_at.desc(), Application.id.desc()).limit(limit + 1)
    result = await session.execute(stmt)
    rows = result.all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        _to_out(
            application,
            borrower_pan=borrower.pan,
            borrower_gstin=borrower.gstin,
            borrower_udyam=borrower.udyam,
            entity_type=borrower.entity_type,
            legal_name=borrower.legal_name,
        )
        for application, borrower in rows
    ]

    next_cursor = None
    if has_more and rows:
        last_application = rows[-1][0]
        next_cursor = _encode_cursor(last_application.created_at, last_application.id)

    return items, next_cursor
