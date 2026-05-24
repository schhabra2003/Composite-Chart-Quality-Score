"""
CCQS V1 — Leadership Classification (SPEC Section 11, Path 1.5)

9-tier per-stock leadership classification:

    ELITE_LEADER         — top-shelf, all confirmations on
    STRONG_LEADER        — high RS + MTF confluence
    EMERGING_LEADER      — multibagger discovery (rising mid-band)
    ESTABLISHED_LEADER   — high RS with SPY RS Line new high
    STRONG_PERFORMER     — RS Rating ≥ 60
    NEUTRAL              — mid-band (rs_spy 45-60), no other signal
    WEAK_PERFORMER       — low RS (25-45) but stable / improving slope
    DETERIORATING        — actively declining (rs_spy<40 & slope<-5)
    WEAK_LAGGARD         — chronically weak (rs_spy<25 & slope<0)

Path 1.5: single-benchmark vs SPY, with QQQ RS Line slope as a
context-confirmation gate for top tiers. `MID_PACK` is folded into
`NEUTRAL` (the band-level distinction was not load-bearing). The
9th tier `WEAK_PERFORMER` was added in Phase 3 calibration to absorb
the low-RS-but-stable cohort that previously bloated NEUTRAL.

Run:
    python -m compute.leadership
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

FEATURES_PATH = CACHE_DIR / "features.parquet"
COMPONENTS_PATH = CACHE_DIR / "components.parquet"
LEADERSHIP_PATH = CACHE_DIR / "leadership.parquet"
LEADERSHIP_META_PATH = CACHE_DIR / "leadership_meta.json"

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")
logger.add(LOG_DIR / "ccqs.log", level="DEBUG", rotation="10 MB", retention="30 days")


TIERS: list[str] = [
    "ELITE_LEADER",
    "STRONG_LEADER",
    "EMERGING_LEADER",
    "ESTABLISHED_LEADER",
    "STRONG_PERFORMER",
    "NEUTRAL",
    "WEAK_PERFORMER",
    "DETERIORATING",
    "WEAK_LAGGARD",
]


def _z_to_0_100(z: pd.Series) -> pd.Series:
    """Convert a z-score Series to a 0-100 display value via Φ(z) × 100."""
    return pd.Series(norm.cdf(z.to_numpy(dtype=float)) * 100.0, index=z.index)


def classify_leadership(features: pd.DataFrame, components: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame with 'leadership_tier' (categorical) + 'is_basket_leader'.

    Vectorized: builds boolean masks per tier and applies first-match-wins.
    """
    # s_rs_leadership in 0-100 display space for SPEC comparisons.
    s_lead = _z_to_0_100(components["s_rs_leadership"])

    rs_spy = features["rs_rating_spy"].astype(float)
    rs_slope = features["rs_rating_slope_60d"].astype(float)
    mtf_coh = features["mtf_rs_coherence"].astype(float)
    vol_conf = features["volume_leadership_confirmed"].astype(float).fillna(0).astype(bool)
    spy_nh_252 = features["rs_line_spy_new_high_252d"].astype(float).fillna(0).astype(bool)
    qqq_slope_60 = features["rs_line_qqq_slope_60d"].astype(float)

    # is_basket_leader: rank 1 within its basket on a given date.
    basket_rank = features["within_basket_rank"].astype(float)
    is_basket_leader = (basket_rank == 1.0).fillna(False)

    qqq_context_ok = (qqq_slope_60 > 0).fillna(False)

    # Tier masks, evaluated in priority order.
    m_elite = (
        (s_lead >= 90)
        & (rs_spy >= 95)
        & (mtf_coh == 3)
        & vol_conf
        & is_basket_leader
        & qqq_context_ok
    )

    m_strong = (s_lead >= 80) & (rs_spy >= 75) & (mtf_coh >= 2)

    m_emerging = (
        (rs_spy >= 60) & (rs_spy <= 85)
        & (rs_slope >= 10)
        & (mtf_coh >= 2)
        & qqq_context_ok
    )

    m_established = (rs_spy >= 75) & spy_nh_252

    m_strong_perf = rs_spy >= 60

    # Genuine middle band — rs_spy is uninspiring but not declining.
    m_neutral = (rs_spy >= 45) & (rs_spy < 60)

    # Low RS but stable / slightly improving momentum. Captures the gap
    # (formerly absorbed into NEUTRAL) where rs_spy is 25-45 yet rs_slope
    # has not turned actively negative — often value / cyclical names mid-
    # cycle or recovering laggards.
    m_weak_perf = (rs_spy >= 25) & (rs_spy < 45) & (rs_slope >= -5)

    # Active decline: written after WEAK_PERFORMER / WEAK_LAGGARD so it
    # takes precedence in the overlap (severely negative slope wins).
    m_deteriorating = (rs_spy < 40) & (rs_slope < -5)

    # Chronically weak and still rolling over.
    m_weak = (rs_spy < 25) & (rs_slope < 0)

    # First-match-wins via priority chain.
    tier = pd.Series("NEUTRAL", index=features.index, dtype=object)
    # Apply in reverse priority so later writes are overwritten by higher tiers.
    tier[m_neutral] = "NEUTRAL"
    tier[m_weak_perf] = "WEAK_PERFORMER"
    tier[m_weak] = "WEAK_LAGGARD"
    tier[m_deteriorating] = "DETERIORATING"
    tier[m_strong_perf] = "STRONG_PERFORMER"
    tier[m_established] = "ESTABLISHED_LEADER"
    tier[m_emerging] = "EMERGING_LEADER"
    tier[m_strong] = "STRONG_LEADER"
    tier[m_elite] = "ELITE_LEADER"

    # Rows lacking enough history to compute rs_rating_spy cannot be
    # classified — leave them as NaN rather than defaulting to NEUTRAL,
    # which would otherwise inflate the mid-band by ~21pp.
    tier[rs_spy.isna()] = np.nan

    tier_cat = pd.Categorical(tier, categories=TIERS)
    out = pd.DataFrame(index=features.index)
    out["leadership_tier"] = tier_cat
    out["is_basket_leader"] = is_basket_leader
    out["s_rs_leadership_0_100"] = s_lead
    return out


def main() -> int:
    t0 = time.time()
    if not FEATURES_PATH.exists() or not COMPONENTS_PATH.exists():
        logger.error(
            "Missing inputs. Run `python -m compute.features` and "
            "`python -m compute.components` first."
        )
        return 1

    features = pd.read_parquet(FEATURES_PATH)
    components = pd.read_parquet(COMPONENTS_PATH)
    leadership = classify_leadership(features, components)
    elapsed = time.time() - t0

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    leadership.to_parquet(LEADERSHIP_PATH, compression="snappy")
    logger.info(
        f"Wrote {LEADERSHIP_PATH} ({len(leadership):,} rows × "
        f"{len(leadership.columns)} cols) in {elapsed:.1f}s"
    )

    dist = leadership["leadership_tier"].astype(str).value_counts(normalize=True).to_dict()
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "n_rows": int(len(leadership)),
        "tiers": TIERS,
        "leadership_distribution": {k: round(v, 4) for k, v in dist.items()},
    }
    LEADERSHIP_META_PATH.write_text(json.dumps(meta, indent=2, default=str))

    print()
    print("=" * 60)
    print("LEADERSHIP TIER DISTRIBUTION (all rows)")
    print("=" * 60)
    for t in TIERS:
        pct = dist.get(t, 0.0) * 100
        print(f"  {t:<20} {pct:6.2f}%")
    print(f"Elapsed: {elapsed:.1f}s")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
