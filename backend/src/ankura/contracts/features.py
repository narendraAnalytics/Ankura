"""FeatureSnapshot — the feature engine's OUTPUT shape (Phase 2 Step 2).

This module declares the SHAPE only. It computes nothing — `features/
metrics.py` (Step 1) owns the formulas, `features/engine.py` (Step 6) owns
turning a `CanonicalFinancialData` into an instance of this contract. Keeping
the shape and the computation in separate modules is what stops the engine
from growing a second, informal copy of §14.2's field list.

Every §14.2 metric is `float | None`, never silently `0.0` — a `None` here
means the underlying metric's denominator was structurally zero (see
`features/metrics.py` per-metric docstrings for which cases apply), and that
undefined-ness must survive all the way into data_quality, not get coerced
into a number that would later look like a real measurement.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ankura.contracts.common import AsOf, UtcDatetime
from ankura.contracts.financial import DataQuality


class ProvenanceEntry(BaseModel):
    """Which source contributed to a snapshot, and that source's own as_of —
    required by both the Decision Record (P3) and P5's explanation layer;
    retrofitting provenance later is a rewrite (phase2.txt Step 2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1, max_length=32)
    """"bank", "gst", or "bureau" — matches CanonicalFinancialData's own
    source shapes, not a free-form label."""

    source_as_of: AsOf
    """The source's own as-of time — e.g. a GST return's filing period end,
    a bank statement's period end. Distinct from the snapshot's own as_of."""

    months_used: list[str] = Field(default_factory=list)
    """YYYY-MM periods actually consumed from this source. Lets a reviewer
    see the aligned window (Step 8's bank/GST alignment requirement) without
    re-deriving it from raw data that, per D9, is never persisted."""


class FeatureSnapshot(BaseModel):
    """Versioned, provenance-carrying output of `compute_features()`
    (Step 6). Immutable once computed (Step 9) — recomputation produces a
    NEW snapshot with a new `feature_engine_version`, never an overwrite."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    application_id: UUID

    as_of: AsOf
    """Business time this snapshot reasons about — the window boundary the
    engine windowed data relative to."""

    computed_at: UtcDatetime
    """Wall-clock time this snapshot was computed. Distinct from as_of —
    two snapshots can share an as_of (recomputed under a new engine
    version) but never a computed_at."""

    feature_engine_version: str = Field(min_length=1, max_length=32)
    """Pins `features.metrics.FEATURE_ENGINE_VERSION` at computation time —
    CLAUDE.md rule 3: every mutating action pins the versions that produced
    it."""

    input_hash: str = Field(min_length=64, max_length=64)
    """SHA-256 hex digest of the canonicalized `CanonicalFinancialData` that
    produced this snapshot. Lets Phase 3's replay endpoint prove "same
    input, same engine version, same output" without ever persisting the
    raw payload itself (D9)."""

    # --- final architecture.txt §14.2 metrics, one field each -------------
    dscr: float | None
    obligation_ratio: float | None
    bounce_ratio: float | None
    bank_gst_gap: float | None
    cash_deposit_ratio: float | None
    customer_concentration: float | None
    supplier_concentration: float | None

    data_quality: DataQuality
    provenance: list[ProvenanceEntry] = Field(default_factory=list)
