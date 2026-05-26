"""
CCQS V1 — Component Scoring Layer (SPEC Section 7)

Computes 11 component z-scores per (ticker, date):

    S_RS                Classical cross-sectional momentum
    S_RS_LEADERSHIP     Multi-dim leadership composite (PRIMARY)
    S_RESIDUAL_MOMENTUM Beta-adjusted idiosyncratic momentum (Phase 8a)
    S_RSL               RS Line dynamics
    S_TREND_SLOPE       Trend cleanness (ADX + R² + t-stat)
    S_STRUCTURE         MA stacks + HH/HL + Supertrend
    S_MTF               Multi-timeframe confluence
    S_EXTENSION         Vol-normalized extension (inverted)
    S_DEMAND            Volume quality (zero-weighted since Phase 7)
    S_MOMENTUM          MACD + RSI + divergences
    S_VOLUME            Bundled volume-pattern composite (Phase 10)

(S_CLIMAX removed in Phase 6, 2026-05-25 — carried zero weight since
Phase X.2.1, math was inverted vs label. Underlying features remain
available to state classification and the setup classifier.)

All outputs live in z-score space. Raw features feed pre-transform
operations (logs, products, sign-flips, posture lookups); z_scores feed
the linear blends directly.

Run:
    python -m compute.components
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
Z_SCORES_PATH = CACHE_DIR / "z_scores.parquet"
COMPONENTS_PATH = CACHE_DIR / "components.parquet"
COMPONENTS_META_PATH = CACHE_DIR / "components_meta.json"

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")
logger.add(LOG_DIR / "ccqs.log", level="DEBUG", rotation="10 MB", retention="30 days")

EPS = 1e-10

COMPONENT_COLS = [
    "s_rs", "s_rs_leadership", "s_residual_momentum",
    "s_rsl", "s_trend_slope", "s_structure",
    "s_mtf", "s_extension", "s_demand", "s_momentum",
    "s_volume",
]

# Volume-gate cap on S_RS_LEADERSHIP: 70th percentile of standard normal.
Z_CAP_70 = float(norm.ppf(0.70))  # ≈ 0.5244

# MACD posture lookup table (SPEC §7 S_MOMENTUM).
MACD_POSTURE_SCORE: dict[str, float] = {
    "Positive/Accelerating/Strong": 100.0,
    "Positive/Accelerating/Weak": 80.0,
    "Positive/Decelerating/Strong": 65.0,
    "Positive/Decelerating/Weak": 50.0,
    "Negative/Decelerating/Weak": 40.0,
    "Negative/Decelerating/Strong": 30.0,
    "Negative/Accelerating/Weak": 20.0,
    "Negative/Accelerating/Strong": 0.0,
}


# ---------------------------------------------------------------------------
# Cross-sectional z-score helpers
# ---------------------------------------------------------------------------

def _robust_z_date(v: pd.Series) -> pd.Series:
    """Robust z per date with MAD≈0 fallback (mirrors standardization.py)."""
    v = v.astype(float)
    med = v.median()
    mad = float((v - med).abs().median())
    if mad < 1e-8:
        std = float(v.std(ddof=0))
        if std < 1e-8:
            return pd.Series(0.0, index=v.index)
        return (v - med) / std
    return (v - med) / (1.4826 * mad)


def per_date_robust_z(s: pd.Series) -> pd.Series:
    """Cross-sectional robust z-score per date."""
    return s.groupby(level="date", sort=False).transform(_robust_z_date)


def per_date_standard_z(s: pd.Series) -> pd.Series:
    """Cross-sectional standard z-score per date."""
    def _z(v):
        v = v.astype(float)
        mu = v.mean()
        sd = v.std(ddof=0)
        if sd < EPS:
            return pd.Series(0.0, index=v.index)
        return (v - mu) / sd
    return s.groupby(level="date", sort=False).transform(_z)


# ---------------------------------------------------------------------------
# Component computations
# ---------------------------------------------------------------------------

def _compute_s_rs(z: pd.DataFrame) -> pd.Series:
    # within_basket_z_21d is NaN for tickers whose primary basket (after dedup)
    # has <3 effective members. Treat NaN as z=0 (neutral within-basket info) so
    # those tickers still get scored on the other two inputs.
    return (
        0.55 * z["rs_rating_spy"].astype(float)
        + 0.30 * z["sharpe_momentum_rank_126d"].astype(float)
        + 0.15 * z["within_basket_z_21d"].astype(float).fillna(0.0)
    )


def _compute_s_rs_leadership(features: pd.DataFrame, z: pd.DataFrame) -> pd.Series:
    primary_rs = z["rs_rating_spy"].astype(float)

    # Phase X.2.1 — Path E demoted the 252d risk-adjusted features in favour
    # of 60d versions; the OOS feature audit (2026-05) showed the 252d trio
    # (sharpe_rank_252d, gain_to_pain_ratio_252d, information_ratio_252d)
    # to be top-3 OOS contributors at *every* horizon. Restore them to the
    # quality sub-block; keep sortino_rank_126d as a smaller stabiliser.
    quality = (
        0.30 * z["sharpe_rank_252d"].astype(float)
        + 0.30 * z["gain_to_pain_ratio_252d"].astype(float)
        + 0.30 * z["information_ratio_252d"].astype(float)
        + 0.10 * z["sortino_rank_126d"].astype(float)
    )

    # rs_rating_slope_120d may be NaN for very recent listings/spinoffs
    # (e.g. SNDK from the Feb-2025 WDC spinoff). Treat NaN as z=0 so the
    # ticker is still scoreable on the 60d slope.
    accel = (
        0.50 * z["rs_rating_slope_60d"].astype(float)
        + 0.50 * z["rs_rating_slope_120d"].astype(float).fillna(0.0)
    )

    rsl = (
        0.20 * z["rs_line_spy_new_high_252d"].astype(float)
        + 0.15 * z["rs_line_spy_slope_60d"].astype(float)
        + 0.50 * z["rs_line_spy_r_squared_60d"].astype(float)
        + 0.15 * z["rs_line_qqq_new_high_252d"].astype(float)
    )

    # Confluence: mtf_rs_coherence is 0..3 (categorical-ish integer), z-score it
    # cross-sectionally so it lives in the same space as the rest of the blend.
    # within_basket_z_63d carries the same NaN risk as the 21d variant;
    # treat NaN as z=0 to keep small-primary-basket tickers scoreable.
    confluence = (
        0.55 * z["mtf_rs_coherence"].astype(float)
        + 0.45 * z["within_basket_z_63d"].astype(float).fillna(0.0)
    )

    # Path D — information_ratio_252d is independent alpha-quality info; gets
    # its own 10% slot at top-level (carved 5% each from primary_rs & confluence).
    s_lead = (
        0.30 * primary_rs
        + 0.15 * quality
        + 0.10 * accel
        + 0.20 * rsl
        + 0.15 * confluence
        + 0.10 * z["information_ratio_252d"].astype(float)
    )

    # Volume gate: if volume_leadership_confirmed is False, cap at 70th
    # percentile of standard normal (≈ 0.5244 in z-space).
    vol_conf = features["volume_leadership_confirmed"].astype(float).fillna(0).astype(bool)
    capped = s_lead.clip(upper=Z_CAP_70)
    s_lead = s_lead.where(vol_conf, capped)

    return s_lead


def _compute_s_residual_momentum(features: pd.DataFrame) -> pd.Series:
    """S_RESIDUAL_MOMENTUM — Phase 8a residual / idiosyncratic momentum.

    Per-date cross-sectional robust z of the 126-day residual momentum
    feature. The feature itself (`residual_momentum_126d` in
    compute/features.py) is the trailing-126d sum of daily residual
    log-returns, where each day's residual is

        r_resid[t] = r_i[t] - β_lag1[t] · r_SPY[t]

    and β_lag1 is the trailing 252-day rolling OLS beta vs SPY (shifted
    one day to eliminate look-ahead).

    Empirical basis: Blitz–Huij–Martens (2011), Robeco production usage.
    Phase 8a pre-implementation test showed:
      - Standalone IC at 126d-fwd = +0.0466 (t=14.4)
      - Orthogonal-to-`s_rs` IC at 126d-fwd: +0.0246, t=+8.63
        (overwhelmingly significant incremental signal beyond `s_rs`)
      - Walk-forward paired t-test: 60d t=2.05, 126d t=2.72
      - 23 of 24 (state × horizon) cells improve

    Weighted at 5% in every state in compute/ccqs.py STATE_WEIGHTS.

    Clipped at ±10 (matches standardization.py's clamp on the z-scored
    feature frame). Residual momentum has fatter tails than the other
    components — sums of log-residuals can hit large magnitudes on
    crash/recovery dates — so the clip is defensive insurance against
    extreme outliers dominating the per-date Bayesian composite.
    """
    z = per_date_robust_z(features["residual_momentum_126d"].astype(float))
    return z.clip(lower=-10.0, upper=10.0)


def _compute_s_rsl(z: pd.DataFrame) -> pd.Series:
    return (
        0.40 * z["rs_line_spy_new_high_252d"].astype(float)
        + 0.25 * z["rs_line_spy_new_high_60d"].astype(float)
        + 0.20 * z["rs_line_spy_slope_20d"].astype(float)
        + 0.15 * z["rs_line_spy_r_squared_60d"].astype(float)
    )


def _compute_s_trend_slope(features: pd.DataFrame, z: pd.DataFrame) -> pd.Series:
    # Derived signed-supertrend term: direction × days_since_flip
    super_signed = (
        features["supertrend_direction"].astype(float)
        * features["supertrend_days_since_flip"].astype(float)
    )
    z_super_signed = per_date_robust_z(super_signed)

    # Derived DI spread
    di_spread = features["plus_di"].astype(float) - features["minus_di"].astype(float)
    z_di_spread = per_date_robust_z(di_spread)

    # Path D — trend quality features carry persistence / smoothness signal
    # that ADX alone cannot read. Re-weighted to give them ~40% of the
    # composite; pure-ADX dropped from 0.30 → 0.20.
    s = (
        0.20 * z["adx_14"].astype(float)
        + 0.15 * z["trend_r_squared_60d"].astype(float)
        + 0.10 * z["trend_rsquared_252d"].astype(float)
        + 0.15 * z["hurst_exponent_252d"].astype(float)
        + 0.15 * z["return_autocorrelation_60d_lag1"].astype(float)
        + 0.10 * z["trend_slope_60d"].astype(float)
        + 0.10 * z_super_signed
        + 0.05 * z_di_spread
    )

    # Significance gating: half-weight when t-stat insignificant.
    t_stat = features["trend_slope_t_stat"].astype(float)
    insignificant = (t_stat.abs() < 1.96).fillna(True)
    s = s.where(~insignificant, s * 0.5)
    return s


def _compute_s_structure(features: pd.DataFrame, z: pd.DataFrame) -> pd.Series:
    # Phase X.2.1 — two empirical fixes from the OOS audit (2026-05):
    #   FIX 1: sign-flip hh_count_60d. Audit found mean OOS IC = -0.0335
    #          (t = -9.0 at 5d). Higher pivot highs predict *lower* forward
    #          returns; the raw feature was effectively a contrarian signal
    #          fed in with the wrong sign.
    #   FIX 4: boost hl_count_60d weight from 0.08 → 0.25. Audit found OOS
    #          IC = +0.049 (t = +14.1) at 1d horizon — the strongest single
    #          OOS contributor in the entire feature set.
    # Simplifying: dropped ulcer_index_60d and failed_breakout_flag_10d from
    # the blend (neither was a top-tier OOS carrier).
    return (
        0.20 * z["sma_stack_score"].astype(float)
        + 0.20 * z["ema_stack_score"].astype(float)
        + 0.10 * (-z["hh_count_60d"].astype(float))
        + 0.25 * z["hl_count_60d"].astype(float)
        + 0.10 * z["supertrend_direction"].astype(float)
        + 0.10 * z["new_252d_high"].astype(float)
        + 0.05 * z["pct_up_days_21"].astype(float)
    )


def _compute_s_mtf(features: pd.DataFrame, z: pd.DataFrame) -> pd.Series:
    # weekly_macd_posture is categorical; derive binary "is positive", per-date z.
    weekly_macd_pos = (features["weekly_macd_posture"] == "Positive").astype(float)
    z_weekly_macd_pos = per_date_standard_z(weekly_macd_pos)

    # weekly_trend_slope_sign > 0 → binary
    weekly_slope_pos = (features["weekly_trend_slope_sign"].astype(float) > 0).astype(float)
    z_weekly_slope_pos = per_date_standard_z(weekly_slope_pos)

    weekly_score = (
        0.30 * z["weekly_stack_alignment"].astype(float)
        + 0.20 * z["weekly_higher_highs"].astype(float)
        + 0.20 * z["weekly_rs_rising"].astype(float)
        + 0.15 * z_weekly_macd_pos
        + 0.15 * z_weekly_slope_pos
    )

    monthly_score = (
        0.50 * z["monthly_close_above_sma_10"].astype(float)
        + 0.50 * z["monthly_higher_highs_3m"].astype(float)
    )

    return 0.80 * weekly_score + 0.20 * monthly_score


def _compute_s_extension(features: pd.DataFrame, z: pd.DataFrame) -> pd.Series:
    # Inverted: less extended = better.
    pct_ma_50 = features["pct_ma_50"].astype(float)

    severely_broken = pct_ma_50 < -10
    below_50ma = (pct_ma_50 >= -10) & (pct_ma_50 < -3)

    above = (
        0.55 * (-z["vol_normalized_extension"].astype(float))
        + 0.30 * (-z["pct_ma_50"].astype(float))
        + 0.15 * (-z["price_z_score_vs_trend"].astype(float))
    )

    s = above.copy()
    s = s.where(~below_50ma, -0.5)
    s = s.where(~severely_broken, -1.0)
    return s


def _compute_s_demand(features: pd.DataFrame, z: pd.DataFrame) -> pd.Series:
    udvr = features["up_down_vol_ratio_50"].astype(float)
    log_udvr = np.log(udvr.clip(lower=EPS))
    z_log_udvr = per_date_robust_z(log_udvr)

    return (
        0.30 * z_log_udvr
        + 0.25 * (-z["distribution_days_25"].astype(float))
        + 0.20 * z["ad_line_slope_20"].astype(float)
        + 0.15 * z["cmf_21"].astype(float)
        + 0.10 * z["volume_z_20_252"].astype(float)
    )


def _compute_s_momentum(features: pd.DataFrame, z: pd.DataFrame) -> pd.Series:
    # Legacy oscillator pieces (MACD posture, RSI extremes, divergence
    # adjustment) — preserved verbatim, then per-date z-scored so each
    # contributes on the same scale as the new 21d signals.
    macd_score = features["macd_posture"].map(MACD_POSTURE_SCORE).astype(float)
    macd_score = macd_score.fillna(50.0)

    rsi = features["rsi_14"].astype(float)
    rsi_score = pd.Series(50.0, index=features.index)
    rsi_score = rsi_score.where(~(rsi < 30), 80.0)
    rsi_score = rsi_score.where(~(rsi > 75), 20.0)

    bull = features["bullish_divergence_20d"].astype(float).fillna(0)
    bear = features["bearish_divergence_20d"].astype(float).fillna(0)
    div_adj = 15.0 * bull - 15.0 * bear

    z_macd = per_date_standard_z(macd_score)
    z_rsi = per_date_standard_z(rsi_score)
    z_div = per_date_standard_z(div_adj)

    # Path E — 21d momentum + RS-line slope dominate. The 60% allocation to
    # these two short-horizon signals targets the 20–60d IC gap; legacy
    # MACD/RSI/divergence retain the remaining 40%.
    return (
        0.40 * z["momentum_21d_pct"].astype(float)
        + 0.20 * z["rs_line_spy_slope_21d"].astype(float)
        + 0.20 * z_macd
        + 0.10 * z_rsi
        + 0.10 * z_div
    )


def _compute_s_volume(features: pd.DataFrame) -> pd.Series:
    """S_VOLUME — Phase 10 volume-pattern composite (2026-05-26).

    Equal-weight blend of TWO orthogonal volume features:

      • low_rel_vol_10d  — flag: today's volume ≤ rolling-10d min.
                            Captures consolidation / "dry-up" days.
      • volume_buzz_50   — (volume / 50d avg − 1) × 100. Captures
                            single-day surge intensity.

    Each input is independently per-date robust-z scored (median/MAD,
    1.4826 multiplier); the equal-weight sum is then per-date robust-z'd
    again so the output sits on the same scale as the other 10 components,
    and clipped at ±10 to defend against extreme outliers.

    EMPIRICAL BASIS (Phase 10 investigation, 2026-05-26):
      • volume_buzz_50: standalone IC +0.0058 (5d, CI > 0), +0.0063 (20d,
        CI > 0). Orthogonal IC matches: +0.0059 (5d), +0.0058 (20d) — both
        with strict CI > 0 — meaning the short-horizon signal is NOT
        captured by the existing 10 components.
      • low_rel_vol_10d: orthogonal IC +0.0049 (60d, CI > 0), +0.0055
        (126d, CI > 0). Standalone IC is slightly negative at short
        horizons (−0.0022 5d/20d) but the orthogonal direction (after
        controlling for state/RS/structure) is positive at long horizons.

    INTEGRATION RESULTS (Config W1, 3% per state, n_dates=1414):
      • 5d  per-date IC: 0.01133 → 0.01168 (+3.1%, t=2.33 → 2.41)
      • 20d per-date IC: 0.00867 → 0.00903 (+4.1%, t=1.95 → 2.04)
      • 60d per-date IC: 0.01376 → 0.01362 (−1.0%, NS)
      • 126d per-date IC: 0.02916 → 0.02946 (+1.0%, NS)
      • Walk-forward paired t at 5d: +2.01 (first config in three
        investigations to clear +1.96)
      • Per-date IC delta CI at 5d: [+0.000012, +0.000686] strict > 0
      • EXHAUSTION-state IC: +0.006 to +0.016 across every horizon
        (resolves the EXHAUSTION fragility documented in Phase 3c /
        Priority 8a.1 / Phase 8b).

    BUNDLED FEATURE REQUIREMENT (W6 LESSON):
      The two features MUST be used together. Investigation Config W6
      (low_rel_vol_10d alone at 5%) actively HURT CCQS at every horizon
      (walk-forward paired t between −1.20 and −1.95). The orthogonal-IC
      positive direction emerges only when the feature is blended with
      volume_buzz_50; alone, the standalone-IC negative direction
      dominates. Do not unbundle.

    NaN HANDLING:
      ~18% of (ticker, date) rows are NaN until the cache-wide 252d
      warmup is met. Standalone feature NaN% is 4–6%. Compute_ccqs()
      gracefully handles NaN by zeroing the contribution from those rows.

    Weighted at 3% in every state in compute/ccqs.py STATE_WEIGHTS
    (renormalized by ×0.97 across the existing 10 components).
    """
    z_lo = per_date_robust_z(features["low_rel_vol_10d"].astype(float))
    z_bz = per_date_robust_z(features["volume_buzz_50"].astype(float))
    raw = 0.5 * z_lo + 0.5 * z_bz
    return per_date_robust_z(raw).clip(lower=-10.0, upper=10.0)


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

def compute_components(features: pd.DataFrame, z_scores: pd.DataFrame) -> pd.DataFrame:
    """Return DataFrame of 11 component z-scores aligned to features index."""
    # Align z_scores to features (both should already share the MultiIndex).
    z = z_scores.reindex(features.index)

    out = pd.DataFrame(index=features.index)
    out["s_rs"] = _compute_s_rs(z)
    out["s_rs_leadership"] = _compute_s_rs_leadership(features, z)
    out["s_residual_momentum"] = _compute_s_residual_momentum(features)
    out["s_rsl"] = _compute_s_rsl(z)
    out["s_trend_slope"] = _compute_s_trend_slope(features, z)
    out["s_structure"] = _compute_s_structure(features, z)
    out["s_mtf"] = _compute_s_mtf(features, z)
    out["s_extension"] = _compute_s_extension(features, z)
    out["s_demand"] = _compute_s_demand(features, z)
    out["s_momentum"] = _compute_s_momentum(features, z)
    out["s_volume"] = _compute_s_volume(features)
    return out


def main() -> int:
    t0 = time.time()
    if not FEATURES_PATH.exists() or not Z_SCORES_PATH.exists():
        logger.error(
            "Missing inputs. Run `python -m compute.features` and "
            "`python -m compute.standardization` first."
        )
        return 1

    features = pd.read_parquet(FEATURES_PATH)
    z_scores = pd.read_parquet(Z_SCORES_PATH)
    logger.info(
        f"Loaded features ({features.shape}) and z_scores ({z_scores.shape})"
    )

    components = compute_components(features, z_scores)
    elapsed = time.time() - t0

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    components.to_parquet(COMPONENTS_PATH, compression="snappy")
    logger.info(
        f"Wrote {COMPONENTS_PATH} ({len(components):,} rows × "
        f"{len(components.columns)} cols) in {elapsed:.1f}s"
    )

    summary = {col: float(components[col].mean()) for col in COMPONENT_COLS}
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "n_rows": int(len(components)),
        "components": COMPONENT_COLS,
        "mean_per_component": summary,
    }
    COMPONENTS_META_PATH.write_text(json.dumps(meta, indent=2, default=str))
    logger.info(f"Wrote {COMPONENTS_META_PATH}")

    print()
    print("=" * 60)
    print("COMPONENT SUMMARY")
    print("=" * 60)
    for col in COMPONENT_COLS:
        s = components[col]
        print(
            f"  {col:<22} mean={s.mean(): .3f}  std={s.std(): .3f}  "
            f"min={s.min(): .2f}  max={s.max(): .2f}  nan%={s.isna().mean()*100:.1f}"
        )
    print(f"Elapsed: {elapsed:.1f}s")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
