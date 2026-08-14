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
| `endgoal.txt` | The full end-to-end product narrative (intake → ... → Decision Record → LOS) and the P1-P10 phase table | Orientation — what the finished product looks like and where the current phase sits in it |
| `ankuraworkflow.txt` | Full business + technical workflow: market analysis, regulatory landscape, product shape, phase skeleton, open decisions | Understanding *why* before *what* |
| `final architecture.txt` | Locked technical architecture + stack decisions, including the §14 addendum with formulas, connection strings, and RLS rules, and §16's Phase 1 close-out patterns | Before writing any backend code |
| `phase2.txt` | **Current phase's** checkbox-gated build plan (synthetic cohort + feature engine) | Day-to-day implementation reference |
| `phase1.txt` | Completed phase's build plan — full step-by-step history, every gotcha found live, kept for reference | Understanding how/why P1 ended up the way it did |
| `smallBusineddloans.txt` | Original raw research notes on AA/GST/Setu mechanics | Background only — superseded where it conflicts with the files above |
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

**Phase 1 (Foundation) is COMPLETE** — tagged `p1-foundation`, all 12 steps
done and live-verified against real Neon (not just re-run tests): multi-
tenant schema with Row Level Security enforced at the database (not app
code), tenant API key auth, validated + idempotent application intake
(`POST /v1/applications`, claim-before-work idempotency, byte-identical
replay proven via real curl), as-of/clock discipline (`Clock` protocol +
`FrozenClock`, ruff-enforced ban on ad hoc `datetime.now()`), an append-
only hash-chained audit trail (tamper detection proven), and CI + pre-
commit quality gates + secret scanning (the repo switched to a PR-based
workflow starting at this step — direct pushes to `main` are now blocked).
Full step-by-step history, every gotcha found live, and the exact PROVE IT
verification for each item lives in `phase1.txt` (gitignored, local-only —
see `backend/CLAUDE.md` for the same history in more implementation
detail) and in the git log up to the `p1-foundation` tag. No credit logic,
feature engine, or LLM integration exists yet — Phase 1 was deliberately
the multi-tenant API + schema + audit spine only.

`final architecture.txt` §16 (added on Phase 1 exit) captures five
implementation patterns for Phase 2/3 to adopt from the start rather than
rediscover: audit/ledger writes need their own transaction, decoupled from
the request they describe (a rejection/failure must not erase the row
recording it); idempotency must claim before doing the work, not after;
`SELECT ... FOR UPDATE` needs UPDATE privilege an append-only role
deliberately lacks — use a Postgres advisory lock instead; chain/ledger
ordering must walk by hash pointer, never by `recorded_at`/timestamp
(Postgres's `now()` is constant for a whole transaction); and dev Neon
runs in `aws-us-east-2`, confirmed not a residency violation since the
`ENV=prod`-only guard never applied to it.

**Phase 2 (synthetic cohort + deterministic feature engine) is underway.**
Plan is in `phase2.txt` (gitignored, local-only, same checkbox/PROVE-IT
format as `phase1.txt`) — goal: turn a `CanonicalFinancialData` object into
a versioned, provenance-carrying `FeatureSnapshot` using formulas pinned
exactly once (`final architecture.txt` §14.2), plus the 200-borrower
synthetic cohort (`ankuraworkflow.txt` §7.3/§9.5 proof asset A1) generated
FROM those formulas, seeded and committed to the repo. No policy, no
scorecard, no routing, no LLM — the feature engine computes numbers, it
never decides anything with them (that's Phase 3). Step 0 (nine open
decisions — cohort size/mix, ratio rounding, proposed-EMI convention,
etc.), Step 1 (`backend/src/ankura/features/metrics.py` — all seven
§14.2 metrics, pure functions, hand-computed tests), Step 2 (grew
`CanonicalFinancialData`, defined `FeatureSnapshot`), and Step 3
(`backend/src/ankura/cohort/archetypes.py` — all nine D2 archetypes as
declarative specs with range/direction expected feature signatures), and
Step 4 (`backend/src/ankura/cohort/generator.py` — the deterministic,
seeded generator that turns each archetype spec into a real
`CanonicalFinancialData`, values solved backward from the pinned §14.2
formulas rather than hand-typed, verified byte-identical across both
same-process and cross-process regeneration), Step 5 (the 200-borrower
cohort — proof asset A1 — generated and committed to
`backend/src/ankura/cohort/data/`, one JSON file per borrower plus a
manifest with a checksum over the whole set, regenerable via
`uv run python -m ankura.cohort.generate`, with a drift test keeping the
committed files and the generator from silently diverging), and Step 6
(`backend/src/ankura/features/engine.py` — `compute_features()`, this
phase's centrepiece: windows a `CanonicalFinancialData` to a trailing
12 months relative to `as_of`, aggregates it, and calls the pinned
metric formulas, with no thresholds/bands/decisions anywhere in it;
proven replayable byte-for-byte, and all 200 committed cohort borrowers
verified against their own archetype's expected signature through this
real engine) are done. A real bug was found and fixed while wiring Step 6
up: the generator could date a transaction after `as_of`, which the
engine's correct as_of-cutoff windowing then silently excluded while the
generator's own totals had counted it — fixed in the generator, cohort
regenerated. See `backend/CLAUDE.md` for implementation-level detail and
`endgoal.txt` (gitignored, local-only) for the full end-to-end product
narrative these phases are building toward.

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
