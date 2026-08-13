"""Settings fail-fast behaviour. Implemented in Phase 1 Step 3.

PROVE IT (phase1.txt Step 3): booting with an empty environment raises a
clear config error listing every missing key, not a stack trace at first
query. `_env_file=None` disables loading the real backend/.env so these
tests exercise a truly empty environment regardless of local dev setup.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ankura.config import Settings, assert_expected_db_role

VALID: dict[str, str] = {
    "env": "local",
    "database_url": "postgresql://user:pw@ep-example.aws.neon.tech/db",
    "database_direct_url": "postgresql://user:pw@ep-example.aws.neon.tech/db",
    "app_db_role": "ankura_app",
    "log_level": "INFO",
    "api_key_pepper": "x" * 32,
}


def test_valid_settings_construct_cleanly() -> None:
    Settings(_env_file=None, **VALID)  # type: ignore[call-arg]


def test_empty_environment_lists_every_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "ENV",
        "DATABASE_URL",
        "DATABASE_DIRECT_URL",
        "APP_DB_ROLE",
        "LOG_LEVEL",
        "API_KEY_PEPPER",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    missing_fields = {error["loc"][0] for error in exc_info.value.errors()}
    assert missing_fields == {
        "env",
        "database_url",
        "database_direct_url",
        "app_db_role",
        "log_level",
        "api_key_pepper",
    }


@pytest.mark.parametrize("bad_url", ["mysql://x", "not-a-url", ""])
def test_database_url_must_look_like_postgres(bad_url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**VALID, "database_url": bad_url})  # type: ignore[call-arg]


@pytest.mark.parametrize("owner_role", ["postgres", "neondb_owner", "NEONDB_OWNER"])
def test_app_db_role_rejects_owner_like_names(owner_role: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**VALID, "app_db_role": owner_role})  # type: ignore[call-arg]


def test_api_key_pepper_rejects_short_secrets() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**VALID, "api_key_pepper": "too-short"})  # type: ignore[call-arg]


def test_prod_requires_indian_region() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            **{
                **VALID,
                "env": "prod",
                "database_url": "postgresql://user:pw@ep-x.us-east-2.aws.neon.tech/db",
            },
        )


def test_prod_allows_asia_south1() -> None:
    Settings(
        _env_file=None,  # type: ignore[call-arg]
        **{
            **VALID,
            "env": "prod",
            "database_url": "postgresql://user:pw@10.1.2.3/db?host=asia-south1",
        },
    )


def test_local_env_has_no_region_restriction() -> None:
    Settings(_env_file=None, **VALID)  # type: ignore[call-arg]  # env=local, us-east-2 URL — fine


def test_assert_expected_db_role_passes_when_matching() -> None:
    settings = Settings(_env_file=None, **VALID)  # type: ignore[call-arg]
    assert_expected_db_role("ankura_app", settings)  # must not raise


def test_assert_expected_db_role_raises_when_mismatched() -> None:
    settings = Settings(_env_file=None, **VALID)  # type: ignore[call-arg]
    with pytest.raises(RuntimeError, match="ankura_app"):
        assert_expected_db_role("neondb_owner", settings)
