# Ankura Synthetic MSME Cohort

This folder contains 200 synthetic MSME borrower profiles — bank
statements, GST filings, and bureau summaries — used to prove Ankura's
credit-decisioning logic works before it ever touches a real lender's
data. Every borrower here is entirely synthetic: no real business, no
real PAN, no real transaction ever appears in this folder.

## Why this exists

A credit-decisioning platform is hard to trust from a slide deck alone.
This cohort lets us show, concretely, that Ankura's numbers behave the
way a credit head would expect: a healthy, growing business scores
differently from one over-leveraged on existing debt, a seasonal trader's
volatility doesn't get mistaken for distress, and known fraud patterns
(GST returns that don't match the bank statement, money moving in a
circle to fake turnover) actually move the numbers that are supposed to
catch them.

Every number in every file was **computed**, not typed in by hand, from
the same formulas the production system uses (see
`../../../../final architecture.txt` §14.2). Nothing here is a mockup.

## The mix (200 borrowers)

| Archetype | Count | What it represents |
| --- | ---: | --- |
| Healthy grower | 50 | Established business, steady growth, low debt, clean books — the ordinary majority of a real loan book |
| Seasonal trader | 30 | Retail/trading business with a genuine festival-season peak (Sep–Nov) and lean trough (Feb–Apr) |
| Declining business | 25 | Revenue genuinely shrinking, bounces creeping up — real financial stress, not fraud |
| Over-leveraged | 25 | A sound business whose existing EMI load is simply too heavy for its income |
| Recovering from stress | 20 | Past trouble visibly on the mend — improving, but not yet fully healthy |
| Thin file | 20 | A genuinely young business: 1–3 months of history, no GST filed yet, no bureau record |
| New to credit | 15 | An established, operating business that has simply never borrowed before |
| GST-vs-bank mismatch (fraud) | 10 | Bank turnover and GST-filed turnover materially disagree |
| Circular transactions (fraud) | 5 | Money moving in a ring between a small set of counterparties to fake turnover |

## What's in a borrower's file

Each `NNNN_ARCHETYPE.json` file (e.g. `0000_HEALTHY_GROWER.json`) is one
borrower's full `CanonicalFinancialData` — the same shape a real bank/GST/
bureau data provider will hand to Ankura in production. It's readable
JSON; open any file directly to see a borrower's bank transactions, GST
returns, and bureau summary in full.

`manifest.json` lists every borrower's archetype assignment, the
generation settings (seed, generator version, "as of" date), and a
checksum over the whole set — proof that this exact 200-borrower cohort
was produced by this exact code, not hand-edited afterward.

## How to regenerate

The cohort is fully deterministic: the same code, run again, produces the
same 200 files byte-for-byte. To regenerate:

```bash
cd backend
uv run python -m ankura.cohort.generate
```

`git status` should show no changes after running this — if it does, the
generator and the committed cohort have drifted apart, which is exactly
what `tests/test_cohort_data.py` checks automatically in CI.
