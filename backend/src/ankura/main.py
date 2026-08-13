"""FastAPI application factory.

Router wiring (health, applications, tenants) and auth middleware are added
in Phase 1 Step 8 (application intake API). This file stays a bare factory
until then — no routes, no lifespan events, nothing that reaches the
database yet.
"""

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(
        title="Ankura",
        description="Governed AI decisioning layer for Indian MSME lending.",
        version="0.1.0",
    )
    return app


app = create_app()
