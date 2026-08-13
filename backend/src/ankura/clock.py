"""The only permitted source of "now" in this codebase.

Step 8 pulled forward the minimum this needed: a `Clock` protocol plus
`SystemClock`, injected via a FastAPI dependency, so every request's
`as_of`/`received_at` stamping already went through one seam instead of a
scattered `datetime.now()`. Step 10 completes the discipline: `FrozenClock`
for deterministic tests, and a ruff `TID251` banned-api rule (see
pyproject.toml's `[tool.ruff.lint.flake8-tidy-imports.banned-api]`, with a
per-file-ignore for this module) plus tests/test_clock_discipline.py's own
belt-and-suspenders source-tree grep, banning
`datetime.now()`/`datetime.utcnow()`/`date.today()`/`time.time()` anywhere
outside this module. See phase1.txt Step 10 and backend/CLAUDE.md's clock
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


class FrozenClock:
    """Deterministic clock for tests: always returns the instant it was
    constructed with, never advancing on its own."""

    def __init__(self, frozen_at: datetime) -> None:
        if frozen_at.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        self._frozen_at = frozen_at

    def now(self) -> datetime:
        return self._frozen_at


_default_clock: Clock = SystemClock()


def get_clock() -> Clock:
    """FastAPI dependency. Route/service code must depend on this, never
    import `SystemClock` (or `datetime.now`) directly."""
    return _default_clock
