"""Shared pytest fixtures.

Tenant-scoped client and FrozenClock fixtures land here as their owning
steps arrive (Step 8 for the API client, Step 10 for the clock).
"""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    # psycopg3's async mode cannot run on Windows' default ProactorEventLoop
    # (it needs select()/selectors support that Proactor doesn't provide).
    # Without this, every async DB test fails with
    # "psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop'".
    # Must run before pytest-asyncio creates its first event loop, so this
    # lives at conftest.py import time, not inside a fixture.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
