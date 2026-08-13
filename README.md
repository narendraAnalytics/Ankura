# Ankura

**A governed AI decisioning layer for Indian MSME lending.**

Ankura plugs into an NBFC or LSP's existing loan origination system and turns
consented bank, GST, and bureau data into a credit recommendation that ships
with a complete, reproducible, regulator-ready **Decision Record** — routing
anything uncertain to a human reviewer with the case pre-assembled.

> A consent-driven decisioning component that transforms verified MSME
> financial data into explainable credit recommendations, with mandatory
> human review above configurable thresholds, and a decision that can be
> replayed exactly, months later, against the policy version that produced it.

Ankura is not a lender, not a loan origination system, not an Account
Aggregator, and not "AI that approves loans." It is a technology service
provider: the AI explains, a deterministic policy engine decides the numbers,
and a human owns anything above threshold.

## Why this project, and why now

India's Account Aggregator network and RBI's Unified Lending Interface have
made consented financial data plumbing a commodity — not a differentiator.
What NBFCs lack, and what recent RBI regulation (the Digital Lending
Directions 2025, the FREE-AI framework, and the DPDP Rules) now actively
requires of them, is the ability to **defend an AI-influenced credit decision**:
reproduce it, explain it, show who reviewed it, and prove the policy that
produced it. That gap — not another way to read a bank statement — is what
Ankura builds. The full market analysis and reasoning live in
[`ankuraworkflow.txt`](./ankuraworkflow.txt).

## Repository layout

```text
.
├── README.md                  you are here
├── CLAUDE.md                  project memory / conventions for AI assistants
├── ankuraworkflow.txt         business + technical workflow, market analysis,
│                               regulatory landscape, phase skeleton
├── final architecture.txt     locked technical architecture and stack decisions
├── phase1.txt                 current phase's checkbox-gated build plan
├── smallBusineddloans.txt     original raw research notes (background only)
└── backend/                   FastAPI service — the Decision API
    ├── README.md               backend setup and commands
    └── CLAUDE.md                backend-specific coding conventions
```

A `frontend/` (Next.js reviewer + governance consoles) is planned for a later
phase and does not exist yet — see the phase sequence below.

## Documentation map

| Read this | To understand |
|---|---|
| [`ankuraworkflow.txt`](./ankuraworkflow.txt) | The full picture: why this problem, why now, who pays, the product shape, the 12-phase build sequence, and open decisions |
| [`final architecture.txt`](./final%20architecture.txt) | The locked stack and architecture, including connection-string handling, RLS rules, and canonical metric formulas |
| [`phase1.txt`](./phase1.txt) | What's being built right now, step by step, with pass/fail acceptance checks |
| [`backend/README.md`](./backend/README.md) | How to run the backend locally |
| [`CLAUDE.md`](./CLAUDE.md) / [`backend/CLAUDE.md`](./backend/CLAUDE.md) | Conventions and non-negotiable rules for anyone (human or AI) writing code here |

## Product principles

1. **The Decision Record is the product**, not the credit score. Every
   decision must be reproducible, months later, from stored evidence alone.
2. **The LLM never holds the pen.** Scoring, pricing, and routing are
   deterministic, versioned policy-as-code. The two legitimate LLM surfaces
   are explanation generation and reviewer case-brief synthesis — both
   grounded in already-computed structured evidence, never inventing numbers.
3. **Human-gated by default above threshold.** Small, high-confidence cases
   may auto-decide; everything else goes to a reviewer with a pre-assembled
   brief, not a wall of raw data.
4. **Multi-tenant and audit-first from day one.** Postgres Row Level
   Security, an append-only hash-chained audit trail, and strict as-of-time
   discipline are foundational, not bolted on later.
5. **Bring your own data provider.** Account Aggregator, ULI, and bureau
   integrations sit behind a common interface — Ankura does not lock a lender
   into one AA.

## Current status

**Phase 1 — Foundation** is in progress: a multi-tenant FastAPI service that
accepts an MSME loan application over an authenticated, idempotent API and
stores it under strict tenant isolation with a verifiable audit trail. No
credit logic (scoring, features, policy, LLM) exists yet — that starts in
Phase 2 and Phase 3. See [`phase1.txt`](./phase1.txt) for the live checklist
and [`ankuraworkflow.txt`](./ankuraworkflow.txt) Part 11 for the full
phase-by-phase roadmap (through Phase 9: monitoring and early-warning).

## Getting started

See [`backend/README.md`](./backend/README.md) for setup and local
development instructions.
