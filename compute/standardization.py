"""
CCQS V1 — Cross-Sectional Standardization Layer (SPEC Section 6)

Transforms each of the 108 features into a cross-sectionally comparable
z-score on each daily snapshot, choosing the right transform per feature
family:

    Family                      Transform
    -------------------------   ------------------------------------
    Already percentile (1-99)   pass-through (rescaled to z-style)
    Bounded oscillator [0,100]  standard z around midpoint (50)
    Bounded ratio [0,1]         logit, then robust z
    Returns / %MA / ATR×        robust z (median / 1.4826*MAD)
    Volume ratios / volumes     log(1+x), then standard z
    Binary (0/1)                pass-through
    Categorical (object)        dropped (kept only in features.parquet)

Run:
    python -m compute.standardization
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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FEATURES_PATH = CACHE_DIR / "features.parquet"
Z_SCORES_PATH = CACHE_DIR / "z_scores.parquet"
Z_META_PATH = CACHE_DIR / "z_scores_meta.json"

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")
logger.add(LOG_DIR / "ccqs.log", level="DEBUG", rotation="10 MB", retention="30 days")

EPS = 1e-10


# ---------------------------------------------------------------------------
# Feature-family registry
# ---------------------------------------------------------------------------

# Features that are already cross-sectional percentile ratings (1..99).
# Recenter to ~N(0,1) by treating them as ranks: z = (x - 50) / 28.87.
# 28.87 ≈ sd of Uniform(1,99) = (99-1)/sqrt(12).
PERCENTILE_FEATURES = {
    "rs_rating_spy",
    "sharpe_momentum_rank_126d", "sortino_rank_126d",
    "within_basket_rank_pct",  # 0..1 fraction (lower = better)
    # Path D Cat 22 — additional rank-style features.
    "sharpe_rank_60d", "sharpe_rank_252d", "tail_ratio_252d",
    # Path E Cat 23 — additional rank-style features.
    "momentum_21d_pct", "max_drawdown_pct_60d", "vol_percentile_21d",
}

# Bounded oscillators [0, 100]. Standard z around midpoint 50.
BOUNDED_100_FEATURES = {
    "rsi_14", "weekly_rsi_14", "adx_14", "plus_di", "minus_di",
    "sma_stack_score", "ema_stack_score", "vcp_quality_score",
    "bb_width_pct_252d",
}

# Bounded [0, 1] R²-like — logit, then robust z.
LOGIT_FEATURES = {
    "trend_r_squared_60d", "rs_line_spy_r_squared_60d",
    # Path D Cat 20 — bounded [0,1] persistence / regression-quality.
    "hurst_exponent_252d", "trend_rsquared_252d",
}

# Bounded [-1, 1] correlation-style features — symmetric logit then robust z.
CORRELATION_FEATURES = {
    "return_autocorrelation_60d_lag1",
    # Path E Cat 23 — short-horizon AR(1) coefficient.
    "return_autocorrelation_21d_lag1",
}

# Volume-like quantities — log(1+|x|)*sign(x), then standard z.
LOG_TRANSFORM_FEATURES = {
    "volume", "ad_line_slope_20",
    # Path D Cat 21 — bounded-positive volatility components.
    "upside_vol_60d", "downside_vol_60d",
    # Path E Cat 23 — 21-day A/D slope (matches existing ad_line_slope_20).
    "ad_line_slope_21d",
}

# Binary 0/1 flags: pass-through unchanged.
BINARY_FEATURES = {
    "trend_slope_significant",
    "adx_trend_direction",          # ±1 — kept as-is
    "supertrend_direction",         # ±1
    "capitulation_volume_flag", "climax_volume_flag",
    "rs_line_spy_new_high_60d", "rs_line_spy_new_high_252d",
    "rs_line_qqq_new_high_60d", "rs_line_qqq_new_high_252d",
    "trend_integrity", "new_252d_high", "failed_breakout_flag_10d",
    "weekly_stack_alignment", "weekly_higher_highs", "weekly_rs_rising",
    "weekly_trend_slope_sign",       # ±1
    "monthly_close_above_sma_10", "monthly_higher_highs_3m",
    "bullish_divergence_20d", "bearish_divergence_20d", "bb_squeeze_flag",
    "volume_leadership_confirmed",
    "pct_above_sma_50", "pct_above_sma_200",
    "weekly_rs_new_high_26w", "monthly_rs_rising_3m", "monthly_rs_rising_6m",
}

# Categorical / non-numeric features — excluded from z-score frame.
# (Path 1.5: `multi_bench_leadership_class` removed.)
CATEGORICAL_FEATURES = {
    "weekly_macd_posture",
    "macd_posture",
}


# ---------------------------------------------------------------------------
# Transform primitives
# ---------------------------------------------------------------------------

def robust_z_score(series: pd.Series) -> pd.Series:
    """Robust z-score using median and MAD (SPEC §6 reference).

    When MAD ≈ 0 (common for ordinal / low-cardinality features on dates
    where >½ of tickers share the same value), fall back to std. When std
    is also ≈ 0, the column is genuinely constant — return zeros instead
    of dividing by EPS, which would otherwise blow up to ±1e10.
    """
    vals = series.values
    median = np.nanmedian(vals)
    mad = float(np.nanmedian(np.abs(vals - median)))
    if mad < 1e-8:
        std = float(np.nanstd(vals))
        if std < 1e-8:
            return pd.Series(0.0, index=series.index)
        return (series - median) / std
    return (series - median) / (1.4826 * mad)


def standard_z(series: pd.Series, center: float | None = None) -> pd.Series:
    """Standard z-score; optionally centered at a fixed value (e.g. 50 for RSI)."""
    if center is None:
        center = float(np.nanmean(series.values))
    std = float(np.nanstd(series.values))
    if std < EPS:
        return pd.Series(0.0, index=series.index)
    return (series - center) / std


def winsorize(series: pd.Series, lower_pct: float = 1.0, upper_pct: float = 99.0) -> pd.Series:
    """Clip to lower/upper percentile bounds."""
    lo = np.nanpercentile(series.values, lower_pct)
    hi = np.nanpercentile(series.values, upper_pct)
    return series.clip(lower=lo, upper=hi)


# ---------------------------------------------------------------------------
# Per-feature transform dispatch
# ---------------------------------------------------------------------------

def _transform_one_date(name: str, vals: pd.Series) -> pd.Series:
    """Apply the per-family transform to one feature on one date."""
    if vals.notna().sum() < 5:
        return pd.Series(np.nan, index=vals.index)

    if name in BINARY_FEATURES:
        return vals.astype(float)

    if name in PERCENTILE_FEATURES:
        if name == "within_basket_rank_pct":
            # Lower is better; centre at 0.5 and scale ~N(0,1):
            #   sd of Uniform(0,1) = 1/sqrt(12) ≈ 0.2887
            return (0.5 - vals) / 0.2887
        return (vals - 50.0) / 28.87

    if name in BOUNDED_100_FEATURES:
        return standard_z(vals, center=50.0)

    if name in LOGIT_FEATURES:
        clipped = vals.clip(lower=0.001, upper=0.999)
        logit = np.log(clipped / (1.0 - clipped))
        return robust_z_score(logit)

    if name in CORRELATION_FEATURES:
        # x ∈ [-1, 1] → map to (0, 1) then logit, then robust z.
        p = ((vals.clip(lower=-0.999, upper=0.999) + 1.0) / 2.0)
        logit = np.log(p / (1.0 - p))
        return robust_z_score(logit)

    if name in LOG_TRANSFORM_FEATURES:
        signed = np.sign(vals) * np.log1p(vals.abs())
        return standard_z(signed)

    # Default: skewed numeric → robust z-score.
    return robust_z_score(vals)


def standardize_features(features: pd.DataFrame) -> pd.DataFrame:
    """
    Apply per-family transforms across the universe for each date.

    Returns a DataFrame with the same MultiIndex (ticker, date) as `features`
    but only numeric columns (categoricals are dropped).
    """
    # Drop categorical / non-numeric features upfront.
    keep_cols = [c for c in features.columns if c not in CATEGORICAL_FEATURES]
    numeric = features[keep_cols]

    # Promote to long-by-date pivot: for each feature, run cross-sectional
    # transform per date. Done in vectorized batches using groupby('date').
    z_pieces: dict[str, pd.Series] = {}
    grouped = numeric.groupby(level="date", sort=False)

    for name in keep_cols:
        col = numeric[name]
        # Apply transform date-by-date (cross-sectional).
        z = grouped[name].transform(lambda v, n=name: _transform_one_date(n, v))
        z_pieces[name] = z

    out = pd.DataFrame(z_pieces)
    out.index = numeric.index

    # Clamp z-scores to ±10. Defensive against feature-level outliers (e.g.
    # trend_slope_60d on hyper-momentum names, where (exp(slope·252)-1)·100
    # can hit 1e9+ and even a healthy MAD cannot rescue the z-score from
    # dominating downstream composites). Binary features are 0/1 and
    # unaffected; legitimate z's rarely exceed ±5.
    numeric_cols = out.select_dtypes(include=np.number).columns
    out[numeric_cols] = out[numeric_cols].clip(lower=-10.0, upper=10.0)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    t0 = time.time()
    if not FEATURES_PATH.exists():
        logger.error(f"{FEATURES_PATH} not found. Run `python -m compute.features` first.")
        return 1

    features = pd.read_parquet(FEATURES_PATH)
    logger.info(
        f"Loaded features: {len(features):,} rows × {len(features.columns)} cols"
    )
    z = standardize_features(features)
    elapsed = time.time() - t0

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    z.to_parquet(Z_SCORES_PATH, compression="snappy")
    logger.info(f"Wrote {Z_SCORES_PATH}  ({len(z):,} rows × {len(z.columns)} cols) in {elapsed:.1f}s")

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "n_rows": int(len(z)),
        "n_features_standardized": int(len(z.columns)),
        "n_features_dropped_categorical": int(len(features.columns) - len(z.columns)),
        "dropped_columns": sorted(CATEGORICAL_FEATURES & set(features.columns)),
    }
    Z_META_PATH.write_text(json.dumps(meta, indent=2, default=str))
    logger.info(f"Wrote {Z_META_PATH}")

    print()
    print("=" * 60)
    print("STANDARDIZATION SUMMARY")
    print("=" * 60)
    print(f"Z-score rows:        {meta['n_rows']:,}")
    print(f"Features:            {meta['n_features_standardized']}")
    print(f"Categorical dropped: {meta['n_features_dropped_categorical']} ({', '.join(meta['dropped_columns'])})")
    print(f"Elapsed:             {elapsed:.1f}s")
    print("=" * 60)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
