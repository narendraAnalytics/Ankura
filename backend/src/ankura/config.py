"""Application settings — fail-fast, no defaults for secrets.

pydantic-settings raises a single ValidationError listing every missing or
invalid field at construction time. As long as `get_settings()` is called
eagerly at startup (Step 8 wires this into the app lifespan), a
misconfigured deployment fails immediately with a readable error, not a
stack trace the first time a route touches the database.

See phase1.txt Step 3 and final architecture.txt §13 (residency),
§14.3 (two connection strings), §14.4 (non-owner app role).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Roles that own the schema and therefore bypass Row Level Security
# silently (final architecture.txt §14.4). APP_DB_ROLE must never be one of
# these, even though Steps 1-5 still connect as neondb_owner because the
# dedicated non-owner role isn't created until Step 4.
_OWNER_LIKE_ROLES = {"postgres", "neondb_owner"}

# Data-residency guard (final architecture.txt §13 table / §6.1): production
# database traffic must stay in an Indian GCP region.
_ALLOWED_PROD_REGIONS = ("asia-south1", "asia-south2")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # "ignore", not "forbid": .env accumulates keys for later phases
        # (GEMINI_API_KEY for Phase 5, provider credentials for Phase 7).
        # Fail-fast here means missing REQUIRED keys, not unrelated extras.
        extra="ignore",
    )

    env: Literal["local", "dev", "prod"]

    database_url: str
    """Pooled endpoint, app role. See §14.3 — two connection strings, not one."""

    database_direct_url: str
    """Unpooled endpoint. Alembic only — never used by the running app."""

    app_db_role: str
    """Dedicated non-owner Postgres role the app connects as. See §14.4."""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    api_key_pepper: str
    """Server-side secret mixed into tenant API key hashes before storage."""

    @field_validator("database_url", "database_direct_url")
    @classmethod
    def _must_look_like_postgres_dsn(cls, value: str) -> str:
        if not value.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError(
                'must start with "postgresql://" (raw Neon/Cloud SQL DSN) or '
                '"postgresql+psycopg://" (already driver-qualified)'
            )
        return value

    @field_validator("app_db_role")
    @classmethod
    def _must_not_be_owner_like(cls, value: str) -> str:
        if value.lower() in _OWNER_LIKE_ROLES:
            raise ValueError(
                f'"{value}" is an owner-like role and silently bypasses Row '
                "Level Security — APP_DB_ROLE must be a dedicated non-owner "
                "role (final architecture.txt §14.4)"
            )
        return value

    @field_validator("api_key_pepper")
    @classmethod
    def _must_be_long_enough(cls, value: str) -> str:
        if len(value) < 16:
            raise ValueError("must be at least 16 characters")
        return value

    @model_validator(mode="after")
    def _enforce_prod_data_residency(self) -> Settings:
        if self.env == "prod" and not any(
            region in self.database_url for region in _ALLOWED_PROD_REGIONS
        ):
            raise ValueError(
                "ENV=prod requires DATABASE_URL to target an Indian region "
                f"({' or '.join(_ALLOWED_PROD_REGIONS)}) — data residency "
                "guard, final architecture.txt §13 / §6.1. Refusing to boot."
            )
        return self


def assert_expected_db_role(current_user: str, settings: Settings) -> None:
    """Compare a live `SELECT current_user` result against APP_DB_ROLE.

    Pure comparison, no DB access itself — Step 4's engine startup (or a
    readiness check) calls this once a connection exists, so the RLS-bypass
    mistake is caught even if APP_DB_ROLE was set correctly in config but
    the connection string still authenticates as someone else.
    """
    if current_user != settings.app_db_role:
        raise RuntimeError(
            f'connected as "{current_user}" but APP_DB_ROLE is '
            f'"{settings.app_db_role}" — refusing to continue, this would '
            "silently run every query without tenant isolation"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # fields come from env/`.env`
