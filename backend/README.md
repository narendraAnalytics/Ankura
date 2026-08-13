# Ankura Backend

FastAPI service implementing Ankura's governed credit-decisioning API — the
part of the system that lenders integrate into their LOS. See the repo root
[`README.md`](../README.md) for what Ankura is; this document is setup and
day-to-day commands only.

Full architecture is locked in [`../final architecture.txt`](../final%20architecture.txt).
Current build checklist is [`../phase1.txt`](../phase1.txt).

## Stack

Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 (async) · Alembic ·
psycopg3 · Postgres (Neon in dev, Cloud SQL in prod) · LangGraph (from Phase
4) · Gemini via Vertex AI (from Phase 5) · uv for dependency management.

## Prerequisites

- Python 3.12 (see `.python-version`)
- [uv](https://docs.astral.sh/uv/) installed
- A Neon Postgres project (free tier is fine for development)
- `git`

## Setup

```bash
uv sync
cp .env.example .env    # fill in the values described below
```

### Environment variables

Copy `.env.example` and fill every key — the app fails fast at startup if any
required setting is missing (this is intentional; see `src/ankura/config.py`).

| Variable | Notes |
| --- | --- |
| `ENV` | `local` \| `dev` \| `prod` |
| `DATABASE_URL` | **Pooled** Neon endpoint (`…-pooler.neon.tech`), used by the running app |
| `DATABASE_DIRECT_URL` | **Unpooled** Neon endpoint, used only by Alembic migrations |
| `APP_DB_ROLE` | Name of the dedicated non-owner Postgres role the app connects as |
| `LOG_LEVEL` | e.g. `INFO` |
| `API_KEY_PEPPER` | Server-side secret used when hashing tenant API keys |

Why two database URLs: Neon fronts Postgres with PgBouncer in transaction
mode, which does not support session-level prepared statements. Migrations
(DDL) must run against the direct/unpooled endpoint; the app runs against the
pooled endpoint. Mixing these up is the most common first-week Neon mistake.

### Database role and RLS

The app must connect as a **dedicated, non-owner, non-superuser** Postgres
role — owners and superusers silently bypass Row Level Security. Every
tenant-scoped table has `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL
SECURITY`; tenant context is set per-transaction via `SET LOCAL
app.tenant_id`. See `../final architecture.txt` §14.4 for the full rule set.

## Running locally

```bash
uv run alembic upgrade head              # apply migrations (uses DATABASE_DIRECT_URL)
uv run fastapi dev src/ankura/main.py     # start the dev server
```

API docs at `http://localhost:8000/docs` once running.

**Windows Git Bash / legacy console:** if this crashes with
`UnicodeEncodeError: 'charmap' codec can't encode characters` before the
server ever binds, it's `fastapi dev`'s own CLI banner trying to print an
emoji on a non-UTF-8 console — nothing to do with this app. Fix:
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run fastapi dev src/ankura/main.py`.

## Testing

```bash
uv run pytest                 # full suite
uv run pytest --cov=ankura    # with coverage (CI gate: 80%)
```

Two tests are load-bearing and should never be weakened:

- `test_tenant_isolation.py` — passes even with the ORM's own `tenant_id`
  filter removed, proving isolation is enforced by Postgres RLS, not just
  application code.
- `test_clock_discipline.py` — fails the build if `datetime.now()` /
  `utcnow()` / `date.today()` / `time.time()` appear anywhere outside
  `src/ankura/clock.py`.

## Code quality

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/ankura
```

`pre-commit` runs these plus `gitleaks` (secret scanning), `end-of-file-fixer`,
`check-added-large-files`, and `no-commit-to-branch` (blocks direct commits to
`main`) automatically. The config lives at the **repo root**
(`../.pre-commit-config.yaml`), not here — this is a monorepo with one `.git`
at the project root — but `pre-commit` itself is installed as a dev
dependency of this package, so run it via:

```bash
uv run pre-commit install   # once per clone; registers the git hook
uv run pre-commit run --all-files   # run everything on demand
```

The ruff/mypy hooks shell out to `uv run --directory backend <tool>` rather
than using the ruff-pre-commit / mirrors-mypy mirrors, so the versions
pre-commit runs are always exactly what `uv.lock` pins — never a second,
independently-drifting pin.

## CI

`../.github/workflows/ci.yml` runs on every push to `main` and every PR:

- **lint-and-typecheck** — `ruff check`, `ruff format --check`, `mypy --strict`
- **secret-scan** — `gitleaks`, full git history (not just the diff)
- **test** — creates a real, disposable Neon branch (copy-on-write off
  `production`), runs `alembic upgrade head` against it, then the full test
  suite with `pytest --cov=ankura` (gate: fail under 80%, see
  `[tool.coverage.report]` in `pyproject.toml`), then deletes the branch
  whether the job passed or failed

The `test` job needs two repository secrets that are **not** set by this
commit (they're Neon-project-specific and must never be checked in):

| Secret / variable | Value |
| --- | --- |
| `secrets.NEON_API_KEY` | A Neon API key with access to the `ankura` project |
| `vars.NEON_PROJECT_ID` | The Neon project id (not secret, but repo-specific) |
| `secrets.CI_API_KEY_PEPPER` | Any random string ≥16 chars — CI-only, does not need to match any real environment's pepper |

`../.github/dependabot.yml` opens weekly PRs for both the `uv`-managed
dependencies in `backend/` and the GitHub Actions used in `ci.yml` itself.

## Migrations

```bash
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head              # apply
uv run alembic downgrade -1              # roll back one revision
uv run alembic check                     # fails if models and schema disagree
uv run alembic current                   # what revision is this database on
```

Always runs against `DATABASE_DIRECT_URL` (unpooled, `neondb_owner`) — see
`alembic/env.py`'s own docstring; never point it at the pooled app endpoint.
On Windows, `env.py` sets `WindowsSelectorEventLoopPolicy` before connecting
— psycopg3's async mode cannot run on the default `ProactorEventLoop` (same
gotcha as `tests/conftest.py`).

`uv run alembic check` must report no changes after `upgrade head` — if it
doesn't, a model and the schema have drifted. Every migration needs a working
`downgrade()`.

**RLS is hand-written, not autogenerated.** Alembic has no concept of
`ENABLE/FORCE ROW LEVEL SECURITY`, `CREATE POLICY`, or `GRANT`/`REVOKE` — see
migration `0002_row_level_security.py` for the raw `op.execute()` calls that
enable RLS + the `tenant_isolation` policy on the four tenant-scoped tables
and tighten `tenants`/`api_keys` down to `SELECT`-only. `alembic check` only
ever validates the table/column/constraint side of the schema; it says
nothing about RLS or grants being present. When editing that migration,
re-verify by hand against `final architecture.txt` §14.4.

**Bootstrapping a brand-new (empty) database:** `alembic upgrade head`.
**A database that already has this exact schema from before Alembic existed**
(e.g. this repo's own Neon `production` branch, whose tables were created
directly via `Base.metadata.create_all()` in Phase 1 Step 6, before Step 7's
migrations existed): `alembic stamp head` instead — it records the revision
without re-running DDL that would fail on already-existing tables. Confirm
the live schema and the models actually agree first (`alembic check` against
a disposable branch forked from the target, or a manual diff) before
stamping — stamping is a claim, not a verification.

Constraint names are deterministic via `NAMING_CONVENTION` in `db/base.py`
for anything without an explicit `name=` (FKs, PKs). `CheckConstraint` is
deliberately excluded from that convention — SQLAlchemy re-applies the
convention to check constraints even when already explicitly named, which
would double-prefix names that are already final (`ck_tenants_status` →
`ck_tenants_ck_tenants_status`).

## Project layout

```text
src/ankura/
  main.py          FastAPI app factory
  config.py        Settings — fails fast on missing/invalid config
  clock.py          The only permitted source of "now" in the codebase
  db/
    engine.py         Async engine, session factory, RLS tenant-context hook
    models/             SQLAlchemy models (tenants, borrowers, applications, …)
  contracts/           Pydantic canonical request/response/domain models
  api/v1/                Versioned FastAPI routers
  services/               Business logic
  validators/              PAN / GSTIN / Udyam format + checksum validation
alembic/               Migrations (env.py uses DATABASE_DIRECT_URL)
tests/
```

## Current scope (Phase 1)

Multi-tenant application intake API only: auth, validation, idempotency,
audit trail, as-of-time discipline. **No credit logic yet** — no feature
engine, no scoring, no policy engine, no LLM calls. That is intentional; see
`../phase1.txt` for what's in scope and `../ankuraworkflow.txt` Part 11 for
the full phase sequence.

## Conventions

See [`CLAUDE.md`](./CLAUDE.md) in this directory for the full list of
non-negotiable backend conventions (clock discipline, idempotency, money as
integer paise, RLS, contracts-before-tables, canonical metric formulas). Read
it before making structural changes.
