"""
CCQS V1 — State Classification (SPEC Section 8)

Per-stock probabilistic state classification using softmax over
log-likelihoods. Six states:

    TRENDING        — clean uptrend in progress
    PULLBACK        — buyable pullback within uptrend
    CONSOLIDATING   — pre-breakout consolidation
    EXHAUSTION      — parabolic / late-stage exhaustion
    DETERIORATING   — structurally damaged downtrend
    INDETERMINATE   — transitioning / no clear regime

Outputs (per ticker, date):
    primary_state       (string)
    state_confidence    (max probability)
    p_TRENDING, p_PULLBACK, p_CONSOLIDATING, p_EXHAUSTION, p_DETERIORATING, p_INDETERMINATE
    p_adj_TRENDING ... (confidence-blended versions used for Bayesian
                       averaging downstream)

Run:
    python -m compute.state
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

from compute.loader import CACHE_DIR, LOG_DIR

FEATURES_PATH = CACHE_DIR / "features.parquet"
STATE_PATH = CACHE_DIR / "state.parquet"
STATE_META_PATH = CACHE_DIR / "state_meta.json"

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")
logger.add(LOG_DIR / "ccqs.log", level="DEBUG", rotation="10 MB", retention="30 days")

STATES: list[str] = ["TRENDING", "PULLBACK", "CONSOLIDATING", "EXHAUSTION", "DETERIORATING", "INDETERMINATE"]
PROB_COLS: list[str] = [f"p_{s}" for s in STATES]
PROB_ADJ_COLS: list[str] = [f"p_adj_{s}" for s in STATES]


# ---------------------------------------------------------------------------
# Log-likelihood primitives (vectorized over the full long DataFrame)
# ---------------------------------------------------------------------------

def normal_logpdf(x: pd.Series, mu: float, sigma: float) -> pd.Series:
    """Gaussian log-density (kernel only: -0.5·z²).

    Drops the σ-dependent normalization constant so log-likelihoods peak at
    zero and decline with the squared standardised distance. This matches the
    scale of the INDETERMINATE prior (-0.5) baked into SPEC §8.
    """
    sigma = max(float(sigma), 1e-6)
    z = (x.astype(float) - mu) / sigma
    return -0.5 * z * z


def indicator_logpdf(condition: pd.Series, conf: float) -> pd.Series:
    """Log-likelihood when indicator matches state: log(conf) vs log(1-conf)."""
    conf = float(np.clip(conf, 1e-6, 1 - 1e-6))
    cond = condition.astype(float).fillna(0).astype(bool)
    return pd.Series(
        np.where(cond, np.log(conf), np.log(1.0 - conf)),
        index=condition.index,
    )


# ---------------------------------------------------------------------------
# State likelihoods
# ---------------------------------------------------------------------------

def _ll_trending(f: pd.DataFrame) -> pd.Series:
    return (
        normal_logpdf(f["adx_14"], 30.0, 12.0)
        + normal_logpdf(f["trend_r_squared_60d"], 0.65, 0.20)
        + indicator_logpdf(f["sma_stack_score"] >= 80, 0.85)
        + normal_logpdf(f["pct_ma_50"], 10.0, 12.0)
    )


def _ll_pullback(f: pd.DataFrame) -> pd.Series:
    return (
        indicator_logpdf(f["sma_stack_score"] >= 75, 0.80)
        + normal_logpdf(f["pct_ma_50"], 5.0, 5.0)
        + normal_logpdf(f["atr_x_50"], 1.5, 1.0)
        + normal_logpdf(f["rsi_14"], 45.0, 15.0)
    )


def _ll_consolidating(f: pd.DataFrame) -> pd.Series:
    return (
        normal_logpdf(f["bb_width_pct_252d"], 15.0, 12.0)
        + normal_logpdf(f["adx_14"], 15.0, 8.0)
        + indicator_logpdf(f["bb_squeeze_flag"].astype(float) > 0, 0.60)
        + normal_logpdf(f["vcp_quality_score"], 55.0, 25.0)
    )


def _ll_exhaustion(f: pd.DataFrame) -> pd.Series:
    return (
        normal_logpdf(f["atr_x_50"], 6.0, 2.0)
        + normal_logpdf(f["rsi_14"], 75.0, 8.0)
        + normal_logpdf(f["rs_rating_spy"], 92.0, 8.0)
        + indicator_logpdf(f["days_near_52w_high_60d"] >= 25, 0.70)
    )


def _ll_deteriorating(f: pd.DataFrame) -> pd.Series:
    return (
        normal_logpdf(f["pct_ma_50"], -12.0, 10.0)
        + normal_logpdf(f["distribution_days_25"], 8.0, 4.0)
        + indicator_logpdf(f["supertrend_direction"].astype(float) == -1, 0.75)
        + normal_logpdf(f["rs_rating_spy"], 25.0, 20.0)
    )


def _ll_indeterminate(f: pd.DataFrame) -> pd.Series:
    return pd.Series(-2.5, index=f.index)


_LIKELIHOOD = {
    "TRENDING": _ll_trending,
    "PULLBACK": _ll_pullback,
    "CONSOLIDATING": _ll_consolidating,
    "EXHAUSTION": _ll_exhaustion,
    "DETERIORATING": _ll_deteriorating,
    "INDETERMINATE": _ll_indeterminate,
}


# ---------------------------------------------------------------------------
# Softmax + confidence blending
# ---------------------------------------------------------------------------

def _softmax_rowwise(ll_matrix: np.ndarray) -> np.ndarray:
    """Numerically stable softmax per row (axis=1)."""
    m = np.nanmax(ll_matrix, axis=1, keepdims=True)
    exp = np.exp(ll_matrix - m)
    exp = np.where(np.isnan(ll_matrix), 0.0, exp)
    s = exp.sum(axis=1, keepdims=True)
    s = np.where(s < 1e-12, 1.0, s)
    return exp / s


def _confidence_blend(probs: np.ndarray) -> np.ndarray:
    """Confidence blending toward INDETERMINATE per SPEC §8.

    max_prob ≥ 0.7  → unchanged
    max_prob ≥ 0.5  → 70% original + 30% INDETERMINATE
    max_prob < 0.5  → 50% original + 50% INDETERMINATE
    """
    n_rows, n_states = probs.shape
    indeterminate_idx = STATES.index("INDETERMINATE")

    max_p = np.nanmax(probs, axis=1)
    out = probs.copy()

    medium_mask = (max_p < 0.7) & (max_p >= 0.5)
    low_mask = max_p < 0.5

    if medium_mask.any():
        block = probs[medium_mask] * 0.7
        block[:, indeterminate_idx] += 0.3
        out[medium_mask] = block

    if low_mask.any():
        block = probs[low_mask] * 0.5
        block[:, indeterminate_idx] += 0.5
        out[low_mask] = block

    return out


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

def classify_states(features: pd.DataFrame) -> pd.DataFrame:
    """Compute primary state, confidence, and 6-way state probabilities."""
    log_likes: dict[str, pd.Series] = {}
    for s in STATES:
        log_likes[s] = _LIKELIHOOD[s](features)

    ll_df = pd.DataFrame(log_likes, index=features.index)[STATES]
    ll_arr = ll_df.to_numpy(dtype=float, copy=False)

    probs = _softmax_rowwise(ll_arr)
    probs_adj = _confidence_blend(probs)

    primary_idx = np.nanargmax(probs, axis=1)
    primary_state = pd.Categorical.from_codes(primary_idx, categories=STATES)
    confidence = probs[np.arange(len(probs)), primary_idx]

    out = pd.DataFrame(index=features.index)
    out["primary_state"] = primary_state
    out["state_confidence"] = confidence
    for i, s in enumerate(STATES):
        out[f"p_{s}"] = probs[:, i]
    for i, s in enumerate(STATES):
        out[f"p_adj_{s}"] = probs_adj[:, i]

    return out


def main() -> int:
    t0 = time.time()
    if not FEATURES_PATH.exists():
        logger.error(f"{FEATURES_PATH} not found. Run `python -m compute.features` first.")
        return 1

    features = pd.read_parquet(FEATURES_PATH)
    logger.info(f"Loaded features: {features.shape}")

    states = classify_states(features)
    elapsed = time.time() - t0

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    states.to_parquet(STATE_PATH, compression="snappy")
    logger.info(
        f"Wrote {STATE_PATH} ({len(states):,} rows × {len(states.columns)} cols) in {elapsed:.1f}s"
    )

    dist = states["primary_state"].astype(str).value_counts(normalize=True).to_dict()
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "n_rows": int(len(states)),
        "states": STATES,
        "primary_state_distribution": {k: round(v, 4) for k, v in dist.items()},
        "mean_confidence": float(states["state_confidence"].mean()),
    }
    STATE_META_PATH.write_text(json.dumps(meta, indent=2, default=str))
    logger.info(f"Wrote {STATE_META_PATH}")

    print()
    print("=" * 60)
    print("STATE DISTRIBUTION (all rows)")
    print("=" * 60)
    for s in STATES:
        pct = dist.get(s, 0.0) * 100
        print(f"  {s:<12} {pct:6.2f}%")
    print(f"Mean confidence: {meta['mean_confidence']:.3f}")
    print(f"Elapsed: {elapsed:.1f}s")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
