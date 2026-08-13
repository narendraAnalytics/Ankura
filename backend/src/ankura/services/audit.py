"""Append-only audit event writer + hash-chain verification.

Implemented in Phase 1 Step 11. `append_event` is the only way to write a
row — no update/delete path exists in this module by design, and
`audit_events` has no UPDATE/DELETE grant for the app role at the database
level either (migration 0002, "audit_events is append-only at the database
level, not just by omission in application code"). P3 extends this into the
Decision Record; this step only starts the chain.

DURABILITY IS DELIBERATELY DECOUPLED FROM THE CALLER'S TRANSACTION.
`append_event` opens and commits its own short-lived session rather than
writing on the caller's request session. This matters because several
events this step emits (AUTH_FAILED, APPLICATION_REJECTED_INTAKE) happen
exactly when the request is about to fail — and this codebase's one-
transaction-per-request pattern (`get_db_session`) rolls the whole request
transaction back on any raised `ApiError`. An audit write sharing that
transaction would vanish along with everything else the instant the
rejection it's supposed to record gets raised. A self-contained write is
also just the right shape for an audit ledger in general: what happened
should be independent of whether the business operation it describes
ultimately succeeded.

CONCURRENCY: the obvious way to serialize "read the tail hash, then insert
onto it" is `SELECT ... FOR UPDATE` on the latest row — but Postgres
requires UPDATE privilege to use `FOR UPDATE`, which this role deliberately
doesn't have on this table (see above). Instead, `append_event` takes a
transaction-scoped Postgres advisory lock keyed on the tenant
(`pg_advisory_xact_lock`, a built-in function needing no table grants at
all) before reading the tail and inserting — held for exactly this one
event's own transaction, so a concurrent second writer for the same tenant
blocks at its own lock acquisition until the first commits or rolls back.
Same "loser waits" shape as idempotency's unique-constraint trick (Step 9),
one level down the stack.

CHAIN ORDERING: the chain is walked by hash pointer
(`event.prev_hash == parent.event_hash`), never by `recorded_at`. That
column is `server_default=func.now()` — and Postgres's `now()` is constant
for the whole transaction, not per-statement. Even with each event in its
own transaction here, relying on timestamp ordering would still be fragile
under real clock resolution/skew; the hash pointer names an exact single
predecessor with no such ambiguity.

PII rule: `payload` must never contain PAN, GSTIN, mobile, or account
number — references (ids), not values. Not mechanically enforced here
(there is no generic way to know what a caller's dict "means"); callers are
responsible, same as the rule's phrasing in phase1.txt Step 11.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, text

from ankura.db.engine import async_session_factory, set_tenant_context
from ankura.db.models import AuditEvent


def canonical_json(payload: dict[str, Any]) -> str:
    """Stable serialisation (sorted keys, fixed separators) — otherwise the
    hash chain breaks the moment dict ordering or float repr shifts under a
    Python version bump. See phase1.txt Step 11."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _hash_input(
    *,
    event_id: uuid.UUID,
    tenant_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    event_type: str,
    actor_type: str,
    actor_id: str | None,
    payload: dict[str, Any],
    occurred_at: datetime,
    prev_hash: str | None,
) -> dict[str, Any]:
    """Deliberately excludes `recorded_at`: it's DB-assigned wall-clock
    write time (not known until after INSERT), not business content the
    chain needs to protect."""
    return {
        "id": str(event_id),
        "tenant_id": str(tenant_id),
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "event_type": event_type,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "payload": payload,
        "occurred_at": occurred_at.isoformat(),
        "prev_hash": prev_hash,
    }


def _compute_event_hash(**kwargs: Any) -> str:
    canonical = canonical_json(_hash_input(**kwargs))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def append_event(
    tenant_id: uuid.UUID,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    event_type: str,
    actor_type: str,
    actor_id: str | None,
    payload: dict[str, Any],
    occurred_at: datetime,
) -> AuditEvent:
    async with async_session_factory() as session, session.begin():
        await set_tenant_context(session, str(tenant_id))

        # Transaction-scoped advisory lock — released at COMMIT/ROLLBACK
        # below, needs no GRANT (see module docstring).
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('audit_events'), hashtext(:tenant_id))"),
            {"tenant_id": str(tenant_id)},
        )

        # The one event (if any) for this tenant with no child pointing at
        # it yet — i.e. the current end of the chain. Safe only while
        # holding the advisory lock above.
        tail_result = await session.execute(
            text(
                """
                SELECT e1.event_hash
                FROM audit_events e1
                WHERE e1.tenant_id = :tenant_id
                  AND NOT EXISTS (
                      SELECT 1 FROM audit_events e2
                      WHERE e2.tenant_id = e1.tenant_id AND e2.prev_hash = e1.event_hash
                  )
                """
            ),
            {"tenant_id": str(tenant_id)},
        )
        prev_hash = tail_result.scalar_one_or_none()

        event_id = uuid.uuid4()
        event_hash = _compute_event_hash(
            event_id=event_id,
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            payload=payload,
            occurred_at=occurred_at,
            prev_hash=prev_hash,
        )

        event = AuditEvent(
            id=event_id,
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            payload_json=payload,
            occurred_at=occurred_at,
            prev_hash=prev_hash,
            event_hash=event_hash,
        )
        session.add(event)
        await session.flush()
        await session.refresh(event)

    return event


@dataclass(frozen=True)
class ChainVerificationResult:
    ok: bool
    first_broken_event_id: uuid.UUID | None


async def verify_chain(tenant_id: uuid.UUID) -> ChainVerificationResult:
    """Walks the chain by hash pointer (see module docstring), recomputing
    each event's hash from its own stored fields and comparing against the
    stored `event_hash`. The first mismatch — tampered payload, or a break
    in the pointer chain — is reported by event id.
    """
    async with async_session_factory() as session:
        await set_tenant_context(session, str(tenant_id))
        result = await session.execute(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
        events = result.scalars().all()

    if not events:
        return ChainVerificationResult(ok=True, first_broken_event_id=None)

    by_prev_hash: dict[str | None, AuditEvent] = {}
    for event in events:
        if event.prev_hash in by_prev_hash:
            # Two events claim the same predecessor: a forked chain.
            return ChainVerificationResult(ok=False, first_broken_event_id=event.id)
        by_prev_hash[event.prev_hash] = event

    current = by_prev_hash.get(None)
    if current is None:
        # No root (every event claims a predecessor) — no valid start.
        return ChainVerificationResult(ok=False, first_broken_event_id=events[0].id)

    visited = 0
    while current is not None:
        recomputed = _compute_event_hash(
            event_id=current.id,
            tenant_id=current.tenant_id,
            entity_type=current.entity_type,
            entity_id=current.entity_id,
            event_type=current.event_type,
            actor_type=current.actor_type,
            actor_id=current.actor_id,
            payload=current.payload_json,
            occurred_at=current.occurred_at,
            prev_hash=current.prev_hash,
        )
        if recomputed != current.event_hash:
            return ChainVerificationResult(ok=False, first_broken_event_id=current.id)
        visited += 1
        current = by_prev_hash.get(current.event_hash)

    if visited != len(events):
        # Events exist that are disconnected from the main chain (orphans)
        # — also a break, though not attributable to one specific link.
        return ChainVerificationResult(ok=False, first_broken_event_id=None)

    return ChainVerificationResult(ok=True, first_broken_event_id=None)
