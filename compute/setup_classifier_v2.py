"""Phase 25 — Setup classifier v2 (display-layer redesign).

12-label chart-evocative cascade. First-match-wins. Pure descriptive
labels — no predictive language, no gestalt-pattern naming. Replaces
the 27-label cascade in compute/setup_classifier.py (preserved as
legacy for reference; not deleted).

Design principles (verbatim from the Phase 25 spec):

  1. Labels are chart-hooks, not indicator-language.
  2. Describe present state, never predict future outcome.
  3. Decompose patterns into measurable constituents; do not name
     gestalts (no cup-and-handle / wedge / H&S etc.).
  4. Uptrend/Downtrend deliberately omitted — too prevalent to be
     informative.
  5. Threshold values are calibrated starting points — may be tuned
     after coverage analysis on the live universe.
  6. 1-2 word labels are a hard constraint.

All thresholds are either (a) cross-sectional percentiles within the
universe-of-the-day, (b) self-relative ratios against the name's own
trailing history, or (c) scale-invariant % values. No absolute price
levels, no per-name hand-tuned values.

The 12 labels (cascade order, first match wins):

   1. New High
   2. Breakout
   3. Failed Breakout
   4. Tight Base
   5. Coiling
   6. Shallow Pullback
   7. Deep Pullback
   8. Extended
   9. At Highs
  10. Basing Low
  11. Breakdown
  12. Sideways

If no condition matches → empty string ("") — silence beats noise.

Inputs: features.parquet (the additional Phase 25 primitives in
features.py Cat 24 power the cascade — see compute/features.py).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


SETUP_LABELS_V2: list[str] = [
    "New High",
    "Breakout",
    "Failed Breakout",
    "Tight Base",
    "Coiling",
    "Shallow Pullback",
    "Deep Pullback",
    "Extended",
    "At Highs",
    "Basing Low",
    "Breakdown",
    "Sideways",
]


def _bool(s: pd.Series) -> pd.Series:
    """Coerce to a NaN-safe boolean Series (NaN → False)."""
    return s.astype(float).fillna(0).astype(bool)


def _bullish_ma_stack(features: pd.DataFrame) -> pd.Series:
    """close > 21EMA > 50d MA > 200d MA. NaN-safe (NaN → False)."""
    c = features["close"].astype(float)
    e21 = features["ema_21"].astype(float)
    s50 = features["sma_50"].astype(float)
    s200 = features["sma_200"].astype(float)
    return ((c > e21) & (e21 > s50) & (s50 > s200)).fillna(False)


def _cross_sectional_percentile_rank(s: pd.Series) -> pd.Series:
    """Return per-date cross-sectional percentile rank in [0, 1]."""
    return s.groupby(level="date", sort=False).rank(pct=True, method="average")


def classify_setup_v2(features: pd.DataFrame) -> pd.DataFrame:
    """Apply the 12-label cascade to (ticker, date)-indexed feature matrix.

    Returns a DataFrame with the same index, columns ["setup",
    "setup_confidence"]. Confidence is 1.0 for every assigned label
    (boolean classifier, no scoring; preserved for downstream
    compatibility with the legacy setups.parquet schema). Empty-string
    rows have confidence 0.0.
    """
    f = features
    idx = f.index

    # Extract primitives once (avoid repeated .astype calls in the cascade)
    close = f["close"].astype(float)
    sma_50 = f["sma_50"].astype(float)
    sma_200 = f["sma_200"].astype(float)
    ema_21 = f["ema_21"].astype(float)

    new_252_high = _bool(f["new_252d_high"])
    # Phase 25 spec-correct 5d Failed Breakout: within last 5 trading days
    # a Breakout (cond #2) was true on some prior day, AND today's close is
    # below the level cleared by that breakout. See compute/features.py
    # `failed_breakout_flag_5d_v2`. Replaces the legacy 10d-window flag.
    failed_brk = _bool(f["failed_breakout_flag_5d_v2"])
    bb_width_p = f["bb_width_pct_252d"].astype(float)
    pct_ma_50 = f["pct_ma_50"].astype(float)
    pct_from_52w_high = f["pct_from_52w_high"].astype(float)
    pct_from_52w_low = f["pct_from_52w_low"].astype(float)

    # Phase 25 setup-cascade primitives (Cat 24 in features.py)
    close_max_40d = f["close_max_40d"].astype(float)
    close_min_40d = f["close_min_40d"].astype(float)
    pct_from_20d_high = f["pct_from_20d_high"].astype(float)
    range_60d_pct = f["range_60d_pct_of_price"].astype(float)
    range_ratio_20_60 = f["range_20d_to_60d_ratio"].astype(float)
    position_in_60d = f["position_in_60d_range"].astype(float)
    pct_ma_50_p80 = f["pct_ma_50_p80_252d"].astype(float)
    true_range_x_atr = f["true_range_x_atr14"].astype(float)
    adr_pct_20 = f["adr_pct_20"].astype(float)

    bullish_stack = _bullish_ma_stack(f)

    # Cross-sectional percentile ranks (per-date, universe-relative)
    adr_xs_pct = _cross_sectional_percentile_rank(adr_pct_20)

    # Distance from 252d high in % (positive means below the high)
    dist_from_252h_pct = -pct_from_52w_high  # pct_from_52w_high is negative

    # === Cascade evaluation ===
    setup = pd.Series("", index=idx, dtype=object)
    matched = pd.Series(False, index=idx)

    # 1. "New High" — today's close = 252d max AND not extended
    #     (extended new-highs fall through to "Extended" or other labels).
    cond_1 = (
        new_252_high
        & (pct_ma_50 <= pct_ma_50_p80)
    ).fillna(False)
    cond_1 &= ~matched
    setup[cond_1] = "New High"
    matched |= cond_1

    # 2. "Breakout" — closed above prior 40d high with range expansion.
    cond_2 = (
        (close > close_max_40d.shift(1))         # clears prior 40d high
        & (true_range_x_atr > 1.3)               # range expansion confirms
    ).fillna(False)
    cond_2 &= ~matched
    setup[cond_2] = "Breakout"
    matched |= cond_2

    # 3. "Failed Breakout" — flag from feature pipeline (10-day window).
    cond_3 = failed_brk & ~matched
    setup[cond_3] = "Failed Breakout"
    matched |= cond_3

    # 4. "Tight Base" — bullish stack + low cross-sectional ADR + near highs.
    cond_4 = (
        bullish_stack
        & (adr_xs_pct <= 0.25)                   # bottom 25th pct of universe ADR
        & (dist_from_252h_pct <= 5.0)            # within 5% of 252d high
    ).fillna(False)
    cond_4 &= ~matched
    setup[cond_4] = "Tight Base"
    matched |= cond_4

    # 5. "Coiling" — bullish stack + 20d range compressing within 60d
    #    AND BB width in bottom 20th pct of own 252d history.
    cond_5 = (
        bullish_stack
        & (range_ratio_20_60 < 0.6)
        & (bb_width_p <= 20.0)
    ).fillna(False)
    cond_5 &= ~matched
    setup[cond_5] = "Coiling"
    matched |= cond_5

    # 6. "Shallow Pullback" — bullish stack, 3-10% off 20d high, holding 21EMA.
    pct_off_20d = -pct_from_20d_high
    cond_6 = (
        bullish_stack
        & (pct_off_20d >= 3.0) & (pct_off_20d <= 10.0)
        & (close >= ema_21)
    ).fillna(False)
    cond_6 &= ~matched
    setup[cond_6] = "Shallow Pullback"
    matched |= cond_6

    # 7. "Deep Pullback" — bullish stack, 10-20% off 20d high, holding 50d MA.
    cond_7 = (
        bullish_stack
        & (pct_off_20d > 10.0) & (pct_off_20d <= 20.0)
        & (close >= sma_50)
    ).fillna(False)
    cond_7 &= ~matched
    setup[cond_7] = "Deep Pullback"
    matched |= cond_7

    # 8. "Extended" — bullish stack + pct from 50d MA above own 80th-pct.
    cond_8 = (
        bullish_stack
        & (pct_ma_50 > pct_ma_50_p80)
    ).fillna(False)
    cond_8 &= ~matched
    setup[cond_8] = "Extended"
    matched |= cond_8

    # 9. "At Highs" — bullish stack + within 5% of 252d high (residual).
    cond_9 = (
        bullish_stack
        & (dist_from_252h_pct <= 5.0)
    ).fillna(False)
    cond_9 &= ~matched
    setup[cond_9] = "At Highs"
    matched |= cond_9

    # 10. "Basing Low" — within 10% of 252d low AND bottom 40th pct of universe ADR.
    #     Stack-agnostic — catches potential turns or value-trap zones.
    cond_10 = (
        (pct_from_52w_low <= 10.0)
        & (adr_xs_pct <= 0.40)
    ).fillna(False)
    cond_10 &= ~matched
    setup[cond_10] = "Basing Low"
    matched |= cond_10

    # 11. "Breakdown" — closed below prior 40d low AND below 50d MA.
    cond_11 = (
        (close < close_min_40d.shift(1))
        & (close < sma_50)
    ).fillna(False)
    cond_11 &= ~matched
    setup[cond_11] = "Breakdown"
    matched |= cond_11

    # 12. "Sideways" — bounded 60d range (<20% of price) + mid-range position.
    # User-approved widening (Phase 25 validation review): 15% → 20%, 30-70 → 25-75.
    # Preserves Sideways' "deliberately boring, suppress chart-pull" role.
    cond_12 = (
        (range_60d_pct < 20.0)
        & (position_in_60d >= 0.25) & (position_in_60d <= 0.75)
    ).fillna(False)
    cond_12 &= ~matched
    setup[cond_12] = "Sideways"
    matched |= cond_12

    # Confidence: 1.0 when assigned, 0.0 when blank (silence beats noise).
    setup_conf = matched.astype(float)

    out = pd.DataFrame(index=idx)
    # Preserve schema: keep "setup" string column; downstream readers
    # don't require Categorical (setups.parquet read by build_dashboard_cache
    # uses simple string column).
    out["setup"] = setup
    out["setup_confidence"] = setup_conf
    return out
