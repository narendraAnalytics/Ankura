"""Cohort proof asset A1: the drift test. Implemented in Phase 2 Step 5.

Regenerates the cohort in memory (features/generator unchanged) and
compares byte-for-byte against the committed files in `cohort/data/` —
this is what keeps Step 0 D3's "commit the JSON AND keep the generator"
honest. Without this test, the committed cohort would silently become
fiction the first time someone edits `generator.py`/`archetypes.py`
without re-running `python -m ankura.cohort.generate`.
"""

from __future__ import annotations

import json

from ankura.cohort.generate import DATA_DIR, build_cohort_files


def test_committed_cohort_matches_the_generator_byte_for_byte() -> None:
    expected = build_cohort_files()
    committed = {path.name: path.read_text(encoding="utf-8") for path in DATA_DIR.glob("*.json")}
    assert committed == expected


def test_committed_manifest_checksum_matches_a_fresh_regeneration() -> None:
    committed_manifest = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
    fresh_manifest = json.loads(build_cohort_files()["manifest.json"])
    assert committed_manifest["checksum_sha256"] == fresh_manifest["checksum_sha256"]


def test_manifest_cohort_size_is_200() -> None:
    manifest = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cohort_size"] == 200
    assert len(manifest["archetype_assignment"]) == 200


def test_every_committed_file_is_under_the_pre_commit_large_file_cap() -> None:
    """`.pre-commit-config.yaml`'s check-added-large-files hook caps any
    single file at 1000KB (phase2.txt Step 5) — assert it here too, so a
    regenerated cohort that blows the budget fails a fast local test
    instead of only being caught at commit time."""
    max_bytes = 1000 * 1024
    for path in DATA_DIR.glob("*.json"):
        assert path.stat().st_size < max_bytes, path.name
