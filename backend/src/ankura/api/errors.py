"""Standard error envelope and exception handlers.

Single envelope shape: {error: {code, message, details[], request_id}}.
Every deliberate rejection in route/service code raises an `ApiError`
subclass, never a bare `HTTPException` — the machine-readable `code` on
each one is the start of the reason-code vocabulary Phase 3's Decision
Record extends, so treat it as a real contract. Firebase Auth is NOT wired
here; that's for the human-facing consoles starting Phase 4.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """Base for every deliberate rejection this API returns."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []


class AuthError(ApiError):
    """401 — missing, malformed, unknown, or revoked API key."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(status.HTTP_401_UNAUTHORIZED, code, message)


class NotFoundError(ApiError):
    """404 — includes rows RLS silently hid, per phase1.txt Step 6 (not
    403; a cross-tenant read looks identical to a nonexistent id)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(status.HTTP_404_NOT_FOUND, code, message)


class ConflictError(ApiError):
    """409 — duplicate external_ref, borrower identifier conflict, etc."""

    def __init__(
        self, code: str, message: str, details: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__(status.HTTP_409_CONFLICT, code, message, details)


class SemanticError(ApiError):
    """400 — request is well-formed (passes contract validation) but
    invalid in a way that isn't a 422 or a 409, e.g. a malformed cursor."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(status.HTTP_400_BAD_REQUEST, code, message)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _envelope(
    code: str, message: str, details: list[dict[str, Any]], request_id: str
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.details, _request_id(request)),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {"field": ".".join(str(part) for part in error["loc"]), "issue": error["msg"]}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_envelope(
                "VALIDATION_ERROR", "request failed validation", details, _request_id(request)
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope("HTTP_ERROR", str(exc.detail), [], _request_id(request)),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled exception", extra={"request_id": _request_id(request)})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(
                "INTERNAL_ERROR", "an unexpected error occurred", [], _request_id(request)
            ),
        )
