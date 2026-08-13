# Ankura Backend — Project Memory

Read `../CLAUDE.md` first for product context. This file is backend-specific:
stack conventions, patterns, and gotchas that apply while writing code here.

## Current status

Phase 1 Steps 0-6 done. Foundation (0-3): decisions frozen, `src/ankura`
package skeleton, dependencies finalized, `config.py` fail-fast settings.
Database (4-6): `db/engine.py` has a live async engine against Neon's
"ankura" project connecting as `ankura_app` (dedicated non-owner role,
verified via `pg_roles`, never the schema owner); `contracts/` has PAN/
GSTIN (Mod-36 checksum hand-verified against a real GSTIN before any code
was written)/Udyam validators, `MoneyPaise` (INR-only), `AsOf`/
`UtcDatetime`, and the `ApplicationIn`/`Out`/`CanonicalFinancialData`
shapes; and the full schema (`db/models/`: tenants, api_keys, borrowers,
applications, audit_events, idempotency_keys) is live in Neon with Row
Level Security on the 4 genuinely tenant-scoped tables — deliberately NOT
on tenants/api_keys, which are bootstrap/auth tables (see db/base.py for
why). A real RLS bug was found and fixed live this step: the policy needed
`NULLIF(current_setting('app.tenant_id', true), '')::uuid`, not bare
`current_setting(...)`, or a reused pooled connection with no context set
raises instead of cleanly returning zero rows — see final architecture.txt
§14.4. Verified isolation at three levels (ORM, no-context session, and
raw SQL with zero ORM connected genuinely as ankura_app). Full suite
89/89 passing live against Neon, ruff clean, mypy clean. Next up is Step 7
(Alembic migrations) — see `../phase1.txt` (Step 7 must `alembic stamp
head` on the existing "production" branch, not `upgrade head`, since this
schema already exists there).

## Source of truth for architecture

`../final architecture.txt` is the locked technical decision record, including
the §14 addendum (connection strings, RLS rules, canonical metric formulas).
`../phase1.txt` is the current phase's checklist. Follow both exactly; do not
improvise structure that contradicts them without flagging it to the user
first — architecture changes get written back into `final architecture.txt`,
not left implicit in a diff.

## Stack (locked)

- Python 3.12, managed with **uv** (`uv sync`, `uv run …`) — never bare `pip`
- FastAPI + Pydantic v2, SQLAlchemy 2 (async), Alembic, psycopg3
- Postgres: **Neon** in dev, **Cloud SQL (asia-south1)** in prod — app code
  stays portable, no provider-specific SQL features
- LangGraph for orchestration (from Phase 4 onward — not used yet), hosted on
  **Vertex AI / Gemini Enterprise Agent Platform (Agent Runtime)** — not
  embedded in-process on Cloud Run. Cloud Run hosts the FastAPI service
  itself. Locked 2026-08-13, see `../final architecture.txt` §15.
- Gemini via Vertex AI for the two bounded LLM surfaces only (from Phase 5),
  called from inside the Agent Runtime-hosted graph
- Firebase Auth for the human-facing consoles only (from Phase 4) — Phase 1's
  API uses tenant API keys, not Firebase
- Testing: pytest + pytest-asyncio + pytest-cov; ruff + mypy for quality gates

Dependencies for later phases (`langgraph`, `langchain-google-genai`,
`firebase-admin`, `google-cloud-*`) are already in `pyproject.toml` on
purpose — do not import them before their phase arrives.

## Layout

Skeleton created Phase 1 Step 1 (2026-08-13). Most non-`__init__.py`
modules are still docstring-only stubs naming the step that fills them in —
`config.py` (Step 3), `db/engine.py` (Step 4), `contracts/` and
`validators/identifiers.py` (Step 5), and `db/base.py` + all of
`db/models/` (Step 6) are implemented. Check a module's docstring before
assuming it's unimplemented vs. just not-yet-reached.

```
backend/
  src/ankura/
    main.py            FastAPI app factory (routes wired in Step 8)
    config.py           IMPLEMENTED (Step 3) — fail-fast pydantic-settings,
                         residency guard, assert_expected_db_role()
    clock.py             THE ONLY source of current time — Step 10
    db/
      engine.py           IMPLEMENTED (Step 4) — async engine (ankura_app,
                           not owner), get_db_session(), set_tenant_context()
      base.py               IMPLEMENTED (Step 6) — DeclarativeBase,
                           TimestampMixin, RLS scope decision documented here
      models/               IMPLEMENTED (Step 6) — tenant, api_key (both
                           deliberately NOT RLS-scoped, see base.py),
                           borrower, application, audit, idempotency (RLS)
    contracts/            IMPLEMENTED (Step 5) — common, application,
                           financial (write these BEFORE tables —
                           final architecture.txt §14.1)
    api/
      deps.py               auth, tenant resolution, session, clock — Step 8
      errors.py             error envelope + handlers — Step 8
      v1/                    health, applications, tenants — Step 8
    services/              applications, idempotency (Step 9), audit (Step 11)
    validators/             IMPLEMENTED (Step 5) — identifiers.py, PAN/GSTIN
                           checksum/Udyam
  alembic/                 not created yet — Step 7 wraps the schema (already
                          live in Neon since Step 6) into real migrations
  tests/                  one file per step's test target (see phase1.txt);
                          test_tenant_isolation.py (Step 6) now has 5 real
                          tests against live Neon, not a stub
  .env.example             keys named, values blank — populated in Step 3
```

## Rules that must never be silently broken

**Clock discipline.** `datetime.now()`, `datetime.utcnow()`, `date.today()`,
`time.time()` are banned everywhere except `clock.py`. Every request has an
explicit `as_of` (business time) distinct from `recorded_at` (wall-clock write
time). This exists so P3's decision replay is possible; retrofitting it later
is a rewrite, not a patch.

**Idempotency.** Every mutating POST requires an `Idempotency-Key` header.
Same key + same body → replay stored response. Same key + different body →
409. The idempotency record and the entity it protects are written in the
*same* transaction.

**Money.** Integer paise (`amount_paise: int`), never `float`, never
`Decimal` unless a specific calculation demands it and it's converted back to
paise before storage.

**Row Level Security, not just app-layer filters.** Every tenant-scoped table:
`ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY`, policy against
`current_setting('app.tenant_id')`, set via `SET LOCAL` per transaction (never
plain `SET` — it leaks across pooled connections). The app DB role must be a
non-owner, non-superuser — owners bypass RLS silently. `tenant_id` is the
leading column of every index on a tenant table. When testing isolation,
temporarily strip the ORM's own `WHERE tenant_id = …` filter and confirm RLS
alone still blocks cross-tenant reads — that's the real test.

**Two Neon connection strings.** `DATABASE_URL` (pooled, `…-pooler.neon.tech`)
for the app; `DATABASE_DIRECT_URL` (unpooled) for Alembic only. Neon's pooler
runs PgBouncer in transaction mode, which breaks session-level prepared
statements — psycopg3 handles this better than asyncpg but still needs
`prepare_threshold` set deliberately.

**Contracts before tables.** Every DB table is derived from a Pydantic model
in `contracts/`, written first. Don't invent a column that has no contract.

**Canonical metric formulas live in exactly one place** (feature engine
module, arriving Phase 2) and are documented in `final architecture.txt` §14.2
— `dscr`, `obligation_ratio` (not "FOIR" — that's a retail concept),
`bounce_ratio`, `bank_gst_gap`, `cash_deposit_ratio`, `customer_concentration`.
Synthetic ground-truth borrowers (Phase 2) must be generated *from* these
formulas, never hand-typed to a plausible-looking number.

**No credit logic in Phase 1.** Scoring, features, policy evaluation, pricing
— none of it belongs yet. If you're writing a DSCR calculation while working
Phase 1 steps, stop; that's Phase 2/3 scope.

## Testing expectations

- `test_tenant_isolation.py` must pass with the ORM's tenant filter removed
  (proves RLS, not app code, is the actual boundary).
- `test_clock_discipline.py` greps the source tree for banned time calls.
- `test_idempotency.py` includes a concurrent-duplicate-request case, not just
  sequential replay.
- Coverage gate: 80% on `src/ankura`, enforced in CI.

## Commands

```bash
uv sync                          # install deps
uv run fastapi dev src/ankura/main.py   # local dev server
uv run pytest                    # tests
uv run pytest --cov=ankura       # with coverage
uv run ruff check . && uv run ruff format --check .
uv run mypy src/ankura
uv run alembic upgrade head       # migrations (uses DATABASE_DIRECT_URL)
```
