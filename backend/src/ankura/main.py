"""FastAPI application factory.

Router wiring, the request-id middleware, and the standard error-envelope
exception handlers are assembled here (Phase 1 Step 8). `get_settings()` is
called eagerly at import time so a misconfigured deployment fails at boot,
not on the first request that happens to touch config.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import Response

from ankura.api.errors import register_exception_handlers
from ankura.api.v1 import applications, health, tenants
from ankura.config import get_settings

RequestHandler = Callable[[Request], Awaitable[Response]]


def create_app() -> FastAPI:
    get_settings()

    app = FastAPI(
        title="Ankura",
        description="Governed AI decisioning layer for Indian MSME lending.",
        version="0.1.0",
    )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next: RequestHandler) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(tenants.router)
    app.include_router(applications.router)

    return app


app = create_app()
