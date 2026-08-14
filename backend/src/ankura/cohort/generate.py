"""CLI entry point + file-building helpers for the committed synthetic
cohort (phase2.txt Step 5, proof asset A1). Run with:

    uv run python -m ankura.cohort.generate

Regenerates `cohort/data/*.json` + `manifest.json` from the deterministic
generator (Step 4) and OVERWRITES the committed files in place. Per Step
0 D3, both halves are kept honest: the generated JSON is committed so a
human can read/diff a borrower and demos need no generation step, and the
generator itself stays runnable so the cohort can be regenerated and
byte-compared. `tests/test_cohort_data.py`'s drift test is what actually
enforces that the two never quietly diverge — it fails in CI the moment
`generator.py` changes without a matching regeneration commit.

`build_cohort_files()` is pure (no disk I/O) so both this CLI and the
drift test call the exact same code path — the CLI's only job is writing
what that function returns to disk.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from ankura.cohort.archetypes import ARCHETYPES, ArchetypeName
from ankura.cohort.generator import (
    ARCHETYPE_ASSIGNMENT,
    DEFAULT_COHORT_AS_OF,
    GENERATOR_VERSION,
    MASTER_SEED,
    generate_cohort,
)
from ankura.contracts.financial import CanonicalFinancialData

DATA_DIR = Path(__file__).resolve().parent / "data"


def _borrower_filename(index: int, archetype: ArchetypeName) -> str:
    """`NNNN_ARCHETYPE.json` — the archetype in the name is deliberate: a
    credit head browsing `cohort/data/` should be able to tell what a file
    is without opening it (Step 5's "readable, diffable" requirement)."""
    return f"{index:04d}_{archetype.value}.json"


def _checksum(borrowers: list[CanonicalFinancialData]) -> str:
    """SHA-256 over the compact (non-indented) JSON of every borrower, in
    `ARCHETYPE_ASSIGNMENT` order — a single manifest field a reviewer can
    diff to know instantly whether ANY borrower changed, without diffing
    200 files by hand."""
    canonical = "\n".join(b.model_dump_json() for b in borrowers)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_cohort_files(as_of: datetime = DEFAULT_COHORT_AS_OF) -> dict[str, str]:
    """Returns `{filename: file_text}` for all 200 borrowers plus
    `manifest.json` — the complete, in-memory content of `cohort/data/`.
    No disk I/O here; `write_cohort_files()` and the drift test both build
    from this single function so they can never disagree with each other
    by construction."""
    borrowers = generate_cohort(as_of)
    files: dict[str, str] = {}
    for index, (archetype, borrower) in enumerate(
        zip(ARCHETYPE_ASSIGNMENT, borrowers, strict=True)
    ):
        files[_borrower_filename(index, archetype)] = borrower.model_dump_json(indent=2) + "\n"

    manifest = {
        "master_seed": MASTER_SEED,
        "generator_version": GENERATOR_VERSION,
        "as_of": as_of.isoformat(),
        "cohort_size": len(borrowers),
        "archetype_mix": {name.value: spec.count for name, spec in ARCHETYPES.items()},
        "archetype_assignment": [a.value for a in ARCHETYPE_ASSIGNMENT],
        "checksum_sha256": _checksum(borrowers),
    }
    files["manifest.json"] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    return files


def write_cohort_files(output_dir: Path = DATA_DIR) -> None:
    """Overwrite `output_dir` with a fresh regeneration. Existing `*.json`
    files are cleared first so a stale, orphaned borrower file (e.g. from
    a since-changed archetype assignment) can never survive a regeneration
    run — `git status` clean after this is Step 5's own PROVE IT."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for existing in output_dir.glob("*.json"):
        existing.unlink()
    for filename, text in build_cohort_files().items():
        (output_dir / filename).write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    write_cohort_files()
    print(f"Wrote {len(ARCHETYPE_ASSIGNMENT)} borrowers + manifest.json to {DATA_DIR}")


if __name__ == "__main__":
    main()
