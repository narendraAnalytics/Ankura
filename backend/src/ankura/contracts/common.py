"""Shared canonical types: Money, PAN, GSTIN, Udyam, AsOf, shared enums.

Implemented in Phase 1 Step 5 (canonical contracts) — see phase1.txt Step 5
for the exact checklist. Rules that apply to every type defined here:
  - money is integer paise, never float
  - GSTIN validation includes the checksum digit, not just a regex
  - every contract sets model_config = ConfigDict(extra="forbid", ...)
  - every contract's docstring names which later phase consumes it

Written BEFORE any database table — final architecture.txt §14.1.
"""
