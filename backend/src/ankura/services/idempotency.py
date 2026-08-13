"""Idempotency-Key handling: fingerprint, replay, conflict, concurrent-request
resolution.

Implemented in Phase 1 Step 9. `run_idempotent` claims (tenant_id, key) with
a placeholder row *before* running `do_work`, then finalizes that same row
with the real response once `do_work` completes — both inside one SAVEPOINT
(`session.begin_nested()`) on the request's own transaction. Claiming before
the work runs (not after) is deliberate: `do_work` itself writes to
application-owned tables (e.g. applications.uq_applications_tenant_external_ref)
that have no idempotency awareness of their own, so two truly concurrent
identical requests would otherwise both reach that insert and one would
blow up with a raw IntegrityError instead of replaying cleanly. Claiming
first means the SECOND request blocks (see below) before it ever touches
those tables. A crash between claim and finalize is still impossible from
the outside: both happen in the same uncommitted transaction, so a crash
there just means neither survives, per phase1.txt Step 9.

Concurrency: the claim step is `INSERT ... ON CONFLICT (tenant_id, key) DO
NOTHING RETURNING id`, not a plain INSERT wrapped in try/except
IntegrityError. Postgres still has to block on the unique index to resolve
the conflict, and that lock is held for the winner's *entire* transaction,
not just its INSERT — so a second concurrent request naturally *waits* for
the first to fully commit (claim + do_work + finalize) or roll back before
ON CONFLICT can decide there's nothing to do. That blocking is where "the
loser waits" comes from, for free, with no IntegrityError to catch. If the
loser's claim comes back empty, its own work (if any had started) is rolled
back to the savepoint and it replays whatever the winner committed.

Only successful responses (2xx, from `do_work`) are ever passed in to cache.
A deliberate ApiError raised inside `do_work` (DUPLICATE_EXTERNAL_REF,
BORROWER_IDENTIFIER_CONFLICT, ...) propagates straight through `run_idempotent`
uncached: those checks are already idempotent by construction against live
data, so replaying the exact same request against the exact same key will
trip the same check again on its own, without needing a cache — and caching
a 4xx would risk serving a stale rejection after the underlying condition
(e.g. the duplicate external_ref) has since been resolved.

Expired keys are not silently reusable: an entry past `expires_at` is still
the physical row occupying the (tenant_id, key) unique slot, and is still
replayed if found. `purge_expired` is the only thing that actually frees a
key for reuse — the "cleanup path" phase1.txt Step 9 asks for. Nothing in
Phase 1 schedules it automatically (Cloud Tasks is out of scope here); it's
callable by ops or a future job.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ankura.clock import Clock
from ankura.db.models import IdempotencyKey

DEFAULT_TTL_HOURS = 24


class IdempotencyKeyReuseError(Exception):
    """Same (tenant_id, key) but a different request body. The caller maps
    this to the 409 IDEMPOTENCY_KEY_REUSE response."""

    def __init__(self, key: str) -> None:
        super().__init__(f"Idempotency-Key {key!r} reused with a different request body")
        self.key = key


class _LostRaceError(Exception):
    """Internal control-flow signal only: a concurrent request already
    claimed this key. Always caught inside `run_idempotent`."""


@dataclass(frozen=True)
class IdempotentResult:
    status_code: int
    body: dict[str, Any]
    replayed: bool
    """True whenever this response came from a previously stored record —
    either found immediately, or recovered after losing a concurrent claim
    race — rather than from a fresh `do_work` call. Callers use this to
    decide whether to emit an IDEMPOTENT_REPLAY audit event (Step 11)."""


def fingerprint(payload: dict[str, Any]) -> str:
    """Stable hash of a request body, independent of field order."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize(body: dict[str, Any]) -> dict[str, Any]:
    """Sort keys before returning a response body. A freshly built dict (Python
    field-insertion order) and the same dict after a JSONB round-trip
    (Postgres's own canonical key order, not insertion order) serialize to
    different bytes otherwise — this is what makes a replay byte-identical
    to the original, per phase1.txt Step 9's PROVE IT."""
    return dict(sorted(body.items()))


async def _find(session: AsyncSession, tenant_id: uuid.UUID, key: str) -> IdempotencyKey | None:
    result = await session.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == tenant_id, IdempotencyKey.key == key
        )
    )
    return result.scalar_one_or_none()


async def _claim_placeholder(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    key: str,
    request_fingerprint: str,
    expires_at: datetime,
) -> uuid.UUID | None:
    """Atomically claim (tenant_id, key) with a placeholder response (never
    observable outside this transaction — see module docstring), or return
    None if it's already taken. Postgres blocks this statement on the
    unique index until any concurrent transaction holding the same key
    resolves, so a `None` here always means the other side has already
    committed — never a race still in flight.
    """
    stmt = (
        pg_insert(IdempotencyKey)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            key=key,
            request_fingerprint=request_fingerprint,
            response_status=0,
            response_body={},
            expires_at=expires_at,
        )
        .on_conflict_do_nothing(index_elements=[IdempotencyKey.tenant_id, IdempotencyKey.key])
        .returning(IdempotencyKey.id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _finalize(
    session: AsyncSession,
    row_id: uuid.UUID,
    response_status: int,
    response_body: dict[str, Any],
) -> None:
    await session.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.id == row_id)
        .values(response_status=response_status, response_body=response_body)
    )


async def run_idempotent(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    key: str,
    request_body: dict[str, Any],
    clock: Clock,
    do_work: Callable[[], Awaitable[tuple[int, dict[str, Any]]]],
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> IdempotentResult:
    """Run `do_work` exactly once per (tenant_id, key); every later call with
    the same key + the same `request_body` replays the first response
    instead of running `do_work` again. A same key + different body raises
    `IdempotencyKeyReuseError`.
    """
    request_fingerprint = fingerprint(request_body)

    existing = await _find(session, tenant_id, key)
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise IdempotencyKeyReuseError(key)
        return IdempotentResult(
            existing.response_status, _normalize(existing.response_body), replayed=True
        )

    expires_at = clock.now() + timedelta(hours=ttl_hours)
    try:
        async with session.begin_nested():
            claimed_id = await _claim_placeholder(
                session, tenant_id, key, request_fingerprint, expires_at
            )
            if claimed_id is None:
                raise _LostRaceError
            response_status, response_body = await do_work()
            await _finalize(session, claimed_id, response_status, response_body)
    except _LostRaceError:
        winner = await _find(session, tenant_id, key)
        if winner is None:  # pragma: no cover - see module docstring
            raise RuntimeError(
                f"lost idempotency race for key {key!r} but found no winner row"
            ) from None
        if winner.request_fingerprint != request_fingerprint:
            raise IdempotencyKeyReuseError(key) from None
        return IdempotentResult(
            winner.response_status, _normalize(winner.response_body), replayed=True
        )

    return IdempotentResult(response_status, _normalize(response_body), replayed=False)


async def purge_expired(session: AsyncSession, clock: Clock) -> int:
    """Delete every idempotency key past its TTL — the "cleanup path" of
    phase1.txt Step 9. Returns the number of rows deleted."""
    result = await session.execute(
        delete(IdempotencyKey).where(IdempotencyKey.expires_at <= clock.now())
    )
    return cast(CursorResult[Any], result).rowcount
