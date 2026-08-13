"""Clock discipline test. Implemented in Phase 1 Step 10.

Greps the source tree and fails the build on any banned time call
(datetime.now/.utcnow, date.today, time.time) outside clock.py — see
phase1.txt Step 10 PROVE IT.
"""
