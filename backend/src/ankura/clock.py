"""The only permitted source of "now" in this codebase.

Step 8 pulls forward the minimum this needs: a `Clock` protocol plus
`SystemClock`, injected via a FastAPI dependency, so every request's
`as_of`/`received_at` stamping already goes through one seam instead of a
scattered `datetime.now()`. Step 10 completes the discipline: `FrozenClock`
for deterministic tests, and the repo-wide grep test banning
`datetime.now()`/`utcnow()`/`date.today()`/`time.time()` anywhere outside
this module. See phase1.txt Step 10 and backend/CLAUDE.md's clock
discipline rule.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Timezone-aware UTC datetime."""
        ...


class SystemClock:
    """The only place `datetime.now()` may legitimately appear."""

    def now(self) -> datetime:
        return datetime.now(UTC)


_default_clock: Clock = SystemClock()


def get_clock() -> Clock:
    """FastAPI dependency. Route/service code must depend on this, never
    import `SystemClock` (or `datetime.now`) directly."""
    return _default_clock
