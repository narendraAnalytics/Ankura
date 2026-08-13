"""Canonical financial data shapes — defined now, unused until Phase 7.

Implemented in Phase 1 Step 5: BankTransaction, BankAccountSummary,
GstReturnRecord, BureauSummary, CanonicalFinancialData, DataQuality. Shapes
only — no provider client calls this yet. This is what Phase 2's feature
engine reads and what Phase 7's real providers (Setu AA, GST, bureau) must
normalize into. See ankuraworkflow.txt §5.2 (provider abstraction) and §6.2
(data classes).
"""
