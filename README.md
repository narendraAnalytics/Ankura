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

`pre-commit` runs these plus `gitleaks` (secret scanning) automatically:

```bash
uv run pre-commit install
```

## Migrations

```bash
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
```

Autogenerate must report an empty diff immediately after `upgrade head` — if
it doesn't, a model and the schema have drifted. Every migration needs a
working `downgrade()`.

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
