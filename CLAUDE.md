# Ankura — Project Memory

This file orients any AI assistant (or human) working in this repository. Read
it before touching code or planning docs.

## What this project is

Ankura is a **governed AI decisioning layer for Indian MSME lenders** — not a
lender, not a data aggregator, not a LOS. It plugs into an NBFC/LSP's existing
loan origination system via API, turns consented bank + GST + bureau data into
a reproducible, explainable, human-gated credit decision, and hands back a
**Decision Record** the lender can show a regulator or auditor on demand.

The one-line pitch (do not drift from this framing in code, naming, or docs):

> A consent-driven decisioning component that transforms verified MSME
> financial data into explainable credit recommendations, with mandatory human
> review above configurable thresholds, and a decision that can be replayed
> exactly, months later, against the policy version that produced it.

**The product being sold is the Decision Record — reproducibility and audit
defensibility — not the credit score.** The data-aggregation layer (AA/ULI) is
commodity infrastructure in 2026, not a differentiator. See
`ankuraworkflow.txt` Part 0–2 for the full reasoning; do not re-litigate it
without new information.

## Document map — read in this order

| File | Purpose | When to open it |
|---|---|---|
| `ankuraworkflow.txt` | Full business + technical workflow: market analysis, regulatory landscape, product shape, phase skeleton, open decisions | Understanding *why* before *what* |
| `final architecture.txt` | Locked technical architecture + stack decisions, including the §14 addendum with formulas, connection strings, and RLS rules | Before writing any backend code |
| `phase1.txt` | Current phase's checkbox-gated build plan | Day-to-day implementation reference |
| `smallBusineddloans.txt` | Original raw research notes on AA/GST/Setu mechanics | Background only — superseded where it conflicts with the two files above |
| `backend/CLAUDE.md` | Backend-specific conventions (stack, patterns, gotchas) | Whenever editing `backend/` |
| `backend/README.md` | Backend setup/run instructions | Environment setup |

**Precedence when documents disagree:** `final architecture.txt` > `ankuraworkflow.txt`
> `smallBusineddloans.txt`. If a phase teaches something that changes an
architecture decision, amend `final architecture.txt`, not the phase file.

## Non-negotiable product rules

These come from the regulatory reframe (RBI Digital Lending Directions 2025,
FREE-AI framework, DPDP Rules 2025) and from hard architecture decisions. Do
not silently violate them while "just getting something working."

1. **The LLM is never load-bearing for the credit decision.** All scoring,
   thresholds, pricing, and routing are deterministic Python/policy-as-code.
   The only legitimate LLM surfaces are (a) explanation generation from
   already-computed structured evidence, and (b) reviewer case-brief
   synthesis. Neither may compute a number the LLM invents.
2. **Two agents, not six.** Do not resurrect the six-chatbot framing from the
   early research docs. Orchestrator, data aggregation, underwriting, and
   pricing are deterministic code orchestrated by LangGraph as a state
   machine — not LLM agents.
3. **Every decision must be replayable.** No `datetime.now()` / `utcnow()`
   outside the clock module. Every mutating action pins the versions that
   produced it (policy version, feature engine version, model version).
4. **Multi-tenant from day one, enforced in the database.** Postgres RLS,
   `FORCE ROW LEVEL SECURITY`, non-owner app role, `SET LOCAL` per
   transaction — never only an application-layer `WHERE tenant_id = …`.
5. **Money is integer paise, never float.**
6. **Raw financial payloads (bank/GST/bureau) are short-retention and never
   land in a vector store or a log line.** Derived features are the durable
   artefact.
7. **No secrets in code, env files in git, or documents in this repo.** If a
   provider credential ever appears in a committed file, treat it as
   compromised and rotate it — see `final architecture.txt` §14.5.
8. **Cloud Run hosts the API; Vertex AI / Gemini Enterprise Agent Platform
   (Agent Runtime) hosts the LangGraph graph**, from Phase 4 onward — locked
   2026-08-13, see `final architecture.txt` §15. Do not re-litigate this or
   embed the graph in-process on Cloud Run instead.

## Current status

Phase 1 (Foundation) is in progress. Steps 0-9 done: open decisions frozen,
package skeleton, dependencies, fail-fast config, a live async DB engine
against Neon (connecting as a dedicated non-owner role, `ankura_app`, never
the schema owner), the canonical contracts (PAN/GSTIN/Udyam validators —
GSTIN's Mod-36 checksum hand-verified against a real GSTIN before any code
was written — `MoneyPaise` INR-only, `AsOf`/`UtcDatetime`, application and
financial-data shapes), the full multi-tenant schema live in Neon with Row
Level Security enforced on every genuinely tenant-scoped table, and that
same schema now also expressed as real Alembic migrations (0001 tables,
0002 RLS/policies/grants — RLS is hand-written raw SQL, Alembic can't
autogenerate it). One deliberate exception: `tenants`/`api_keys` are NOT
RLS-scoped — they're bootstrap/auth tables that establish tenant identity,
so RLS-gating them on a tenant_id you don't have yet would be circular;
this is the standard pattern, not a gap. A live RLS bug was found and
fixed in Step 6 (policy needed `NULLIF(current_setting(...), '')::uuid`,
not a bare `current_setting` call, or a reused connection with no tenant
context set raised an error instead of cleanly returning no rows) — see
`final architecture.txt` §14.4. Step 7 proved the migrations on a
disposable Neon branch (full upgrade/downgrade/upgrade + empty-diff cycle)
before `alembic stamp head`-ing the real `production` branch, since that
branch's schema already existed from Step 6's direct `create_all()`. Step 8
built the application intake API on top of all this: tenant API key auth
(HMAC-SHA256 + pepper, not a slow password KDF — API keys are high-entropy
secrets, not human passwords), a single `{error:{code,message,details,
request_id}}` envelope for every rejection, and `POST`/`GET
/v1/applications` with keyset (cursor) pagination and an atomic
`INSERT ... ON CONFLICT DO UPDATE` borrower upsert (never SELECT-then-
INSERT, which would race). Building it required pulling two things forward
out of their own later steps: a minimal `Clock` protocol + `SystemClock`
(Step 10 still owns `FrozenClock` and the banned-`datetime.now()` grep
test), and a new `security.py` module for the key hashing. Step 9 made
POST /v1/applications idempotent: `Idempotency-Key` is required (missing →
400), and the request is served by claiming `(tenant_id, key)` with a
placeholder row *before* the underlying work runs, then finalizing it with
the real response afterward, all inside one SAVEPOINT nested in the
request's own transaction — claiming before the work, not after, is what
makes two truly concurrent identical requests block on the idempotency
table's own unique index instead of racing each other straight into
`applications`' own unique constraints. See `backend/CLAUDE.md` for the
concurrency-bug story and the JSONB key-ordering fix that byte-identical
replay needed. See `phase1.txt` for the live checklist and what's next. No
credit logic, feature engine, or LLM integration exists yet by design —
Phase 1 is the multi-tenant API + schema + audit spine only.

## Working conventions for this repo

- This is a monorepo: planning docs and a single `.git` at the project root,
  code inside `backend/` as an ordinary subfolder (not a nested repo). A
  `frontend/` (Next.js) will appear alongside it in a later phase — do not
  create it early.
- Planning docs are plain `.txt`, not Markdown, by the user's existing
  convention. Keep new planning docs in that format unless asked otherwise.
- Checkbox files (`phase1.txt` and future `phaseN.txt`) are living documents:
  tick a box only when its own "PROVE IT" line is actually verified, not when
  the code merely exists.
- When a phase surfaces a decision that changes the locked architecture,
  update `final architecture.txt` directly (see its own §14 pattern) rather
  than leaving the correction implicit in code.
- Search the web for anything time-sensitive (RBI circulars, AA ecosystem
  stats, competitor positioning) before asserting it as current — this market
  moves fast and the assistant's training data lags it.
