"""PAN / GSTIN / Udyam format and checksum validation.

Implemented in Phase 1 Step 5, used by contracts/common.py. GSTIN validation
must include the checksum digit, not just the structural regex — see
phase1.txt Step 5.
"""
