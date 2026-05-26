"""
CCQS V1 — Composite Score & Grading (SPEC Section 9)

Bayesian-averaged composite over the 6-state probability distribution:

    ccqs_z   = Σ_state p_adj(state) · Σ_comp w[state][comp] · z_comp
    ccqs_raw = Φ(ccqs_z) · 100              (normal CDF → percentile)
    ccqs     = clip(ccqs_raw, p1_d, p99_d)  (per-date winsorization)

Grades (SPEC §9):

    ccqs ≥ 85  → S
    ccqs ≥ 80  → A
    ccqs ≥ 75  → B
    ccqs ≥ 70  → C
    else       → D

Run:
    python -m compute.ccqs
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from scipy.stats import norm

from compute.loader import CACHE_DIR, LOG_DIR
from compute.components import COMPONENT_COLS
from compute.state import STATES, PROB_ADJ_COLS

COMPONENTS_PATH = CACHE_DIR / "components.parquet"
STATE_PATH = CACHE_DIR / "state.parquet"
CCQS_PATH = CACHE_DIR / "ccqs.parquet"
CCQS_META_PATH = CACHE_DIR / "ccqs_meta.json"

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")
logger.add(LOG_DIR / "ccqs.log", level="DEBUG", rotation="10 MB", retention="30 days")


# State-conditional component weights (SPEC §8 matrix).
# Columns: TRENDING, PULLBACK, CONSOLIDATING, EXHAUSTION, DETERIORATING, INDETERMINATE
# Rows must sum to 1.0 per state.
#
# Phase X.2.1 — FIX 2: S_CLIMAX zeroed in every state (mean OOS IC = -0.0242,
# significantly negative at two horizons). Phase 6: removed from the component
# set entirely — the field carried zero weight everywhere and its math was
# inverted vs its name (high s_climax meant "less climactic"). Component
# dimension dropped from 10 → 9. The underlying features (climax_volume_flag,
# days_near_52w_high_60d, consecutive_high_intensity) are still computed and
# consumed by state classification and the setup classifier.
#
# Phase X.3 (M8 — component cleanup): redistribute weight from the four
# zero/negative-OOS-IC components (s_rsl -0.0013, s_trend_slope -0.0001,
# s_extension -0.0070, s_momentum 0.0000) to the four proven positive-OOS
# carriers (s_rs +0.0272, s_rs_leadership +0.0266, s_structure +0.0185,
# s_mtf +0.0154). Cumulative weight on zero-contribution components drops
# from 29% (post-X.2.1) → 8-10% (post-X.3, depending on state).
#
# Phase 7 (Priority 3a — s_demand removal, 2026-05-25): The Priority 2 bootstrap
# analysis flagged s_demand as the next removal candidate — average OOS IC
# −0.009 across the 24 (state × horizon) cells, 6/24 cells significantly
# negative. s_demand zeroed; freed 10-15% per state redistributed to the four
# carriers (s_rs, s_rs_leadership, s_structure, s_mtf). 126d walk-forward
# t-stat crossed institutional 2.0 threshold (1.82 → 2.02). See SPEC §"Phase 7".
#
# Phase 8a (Residual Momentum addition — Config B, 2026-05-26): added the new
# `s_residual_momentum` component (beta-adjusted idiosyncratic momentum, see
# components.py). Weight: ~5% per state, pulled proportionally from the three
# smallest-weight existing components (`s_rsl`, `s_trend_slope`, `s_momentum`)
# wherever they had slack. For EXHAUSTION — where those three only summed to
# 3% — the SHRINK targets are zeroed and the missing 2% is implicitly absorbed
# by the row-renormalization (final s_residual_momentum effective weight in
# EXHAUSTION is 4.90%, slight from 5.00% in the other five states).
#
# Validation (in-memory Phase 8a investigation): Standalone IC at 126d-fwd =
# +0.0466 (t=14.4). Orthogonal-to-`s_rs` IC at 126d-fwd: +0.0246, t=+8.63.
# Per-date paired bootstrap: 60d Δ +0.0016 CI [+0.0004, +0.0029], 126d Δ
# +0.0020 CI [+0.0007, +0.0031]. Walk-forward paired t-test: 60d t=2.05,
# 126d t=2.72. 23 of 24 (state × horizon) cells improve. Known weak regimes
# (mega-caps, HIGH market vol, defensive sectors, 2021 meme/SPAC year) all
# improve. One mild regression: 2020 long horizons (−0.003 / −0.005),
# same direction as the documented Phase 7 COVID caveat.
STATE_WEIGHTS: dict[str, dict[str, float]] = {
    "TRENDING": {
        "s_rs": 0.280120, "s_rs_leadership": 0.280120, "s_residual_momentum": 0.050000,
        "s_rsl": 0.008571, "s_trend_slope": 0.008571, "s_structure": 0.201687,
        "s_mtf": 0.168072, "s_extension": 0.000000, "s_demand": 0.000000,
        "s_momentum": 0.002857,
    },
    "PULLBACK": {
        "s_rs": 0.256203, "s_rs_leadership": 0.291139, "s_residual_momentum": 0.050000,
        "s_rsl": 0.005000, "s_trend_slope": 0.003333, "s_structure": 0.209620,
        "s_mtf": 0.163038, "s_extension": 0.020000, "s_demand": 0.000000,
        "s_momentum": 0.001667,
    },
    "CONSOLIDATING": {
        "s_rs": 0.237975, "s_rs_leadership": 0.261772, "s_residual_momentum": 0.050000,
        "s_rsl": 0.000000, "s_trend_slope": 0.000000, "s_structure": 0.261772,
        "s_mtf": 0.178481, "s_extension": 0.010000, "s_demand": 0.000000,
        "s_momentum": 0.000000,
    },
    "EXHAUSTION": {
        "s_rs": 0.255628, "s_rs_leadership": 0.325345, "s_residual_momentum": 0.049020,
        "s_rsl": 0.000000, "s_trend_slope": 0.000000, "s_structure": 0.185912,
        "s_mtf": 0.174292, "s_extension": 0.009804, "s_demand": 0.000000,
        "s_momentum": 0.000000,
    },
    "DETERIORATING": {
        "s_rs": 0.237500, "s_rs_leadership": 0.296875, "s_residual_momentum": 0.050000,
        "s_rsl": 0.000000, "s_trend_slope": 0.000000, "s_structure": 0.237500,
        "s_mtf": 0.178125, "s_extension": 0.000000, "s_demand": 0.000000,
        "s_momentum": 0.000000,
    },
    "INDETERMINATE": {
        "s_rs": 0.249877, "s_rs_leadership": 0.295309, "s_residual_momentum": 0.050000,
        "s_rsl": 0.008571, "s_trend_slope": 0.008571, "s_structure": 0.204444,
        "s_mtf": 0.170370, "s_extension": 0.010000, "s_demand": 0.000000,
        "s_momentum": 0.002857,
    },
}

# Normalize each state's weights to sum to 1.0. The SPEC matrix presents
# whole-percent values that round to 100-103 per column; we treat them as
# proportional and renormalize so Bayesian averaging is well-defined.
for s, ws in STATE_WEIGHTS.items():
    total = sum(ws.values())
    if abs(total - 1.0) > 1e-9:
        STATE_WEIGHTS[s] = {k: v / total for k, v in ws.items()}


def _state_composite_z(components: pd.DataFrame, state: str) -> pd.Series:
    """Weighted sum of component z-scores under one state's weights."""
    w = STATE_WEIGHTS[state]
    z = sum(w[c] * components[c].astype(float) for c in COMPONENT_COLS)
    return z


def _per_date_zscore(s: pd.Series) -> pd.Series:
    """Cross-sectional z-score per date (no MAD; uses mean/std)."""
    g = s.groupby(level="date", sort=False)
    mean = g.transform("mean")
    std = g.transform("std").replace(0.0, 1.0)
    return (s - mean) / std


def _per_date_winsorize(s: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    """Cross-sectional winsorization per date.

    Clips each row against its own date's lower/upper quantiles. NaN values
    are preserved. A date with all-NaN inputs produces all-NaN output.
    """
    g = s.groupby(level="date", sort=False)
    lo = g.transform(lambda x: x.quantile(lower))
    hi = g.transform(lambda x: x.quantile(upper))
    return s.clip(lower=lo, upper=hi)


def compute_ccqs(components: pd.DataFrame, state: pd.DataFrame) -> pd.DataFrame:
    """
    Returns (per row):
        ccqs_z, ccqs_raw, ccqs, grade, primary_state, state_confidence
    """
    # State-conditional composite z per state, then Bayesian average
    # using confidence-adjusted probabilities.
    ccqs_z_raw = pd.Series(0.0, index=components.index)
    for s in STATES:
        p = state[f"p_adj_{s}"].astype(float).fillna(0.0)
        ccqs_z_raw = ccqs_z_raw + p * _state_composite_z(components, s)

    # The weighted-sum composite has var ≈ Σ wᵢ² ≈ 0.14, much narrower than
    # N(0,1). Renormalize per-date so Φ(z)·100 spans the full 0-100 range
    # and SPEC §9 grade thresholds (85/80/75/70) align with their target
    # tier sizes. The 'ccqs_z' column reports the normalized score.
    ccqs_z = _per_date_zscore(ccqs_z_raw)

    # Convert to 0-100 percentile.
    ccqs_raw = pd.Series(norm.cdf(ccqs_z.to_numpy(dtype=float)) * 100.0, index=ccqs_z.index)

    # Per-date winsorization at 1st / 99th percentiles. The earlier global clip
    # (computed once across the entire long frame) produced ~24k exact ties at
    # the floor/ceiling because every date with extreme scores collapsed to the
    # same two values. Per-date clipping preserves cross-sectional dispersion
    # within each date — clips ~1% of each date's universe at that date's local
    # tails, so ties remain only within a single date (no global collisions).
    # Grade assignment is unchanged (grades use per-date quantiles regardless).
    ccqs = _per_date_winsorize(ccqs_raw, lower=0.01, upper=0.99)

    # Grade (S/A/B/C/D) by per-date cross-sectional percentile rank.
    # Targets: S top 8% (q92), A next 12% (q80), B next 25% (q55),
    # C next 25% (q30), D bottom 30%. Absolute thresholds drift with the
    # universe's mean quality, so per-date quantiles keep tier sizes stable.
    grade = pd.Series(np.nan, index=ccqs.index, dtype=object)
    valid = ccqs.notna()
    if valid.any():
        g = ccqs[valid].groupby(level="date", sort=False)
        q30 = g.transform(lambda s: s.quantile(0.30))
        q55 = g.transform(lambda s: s.quantile(0.55))
        q80 = g.transform(lambda s: s.quantile(0.80))
        q92 = g.transform(lambda s: s.quantile(0.92))
        v = ccqs[valid]
        gr = pd.Series("D", index=v.index, dtype=object)
        gr[v >= q30] = "C"
        gr[v >= q55] = "B"
        gr[v >= q80] = "A"
        gr[v >= q92] = "S"
        grade[valid] = gr

    out = pd.DataFrame(index=components.index)
    out["ccqs_z"] = ccqs_z
    out["ccqs_raw"] = ccqs_raw
    out["ccqs"] = ccqs
    out["grade"] = pd.Categorical(grade, categories=["S", "A", "B", "C", "D"])
    out["primary_state"] = state["primary_state"].astype(str).values
    out["state_confidence"] = state["state_confidence"].astype(float).values
    return out


def main() -> int:
    t0 = time.time()
    if not COMPONENTS_PATH.exists() or not STATE_PATH.exists():
        logger.error(
            "Missing inputs. Run `python -m compute.components` and "
            "`python -m compute.state` first."
        )
        return 1

    components = pd.read_parquet(COMPONENTS_PATH)
    state = pd.read_parquet(STATE_PATH)
    state = state.reindex(components.index)
    ccqs = compute_ccqs(components, state)
    elapsed = time.time() - t0

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ccqs.to_parquet(CCQS_PATH, compression="snappy")
    logger.info(
        f"Wrote {CCQS_PATH} ({len(ccqs):,} rows × {len(ccqs.columns)} cols) in {elapsed:.1f}s"
    )

    grade_dist = ccqs["grade"].astype(str).value_counts(normalize=True).to_dict()

    # Cross-sectional tie diagnostics — these should be near-zero after the
    # Phase 6 per-date winsorization fix.
    n_unique = int(ccqs["ccqs"].nunique())
    top_tie = int(ccqs["ccqs"].value_counts().iloc[0]) if len(ccqs) else 0

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "n_rows": int(len(ccqs)),
        "ccqs_mean": float(ccqs["ccqs"].mean()),
        "ccqs_median": float(ccqs["ccqs"].median()),
        "ccqs_p1": float(np.nanpercentile(ccqs["ccqs"].to_numpy(), 1.0)),
        "ccqs_p99": float(np.nanpercentile(ccqs["ccqs"].to_numpy(), 99.0)),
        "ccqs_unique_values": n_unique,
        "ccqs_max_tie_count": top_tie,
        "winsorization": "per-date p1/p99",
        "grade_distribution": {k: round(v, 4) for k, v in grade_dist.items()},
    }
    CCQS_META_PATH.write_text(json.dumps(meta, indent=2, default=str))

    print()
    print("=" * 60)
    print("CCQS DISTRIBUTION (all rows)")
    print("=" * 60)
    print(f"  Mean    : {meta['ccqs_mean']:.2f}")
    print(f"  Median  : {meta['ccqs_median']:.2f}")
    print(f"  P1 / P99: {meta['ccqs_p1']:.2f} / {meta['ccqs_p99']:.2f}")
    print()
    for g in ["S", "A", "B", "C", "D"]:
        pct = grade_dist.get(g, 0.0) * 100
        print(f"  Grade {g}: {pct:6.2f}%")
    print(f"Elapsed: {elapsed:.1f}s")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
