"""
CCQS V1 — Feature Engineering Layer (SPEC Section 5)

Computes the 104 features per ticker, vectorized across the universe.
TradingView-aligned smoothing: SMA / EMA / Wilder's RMA.

Input:
    data/cache/ohlcv_daily.parquet
    data/cache/data_quality_report.json  (filter to PASS + WARNING)

Output:
    data/cache/features.parquet            MultiIndex (ticker, date), 108 cols
    data/cache/features_meta.json          counts, timings, columns

Run:
    python -m compute.features
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
from scipy import stats as scistats

from compute.loader import CACHE_DIR, LOG_DIR, load_cached_ohlcv
from data.universe import BENCHMARKS, PRIMARY_BASKETS, all_unique_tickers

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FEATURES_PATH = CACHE_DIR / "features.parquet"
FEATURES_META_PATH = CACHE_DIR / "features_meta.json"
QUALITY_REPORT_PATH = CACHE_DIR / "data_quality_report.json"

EPS = 1e-12

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")
logger.add(LOG_DIR / "ccqs.log", level="DEBUG", rotation="10 MB", retention="30 days")


# ---------------------------------------------------------------------------
# Smoothing primitives (TradingView parity)
# ---------------------------------------------------------------------------

def wilder_rma(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Wilder's RMA (alpha=1/n, seeded with SMA(n)) — TradingView parity.

    First (n-1) rows are NaN. At the first SMA-valid row of each column the
    value is replaced with the n-period SMA seed, then the standard
    recursion (alpha=1/n, adjust=False) takes over. Equivalent to Pine's
    `ta.rma()` and SPEC §5 reference implementation.
    """
    sma_seed = df.rolling(n, min_periods=n).mean()
    is_first_valid = sma_seed.notna() & sma_seed.shift(1).isna()
    seeded = df.mask(is_first_valid, sma_seed).mask(sma_seed.isna(), np.nan)
    return seeded.ewm(alpha=1.0 / n, adjust=False, ignore_na=False).mean()


def sma(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.rolling(n, min_periods=n).mean()


def ema(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.ewm(span=n, adjust=False, min_periods=n).mean()


# ---------------------------------------------------------------------------
# Quality-gated universe
# ---------------------------------------------------------------------------

def _load_passing_tickers() -> list[str]:
    """Return PASS + WARNING tickers from the data quality report."""
    if not QUALITY_REPORT_PATH.exists():
        raise FileNotFoundError(
            f"{QUALITY_REPORT_PATH} not found. Run `python -m compute.data_quality` first."
        )
    report = json.loads(QUALITY_REPORT_PATH.read_text())
    keep: list[str] = []
    for t, r in report["results"].items():
        if r.get("status") in ("PASS", "WARNING"):
            keep.append(t)
    return sorted(keep)


def _pivot_ohlcv(long_df: pd.DataFrame, tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Return dict of wide frames (date index, ticker columns) for each OHLCV col.

    The date index is restricted to the SPY trading calendar (canonical US
    market days). yfinance occasionally returns a handful of bars on
    non-NYSE dates for individual tickers — including them would inject
    NaNs into rolling windows for tickers (like NVDA) that didn't trade
    on those days.
    """
    sub = long_df[long_df["ticker"].isin(tickers)].copy()
    sub = sub.sort_values(["date", "ticker"])
    spy_dates = sub.loc[sub["ticker"] == "SPY", "date"].unique()
    sub = sub[sub["date"].isin(spy_dates)]
    wide = {}
    for col in ("open", "high", "low", "close", "adj_close", "volume"):
        wide[col] = sub.pivot(index="date", columns="ticker", values=col).sort_index()
    return wide


# ---------------------------------------------------------------------------
# Cross-sectional rank → 1..99 percentile rating
# ---------------------------------------------------------------------------

def percentile_rating(wide: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional (row-wise) percentile rank scaled to [1, 99]."""
    rank_pct = wide.rank(axis=1, pct=True, na_option="keep")
    rating = (rank_pct * 98.0).round() + 1.0
    return rating.clip(lower=1.0, upper=99.0)


# ---------------------------------------------------------------------------
# Per-ticker helper for state-machine features (supertrend, pivots, VCP)
# ---------------------------------------------------------------------------

def _supertrend_batched(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, atr: np.ndarray,
    multiplier: float = 3.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Supertrend across tickers in parallel.

    Input arrays shape (T, K). Returns (direction, days_since_flip) of shape (T, K).
    The time loop must be sequential (state depends on prior bar) but each
    iteration is vectorized across all K tickers.
    """
    T, K = close.shape
    mid = (high + low) / 2.0
    upper = mid + multiplier * atr
    lower = mid - multiplier * atr

    final_upper = np.full((T, K), np.nan)
    final_lower = np.full((T, K), np.nan)
    direction = np.full((T, K), np.nan)
    days = np.full((T, K), np.nan)

    for i in range(T):
        valid_now = ~np.isnan(atr[i])
        if not valid_now.any():
            continue
        if i == 0:
            prev_upper = np.full(K, np.nan)
            prev_lower = np.full(K, np.nan)
            prev_close = np.full(K, np.nan)
            prev_dir = np.full(K, np.nan)
            prev_days = np.zeros(K)
        else:
            prev_upper = final_upper[i-1]
            prev_lower = final_lower[i-1]
            prev_close = close[i-1]
            prev_dir = direction[i-1]
            prev_days = days[i-1]

        valid_prev = ~np.isnan(prev_upper)
        is_init = valid_now & ~valid_prev

        cond_u = (upper[i] < prev_upper) | (prev_close > prev_upper)
        cond_l = (lower[i] > prev_lower) | (prev_close < prev_lower)
        new_upper = np.where(cond_u, upper[i], prev_upper)
        new_lower = np.where(cond_l, lower[i], prev_lower)
        new_upper = np.where(is_init, upper[i], new_upper)
        new_lower = np.where(is_init, lower[i], new_lower)

        prev_dir_filled = np.where(np.isnan(prev_dir), 1.0, prev_dir)
        dir_curr = np.where(
            (prev_dir_filled == 1) & (close[i] < new_lower), -1.0,
            np.where((prev_dir_filled == -1) & (close[i] > new_upper), 1.0, prev_dir_filled),
        )
        dir_curr = np.where(is_init, 1.0, dir_curr)

        flipped = dir_curr != prev_dir_filled
        new_days = np.where(is_init, 1.0, np.where(flipped, 1.0, prev_days + 1.0))

        final_upper[i] = np.where(valid_now, new_upper, np.nan)
        final_lower[i] = np.where(valid_now, new_lower, np.nan)
        direction[i] = np.where(valid_now, dir_curr, np.nan)
        days[i] = np.where(valid_now, new_days, np.nan)

    return direction, days


def _pivot_counts_one(
    high: np.ndarray, low: np.ndarray, is_ph: np.ndarray, is_pl: np.ndarray,
    lookback: int = 60,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized pivot counts via range-add cumsum.

    For each pivot pair (k-1, k) marked higher, contribute +1 to every t in
    [idx_k, idx_{k-1} + lookback - 1] (both pivots must be in the window).
    """
    n = len(high)
    hh_count = np.zeros(n)
    hl_count = np.zeros(n)
    ph_idxs = np.where(is_ph)[0]
    pl_idxs = np.where(is_pl)[0]

    def _accumulate(idxs: np.ndarray, vals: np.ndarray) -> np.ndarray:
        delta = np.zeros(n + 1)
        for k in range(1, len(idxs)):
            if vals[k] > vals[k-1]:
                start = idxs[k]
                end = min(idxs[k-1] + lookback - 1, n - 1)
                if start <= end:
                    delta[start] += 1
                    delta[end + 1] -= 1
        return np.cumsum(delta[:n])

    if len(ph_idxs) >= 2:
        hh_count = _accumulate(ph_idxs, high[ph_idxs])
    if len(pl_idxs) >= 2:
        hl_count = _accumulate(pl_idxs, low[pl_idxs])
    return np.minimum(hh_count, 3.0), np.minimum(hl_count, 3.0)


def _vcp_score_one(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """Minervini-style VCP detection — scored at each peak then forward-filled."""
    n = len(close)
    score = np.zeros(n)
    win = 10
    if n < 80:
        return score

    # Vectorized peak detection
    c_series = pd.Series(close)
    c_max_centered = c_series.rolling(2 * win + 1, center=True, min_periods=2 * win + 1).max().values
    is_peak = (close == c_max_centered) & ~np.isnan(c_max_centered)
    peak_idxs = np.where(is_peak)[0]
    if len(peak_idxs) < 4:
        return score

    depths = np.full(len(peak_idxs), np.nan)
    vol_meds = np.full(len(peak_idxs), np.nan)
    for k in range(1, len(peak_idxs)):
        a, b = peak_idxs[k-1], peak_idxs[k]
        seg = close[a:b+1]
        seg_v = volume[a:b+1]
        if len(seg) >= 5 and not np.isnan(seg).any():
            depths[k] = (close[a] - np.nanmin(seg)) / close[a]
            vol_meds[k] = np.nanmedian(seg_v)

    score_at_peaks = np.zeros(len(peak_idxs))
    for k in range(3, len(peak_idxs)):
        d = depths[k-2:k+1]
        v = vol_meds[k-2:k+1]
        if np.isnan(d).any() or np.isnan(v).any():
            continue
        contracting = (d[0] > d[1]) and (d[1] > d[2]) and (d[2] > 0)
        vol_drying = (v[0] > v[1]) and (v[1] > v[2])
        if contracting and vol_drying:
            base = 70.0
        elif contracting:
            base = 50.0
        elif vol_drying:
            base = 30.0
        else:
            base = 10.0
        tight_bonus = max(0.0, (0.08 - d[2])) / 0.08 * 30.0
        score_at_peaks[k] = min(100.0, base + tight_bonus)

    # Forward-fill from each peak to the next
    for k, idx in enumerate(peak_idxs):
        nxt = peak_idxs[k+1] if k + 1 < len(peak_idxs) else n
        score[idx:nxt] = score_at_peaks[k]
    return score


def _apply_per_ticker(
    wide_close: pd.DataFrame, wide_high: pd.DataFrame, wide_low: pd.DataFrame,
    wide_volume: pd.DataFrame, atr10: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Batched supertrend + per-ticker (vectorized) pivot/VCP."""
    tickers = wide_close.columns
    idx = wide_close.index

    # Batched supertrend across all tickers
    direction, days = _supertrend_batched(
        wide_high.values, wide_low.values, wide_close.values, atr10.values, multiplier=3.0,
    )

    # Vectorized centered pivots (wide-frame rolling max/min, then equality)
    h_cmax = wide_high.rolling(11, center=True, min_periods=11).max()
    l_cmin = wide_low.rolling(11, center=True, min_periods=11).min()
    ph_mask = ((wide_high == h_cmax) & h_cmax.notna()).values
    pl_mask = ((wide_low == l_cmin) & l_cmin.notna()).values

    hh_arr = np.zeros((len(idx), len(tickers)))
    hl_arr = np.zeros((len(idx), len(tickers)))
    vcp_arr = np.zeros((len(idx), len(tickers)))

    h_vals = wide_high.values
    l_vals = wide_low.values
    c_vals = wide_close.values
    v_vals = wide_volume.values

    for k in range(len(tickers)):
        hh, hl = _pivot_counts_one(
            h_vals[:, k], l_vals[:, k], ph_mask[:, k], pl_mask[:, k], lookback=60,
        )
        hh_arr[:, k] = hh
        hl_arr[:, k] = hl
        vcp_arr[:, k] = _vcp_score_one(c_vals[:, k], v_vals[:, k])

    return {
        "supertrend_direction": pd.DataFrame(direction, index=idx, columns=tickers),
        "supertrend_days_since_flip": pd.DataFrame(days, index=idx, columns=tickers),
        "hh_count_60d": pd.DataFrame(hh_arr, index=idx, columns=tickers),
        "hl_count_60d": pd.DataFrame(hl_arr, index=idx, columns=tickers),
        "vcp_quality_score": pd.DataFrame(vcp_arr, index=idx, columns=tickers),
    }


# ---------------------------------------------------------------------------
# Rolling Hurst exponent (R/S estimator)
# ---------------------------------------------------------------------------

def _rolling_hurst(log_ret: pd.DataFrame, window: int = 252) -> pd.DataFrame:
    """Simple R/S Hurst estimator over a rolling window.

    H > 0.5 → persistent / trending; H < 0.5 → mean-reverting;
    H ≈ 0.5 → random walk. Computed per (date, ticker) over `window` bars of
    log returns. NaN until the first full window. Used by Category 20 trend
    quality features.
    """
    arr = log_ret.values  # (T, K)
    T, K = arr.shape
    out = np.full((T, K), np.nan)
    if T < window:
        return pd.DataFrame(out, index=log_ret.index, columns=log_ret.columns)
    log_n = np.log(float(window))
    for end in range(window - 1, T):
        win = arr[end - window + 1: end + 1]  # (n, K)
        valid = ~np.isnan(win).any(axis=0)
        mu = np.nanmean(win, axis=0)
        dev = win - mu
        cum = np.cumsum(dev, axis=0)
        R = np.nanmax(cum, axis=0) - np.nanmin(cum, axis=0)
        S = np.nanstd(win, axis=0, ddof=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            H = np.log(R / np.where(S == 0, np.nan, S)) / log_n
        out[end] = np.where(valid & (R > 0) & (S > 0), H, np.nan)
    return pd.DataFrame(out, index=log_ret.index, columns=log_ret.columns)


# ---------------------------------------------------------------------------
# Rolling regression over log(close)
# ---------------------------------------------------------------------------

def _rolling_log_regression(
    log_close: pd.DataFrame, window: int = 60,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Rolling OLS on log(close) ~ t over `window` bars.

    Returns: (slope, r_squared, t_stat, residual_z_for_latest)
    All vectorized via per-window numpy ops.
    """
    n = window
    x = np.arange(n, dtype=float)
    x_mean = x.mean()
    x_dev = x - x_mean
    Sxx = (x_dev ** 2).sum()  # scalar

    log_arr = log_close.values  # (T, K)
    T, K = log_arr.shape
    slope = np.full((T, K), np.nan)
    r2 = np.full((T, K), np.nan)
    tstat = np.full((T, K), np.nan)
    z_resid = np.full((T, K), np.nan)

    if T < n:
        return (
            pd.DataFrame(slope, index=log_close.index, columns=log_close.columns),
            pd.DataFrame(r2, index=log_close.index, columns=log_close.columns),
            pd.DataFrame(tstat, index=log_close.index, columns=log_close.columns),
            pd.DataFrame(z_resid, index=log_close.index, columns=log_close.columns),
        )

    for end in range(n - 1, T):
        ywin = log_arr[end - n + 1: end + 1]  # (n, K)
        y_mean = np.nanmean(ywin, axis=0)  # (K,)
        y_dev = ywin - y_mean
        # Mask cols with any NaN in window
        valid = ~np.isnan(ywin).any(axis=0)
        Sxy = (x_dev[:, None] * y_dev).sum(axis=0)
        Syy = (y_dev ** 2).sum(axis=0)

        with np.errstate(divide="ignore", invalid="ignore"):
            b = Sxy / Sxx
            yhat = y_mean + b * (x[-1] - x_mean)  # predicted at last point
            ss_res = Syy - b * Sxy
            ss_tot = Syy
            r2_row = 1.0 - ss_res / np.where(ss_tot == 0, np.nan, ss_tot)
            sigma2 = ss_res / max(n - 2, 1)
            se_b = np.sqrt(sigma2 / Sxx)
            t_row = b / np.where(se_b == 0, np.nan, se_b)
            actual = ywin[-1]
            resid_std = np.sqrt(ss_res / max(n - 2, 1))
            zr = (actual - yhat) / np.where(resid_std == 0, np.nan, resid_std)

        slope[end] = np.where(valid, b, np.nan)
        r2[end] = np.where(valid, r2_row, np.nan)
        tstat[end] = np.where(valid, t_row, np.nan)
        z_resid[end] = np.where(valid, zr, np.nan)

    cols = log_close.columns
    idx = log_close.index
    return (
        pd.DataFrame(slope, index=idx, columns=cols),
        pd.DataFrame(r2, index=idx, columns=cols),
        pd.DataFrame(tstat, index=idx, columns=cols),
        pd.DataFrame(z_resid, index=idx, columns=cols),
    )


# ---------------------------------------------------------------------------
# Within-basket cross-sectional z-score (groupby basket)
# ---------------------------------------------------------------------------

def _rolling_slope(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Per-column rolling OLS slope of y on t over n-bar window."""
    x = np.arange(n, dtype=float)
    x_dev = x - x.mean()
    Sxx = (x_dev ** 2).sum()
    arr = df.values
    T, K = arr.shape
    out = np.full((T, K), np.nan)
    for end in range(n - 1, T):
        ywin = arr[end - n + 1: end + 1]
        valid = ~np.isnan(ywin).any(axis=0)
        ydev = ywin - np.nanmean(ywin, axis=0)
        sxy = (x_dev[:, None] * ydev).sum(axis=0)
        b = sxy / Sxx
        out[end] = np.where(valid, b, np.nan)
    return pd.DataFrame(out, index=df.index, columns=df.columns)


def _within_basket_z(returns_wide: pd.DataFrame, ticker_to_basket: dict[str, str]) -> pd.DataFrame:
    """For each (date, ticker), z-score of `returns_wide` value vs same-basket peers."""
    tickers = returns_wide.columns
    baskets = pd.Series({t: ticker_to_basket.get(t, "UNKNOWN") for t in tickers})
    groups = baskets.groupby(baskets).groups  # basket -> Index of tickers

    out = pd.DataFrame(np.nan, index=returns_wide.index, columns=tickers)
    for basket, members in groups.items():
        if len(members) < 3:
            continue
        sub = returns_wide[members]
        mean = sub.mean(axis=1)
        std = sub.std(axis=1).replace(0, np.nan)
        z = sub.sub(mean, axis=0).div(std, axis=0)
        out[members] = z
    return out


def _within_basket_rank(metric_wide: pd.DataFrame, ticker_to_basket: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Within-basket rank (1=best) and rank_pct."""
    tickers = metric_wide.columns
    baskets = pd.Series({t: ticker_to_basket.get(t, "UNKNOWN") for t in tickers})
    groups = baskets.groupby(baskets).groups

    rank_out = pd.DataFrame(np.nan, index=metric_wide.index, columns=tickers)
    pct_out = pd.DataFrame(np.nan, index=metric_wide.index, columns=tickers)
    for basket, members in groups.items():
        if len(members) < 2:
            continue
        sub = metric_wide[members]
        r = sub.rank(axis=1, ascending=False, method="min", na_option="keep")
        size = sub.notna().sum(axis=1).replace(0, np.nan)
        rank_out[members] = r
        pct_out[members] = r.div(size, axis=0)
    return rank_out, pct_out


# Path 1.5: the `_multi_bench_class` helper (9-class UNIVERSAL/GROWTH/TECH/
# BROAD/DEFENSIVE/... categorical) has been removed along with the
# `multi_bench_leadership_class` feature. Leadership classification now lives
# in the downstream leadership module and uses the 7-tier scheme keyed off
# `rs_rating_spy`, `mtf_rs_coherence`, etc. See SPEC §11.


# ---------------------------------------------------------------------------
# Main feature computation
# ---------------------------------------------------------------------------

FEATURE_ORDER: list[str] = [
    # Cat 1 (9)
    "close", "open", "high", "low", "sma_50", "sma_200", "ema_8", "ema_21", "ema_50",
    # Cat 2 (5)
    "atr_14", "atr_pct", "adr_pct_20", "realized_vol_20", "realized_vol_60",
    # Cat 3 (5)
    "pct_ma_50", "pct_ma_200", "atr_x_50", "atr_x_200", "vol_normalized_extension",
    # Cat 4 (5)
    "trend_slope_60d", "trend_r_squared_60d", "trend_slope_t_stat",
    "trend_slope_significant", "price_z_score_vs_trend",
    # Cat 5 (4)
    "adx_14", "plus_di", "minus_di", "adx_trend_direction",
    # Cat 6 (2)
    "supertrend_direction", "supertrend_days_since_flip",
    # Cat 7 (7)
    "volume", "volume_z_20_252", "up_down_vol_ratio_50",
    "distribution_days_25", "ad_line_slope_20", "cmf_21", "capitulation_volume_flag",
    # Cat 7b (2) — Phase 10 volume pattern: bundled pair feeding s_volume.
    "low_rel_vol_10d", "volume_buzz_50",
    # Cat 8 (4) — single-benchmark RS (Path 1.5)
    "rs_rating_spy",
    "sharpe_momentum_rank_126d", "sortino_rank_126d",
    "within_basket_z_21d",
    # Cat 9 (13) — SPY RS Line + QQQ context-only RS Line
    "rs_line_spy_value", "rs_line_qqq_value",
    "rs_line_spy_new_high_60d", "rs_line_spy_new_high_252d",
    "rs_line_spy_slope_20d", "rs_line_spy_slope_60d", "rs_line_spy_r_squared_60d",
    "rs_line_qqq_new_high_60d", "rs_line_qqq_new_high_252d",
    "rs_line_qqq_slope_20d", "rs_line_qqq_slope_60d",
    "rs_rating_slope_60d", "rs_rating_slope_120d",
    # Cat 9b (3) — Phase 8a residual momentum (beta-adjusted; see comp/feature note).
    "residual_momentum_63d", "residual_momentum_126d", "residual_momentum_252d",
    # Cat 10 (9)
    "sma_stack_score", "ema_stack_score", "hh_count_60d", "hl_count_60d",
    "trend_integrity", "new_252d_high",
    "pct_up_days_21", "failed_breakout_flag_10d",
    # Cat 11 (6)
    "weekly_stack_alignment", "weekly_higher_highs", "weekly_rs_rising",
    "weekly_rsi_14", "weekly_macd_posture", "weekly_trend_slope_sign",
    # Cat 12 (2)
    "monthly_close_above_sma_10", "monthly_higher_highs_3m",
    # Cat 13 (1)
    "mtf_rs_coherence",
    # Cat 14 (7)
    "rsi_14", "macd_line", "macd_signal", "macd_histogram", "macd_posture",
    "bullish_divergence_20d", "bearish_divergence_20d",
    # Cat 15 (6)
    "bb_upper_20", "bb_lower_20", "bb_width_pct_252d", "bb_squeeze_flag",
    "vcp_quality_score", "base_duration_days",
    # Cat 16 (3)
    "days_near_52w_high_60d", "consecutive_high_intensity", "climax_volume_flag",
    # Cat 17 (4)
    "within_basket_z_63d", "within_basket_z_126d",
    "within_basket_rank", "within_basket_rank_pct",
    # Cat 18 (1)
    "volume_leadership_confirmed",
    # Cat 19: REMOVED (Path 1.5) — was `multi_bench_leadership_class`
    # Additional (7) — Path C dropped 4 noise features here.
    "pct_above_sma_50", "pct_above_sma_200",
    "weekly_rs_new_high_26w", "monthly_rs_rising_3m", "monthly_rs_rising_6m",
    "pct_from_52w_high", "pct_from_52w_low",
    # Cat 20 (4) — Trend Quality (Path D): persistence / smoothness signals
    # that are hard to read from the chart but predictive of medium-long term
    # trend continuation.
    "hurst_exponent_252d", "return_autocorrelation_60d_lag1",
    "return_smoothness_60d", "trend_rsquared_252d",
    # Cat 21 (4) — Volatility Quality (Path D): asymmetric & sustained-drawdown
    # vol measures that complement realized_vol/ATR.
    "upside_vol_60d", "downside_vol_60d",
    "ulcer_index_60d", "gain_to_pain_ratio_252d",
    # Cat 22 (4) — Risk-Adjusted Performance (Path D): multi-horizon Sharpe
    # ranks, tail-ratio, information ratio vs SPY.
    "sharpe_rank_60d", "sharpe_rank_252d",
    "tail_ratio_252d", "information_ratio_252d",
    # Cat 23 (10) — Horizon-Specific (Path E): 21d / 60d momentum-quality
    # signals targeted at the 20–60d forward-return horizon, where prior
    # CCQS had its weakest IC (≈0.01). Strong 126d IC (≈0.037) suggests
    # the score reads long-cycle quality well but underweights medium-term
    # momentum; Cat 23 closes that gap.
    "momentum_21d_pct", "rs_line_spy_slope_21d", "ad_line_slope_21d",
    "bb_position_21d",
    "sharpe_ratio_60d", "information_ratio_60d", "sortino_ratio_60d",
    "max_drawdown_pct_60d",
    "return_autocorrelation_21d_lag1", "vol_percentile_21d",
]
assert len(FEATURE_ORDER) == 126, f"FEATURE_ORDER has {len(FEATURE_ORDER)} entries, expected 126"


def compute_features(long_df: pd.DataFrame) -> pd.DataFrame:
    """Compute all 104 features. Returns long DataFrame with MultiIndex (ticker, date)."""
    declared = set(all_unique_tickers())
    universe = [t for t in _load_passing_tickers() if t in declared and t not in BENCHMARKS]
    bench = sorted(BENCHMARKS)
    needed = sorted(set(universe) | set(bench))
    logger.info(f"Computing features for {len(universe)} tickers (+ {len(bench)} benchmarks)")

    wide = _pivot_ohlcv(long_df, needed)
    o, h, l, c, ac, v = wide["open"], wide["high"], wide["low"], wide["close"], wide["adj_close"], wide["volume"]

    feats: dict[str, pd.DataFrame] = {}

    # --- Category 1: Price-Based ----------------------------------------
    feats["close"] = c
    feats["open"] = o
    feats["high"] = h
    feats["low"] = l
    feats["sma_50"] = sma(c, 50)
    feats["sma_200"] = sma(c, 200)
    feats["ema_8"] = ema(c, 8)
    feats["ema_21"] = ema(c, 21)
    feats["ema_50"] = ema(c, 50)

    # --- Category 2: Volatility & Range ---------------------------------
    prev_c = c.shift(1)
    tr_arr = np.maximum.reduce([
        (h - l).values,
        (h - prev_c).abs().values,
        (l - prev_c).abs().values,
    ])
    tr = pd.DataFrame(tr_arr, index=c.index, columns=c.columns)
    atr14 = wilder_rma(tr, 14)
    feats["atr_14"] = atr14
    feats["atr_pct"] = atr14 / c * 100.0
    feats["adr_pct_20"] = np.log(h / l.replace(0, np.nan)).rolling(20, min_periods=20).mean() * 100.0
    daily_ret = c.pct_change(fill_method=None)
    feats["realized_vol_20"] = daily_ret.rolling(20, min_periods=20).std() * np.sqrt(252) * 100.0
    feats["realized_vol_60"] = daily_ret.rolling(60, min_periods=60).std() * np.sqrt(252) * 100.0

    # --- Category 3: Position & Extension -------------------------------
    feats["pct_ma_50"] = (c - feats["sma_50"]) / feats["sma_50"] * 100.0
    feats["pct_ma_200"] = (c - feats["sma_200"]) / feats["sma_200"] * 100.0
    feats["atr_x_50"] = (c - feats["sma_50"]) / atr14.replace(0, np.nan)
    feats["atr_x_200"] = (c - feats["sma_200"]) / atr14.replace(0, np.nan)
    adr_floor = feats["adr_pct_20"].clip(lower=1.0)
    feats["vol_normalized_extension"] = feats["atr_x_50"] / adr_floor

    # --- Category 4: Trend Slope & Regression ---------------------------
    log_c = np.log(c.replace(0, np.nan))
    slope, r2, tstat, zresid = _rolling_log_regression(log_c, window=60)
    feats["trend_slope_60d"] = (np.exp(slope * 252.0) - 1.0) * 100.0
    feats["trend_r_squared_60d"] = r2
    feats["trend_slope_t_stat"] = tstat
    feats["trend_slope_significant"] = (tstat.abs() > 1.96).astype(float)
    feats["price_z_score_vs_trend"] = zresid

    # --- Category 5: Trend Strength (ADX/DI) ----------------------------
    up_move = h.diff()
    dn_move = -l.diff()
    plus_dm = up_move.where((up_move > dn_move) & (up_move > 0), 0.0)
    minus_dm = dn_move.where((dn_move > up_move) & (dn_move > 0), 0.0)
    plus_dm_smooth = wilder_rma(plus_dm, 14)
    minus_dm_smooth = wilder_rma(minus_dm, 14)
    plus_di = 100.0 * plus_dm_smooth / atr14.replace(0, np.nan)
    minus_di = 100.0 * minus_dm_smooth / atr14.replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_14 = wilder_rma(dx, 14)
    feats["adx_14"] = adx_14
    feats["plus_di"] = plus_di
    feats["minus_di"] = minus_di
    feats["adx_trend_direction"] = pd.DataFrame(
        np.where(plus_di > minus_di, 1.0, -1.0),
        index=c.index, columns=c.columns,
    ).where(plus_di.notna() & minus_di.notna())

    # --- Category 6: Supertrend + Cat 10 pivot/structure (state machine) -
    atr10 = wilder_rma(tr, 10)
    per_ticker = _apply_per_ticker(c, h, l, v, atr10)
    feats["supertrend_direction"] = per_ticker["supertrend_direction"]
    feats["supertrend_days_since_flip"] = per_ticker["supertrend_days_since_flip"]

    # --- Category 7: Volume ---------------------------------------------
    feats["volume"] = v
    vol_mean_20 = v.rolling(20, min_periods=20).mean()
    vol_mean_252 = v.rolling(252, min_periods=252).mean()
    vol_std_252 = v.rolling(252, min_periods=252).std()
    feats["volume_z_20_252"] = (vol_mean_20 - vol_mean_252) / vol_std_252.replace(0, np.nan)

    ret_sign = daily_ret.copy()
    up_vol = v.where(ret_sign > 0, 0.0)
    dn_vol = v.where(ret_sign < 0, 0.0)
    ud_ratio_50 = up_vol.rolling(50, min_periods=20).sum() / dn_vol.rolling(50, min_periods=20).sum().replace(0, np.nan)
    feats["up_down_vol_ratio_50"] = ud_ratio_50

    # Distribution days: close < prev_close * 0.998 AND vol > prev_vol
    is_dist = (c < prev_c * 0.998) & (v > v.shift(1))
    feats["distribution_days_25"] = is_dist.astype(float).rolling(25, min_periods=10).sum()

    # A/D line slope (20-day OLS of ad_line on time)
    clv = ((c - l) - (h - c)) / (h - l).replace(0, np.nan)
    ad_increment = (clv * v).fillna(0.0)
    ad_line = ad_increment.cumsum()
    feats["ad_line_slope_20"] = _rolling_slope(ad_line, 20)

    cmf = (clv * v).rolling(21, min_periods=21).sum() / v.rolling(21, min_periods=21).sum().replace(0, np.nan)
    feats["cmf_21"] = cmf

    vol_avg_50 = v.rolling(50, min_periods=20).mean()
    high_50 = h.rolling(50, min_periods=20).max()
    low_50 = l.rolling(50, min_periods=20).min()
    rng_50 = (high_50 - low_50).replace(0, np.nan)
    in_bottom_20 = (c - low_50) / rng_50 < 0.20
    feats["capitulation_volume_flag"] = ((v > 3.0 * vol_avg_50) & (daily_ret < -0.02) & in_bottom_20).astype(float)

    # --- Category 7b: Volume pattern (Phase 10, 2026-05-26) --------------
    # Two NEW orthogonal volume features identified by the Phase 10
    # investigation. They are scored together by the new `s_volume`
    # component (compute/components.py); the two MUST ship as a bundled
    # pair — investigation Config W6 (low_rel_vol alone) actively hurt
    # CCQS IC at every horizon, while combined with volume_buzz_50
    # they produce the only post-Phase-8a config to clear walk-forward
    # paired t > +1.96 (at 5d) and CI > 0 on per-date IC delta.
    #
    # Empirical basis: MarketSmith-style volume patterns.
    # • low_rel_vol_10d (dry-up flag) — orthogonal IC +0.005 at 60d/126d
    #   (CI strictly > 0). Identifies consolidation/dry-up days that
    #   carry forward-return signal AFTER controlling for the other
    #   10 components.
    # • volume_buzz_50 (single-day surge vs 50d mean) — standalone AND
    #   orthogonal IC +0.006 at 5d/20d (CI > 0). Carries the short-
    #   horizon edge that the existing volume features (volume_z_20_252)
    #   miss because they smooth over 20 days.
    #
    # NaN%: ~18% of (ticker, date) rows are NaN until the 252d warmup
    # period (driven by other long-window features in the cache) is met;
    # this is expected and gracefully handled by compute_ccqs() which
    # treats NaN as 0 weight for those rows. Standalone NaN% is closer
    # to 6% (volume_buzz_50 needs 50d) / 4% (low_rel_vol_10d needs 10d).
    #
    # NO LOOK-AHEAD: both features use only data available at time t.
    # low_rel_vol_10d compares v[t] to min(v[t-9:t+1]); volume_buzz_50
    # compares v[t] to mean(v[t-49:t+1]). Both are causal.
    rolling_min_10 = v.rolling(10, min_periods=10).min()
    feats["low_rel_vol_10d"] = (v.le(rolling_min_10)).astype(float)
    feats["low_rel_vol_10d"] = feats["low_rel_vol_10d"].where(rolling_min_10.notna())

    vma_50 = v.rolling(50, min_periods=50).mean()
    feats["volume_buzz_50"] = ((v / vma_50.replace(0, np.nan)) - 1.0) * 100.0

    # --- Category 8 & 9: Single-benchmark RS (vs SPY) + QQQ context ------
    # Path 1.5: cross-sectional RS rating is computed only vs SPY. QQQ RS Line
    # is retained as context-only (raw line + slope + new-high flags) but is
    # NOT cross-sectionally percentile-ranked. IWM was dropped entirely.
    # Rationale: per-horizon ranks under the slope-composite formulation are
    # benchmark-invariant (dividing all stocks by the same constant
    # `(1+r_B_n)` doesn't reorder them), so SPY/QQQ/IWM cross-sectional
    # ranks were ~Pearson 1.0000 (`Multi-benchmark` report, prior turn).
    # QQQ Line is still useful for visual peer context and leadership
    # gating, but doesn't deserve a competing cross-sectional rank.
    spy_c = c["SPY"] if "SPY" in c.columns else None
    qqq_c = c["QQQ"] if "QQQ" in c.columns else None
    if spy_c is None or qqq_c is None:
        raise RuntimeError("Benchmarks (SPY/QQQ) missing from OHLCV cache")

    def _rs_line(bench_close: pd.Series) -> pd.DataFrame:
        line = c.div(bench_close, axis=0)
        base = line.bfill().iloc[0]
        return line.div(base) * 100.0

    rs_line_spy = _rs_line(spy_c)
    rs_line_qqq = _rs_line(qqq_c)
    feats["rs_line_spy_value"] = rs_line_spy
    feats["rs_line_qqq_value"] = rs_line_qqq

    # Cross-sectional RS Rating vs SPY (continuous percentile, [1,99]).
    slope_63 = (rs_line_spy / rs_line_spy.shift(63) - 1.0) * 100.0
    slope_126 = (rs_line_spy / rs_line_spy.shift(126) - 1.0) * 100.0
    slope_189 = (rs_line_spy / rs_line_spy.shift(189) - 1.0) * 100.0
    slope_252 = (rs_line_spy / rs_line_spy.shift(252) - 1.0) * 100.0
    rs_composite_spy = 0.40 * slope_63 + 0.20 * slope_126 + 0.20 * slope_189 + 0.20 * slope_252
    rank_pct = rs_composite_spy.rank(axis=1, pct=True, na_option="keep")
    rs_spy = ((rank_pct * 98.0) + 1.0).clip(lower=1.0, upper=99.0)
    feats["rs_rating_spy"] = rs_spy

    # Sharpe / Sortino momentum ranks (126d)
    mean_126 = daily_ret.rolling(126, min_periods=126).mean()
    vol_126 = daily_ret.rolling(126, min_periods=126).std().replace(0, np.nan)
    sharpe_126 = mean_126 / vol_126
    feats["sharpe_momentum_rank_126d"] = percentile_rating(sharpe_126)
    down = daily_ret.where(daily_ret < 0)
    dvol_126 = down.rolling(126, min_periods=20).std().replace(0, np.nan)
    sortino_126 = mean_126 / dvol_126
    feats["sortino_rank_126d"] = percentile_rating(sortino_126)

    ret_21 = c / c.shift(21) - 1.0
    ticker_to_basket = {t: PRIMARY_BASKETS.get(t, "UNKNOWN") for t in c.columns}
    feats["within_basket_z_21d"] = _within_basket_z(ret_21, ticker_to_basket)

    # Category 9: RS line acceleration / new highs
    def _is_new_high(line: pd.DataFrame, w: int) -> pd.DataFrame:
        prior_max = line.shift(1).rolling(w - 1, min_periods=w - 1).max()
        return (line >= prior_max).astype(float)

    def _slope_pct(line: pd.DataFrame, n: int) -> pd.DataFrame:
        return (line - line.shift(n)) / line.shift(n).replace(0, np.nan) * 100.0

    feats["rs_line_spy_new_high_60d"] = _is_new_high(rs_line_spy, 60)
    feats["rs_line_spy_new_high_252d"] = _is_new_high(rs_line_spy, 252)
    feats["rs_line_spy_slope_20d"] = _slope_pct(rs_line_spy, 20)
    feats["rs_line_spy_slope_60d"] = _slope_pct(rs_line_spy, 60)
    log_rs_spy = np.log(rs_line_spy.replace(0, np.nan))
    _, r2_rs, _, _ = _rolling_log_regression(log_rs_spy, window=60)
    feats["rs_line_spy_r_squared_60d"] = r2_rs

    # QQQ context-only RS Line features (raw, not cross-sectionally ranked).
    feats["rs_line_qqq_new_high_60d"] = _is_new_high(rs_line_qqq, 60)
    feats["rs_line_qqq_new_high_252d"] = _is_new_high(rs_line_qqq, 252)
    feats["rs_line_qqq_slope_20d"] = _slope_pct(rs_line_qqq, 20)
    feats["rs_line_qqq_slope_60d"] = _slope_pct(rs_line_qqq, 60)

    feats["rs_rating_slope_60d"] = rs_spy - rs_spy.shift(60)
    feats["rs_rating_slope_120d"] = rs_spy - rs_spy.shift(120)

    # --- Category 9b: Residual (idiosyncratic) momentum vs SPY ----------
    # Phase 8a (2026-05-26): adds beta-adjusted residual return aggregations
    # at 63 / 126 / 252-day horizons. The 126d residual feeds the new
    # `s_residual_momentum` component in compute/components.py at 5% weight
    # per state in compute/ccqs.py.
    #
    # Empirical basis: Blitz–Huij–Martens (2011) "Residual Momentum" and
    # subsequent fund-implementation replications (Robeco production, plus
    # multiple quant fund replications) — removing the market-beta exposure
    # from momentum returns yields cleaner alpha with higher capacity and
    # lower correlation with passive market beta.
    #
    # Phase 8a empirical validation (in-memory pre-implementation test):
    #   • Standalone 252d-lookback IC at 126d-fwd = +0.0466 (t=14.4)
    #   • Orthogonal-to-`s_rs` residual at 126d-fwd: IC=+0.0246, t=+8.63
    #     (overwhelmingly significant incremental signal beyond s_rs)
    #   • Walk-forward paired t-test: 60d t=2.05, 126d t=2.72
    #   • 126d walk-forward t-stat: 1.87 (Phase 7) → 2.02 (Config B)
    #     — clears the institutional t > 2.0 threshold
    #   • 23 of 24 (state × horizon) cells improve
    #
    # Methodology (no look-ahead):
    #   1. Compute SPY daily log return.
    #   2. For each ticker, compute daily log return.
    #   3. Rolling 252-day OLS beta on log returns using
    #         cov_W(r_i, r_SPY) / var_W(r_SPY)
    #      (Bessel-corrected: cov uses W/(W-1) factor; pandas .var is
    #      already sample by default — equivalent estimator).
    #   4. Trailing beta `β_lag1 = β_252d.shift(1)` (use yesterday's beta
    #      for today's return — eliminates look-ahead).
    #   5. Daily residual: `r_resid[t] = r_i[t] - β_lag1[t] · r_SPY[t]`.
    #   6. Aggregate `r_resid` by simple sum over 63 / 126 / 252-day
    #      windows (no skip-month; user empirical-only directive).
    #
    # Cross-sectional standardization happens in components.py
    # (`_compute_s_residual_momentum` applies per-date robust z).
    log_c_local = np.log(c.replace(0, np.nan))
    log_ret_daily = log_c_local.diff()  # (date × ticker) wide frame of daily log returns
    spy_log_ret = np.log(spy_c.replace(0, np.nan)).diff()
    W_beta = 252
    # Rolling moments — match the Phase 8a investigation script exactly
    spy_mean_w = spy_log_ret.rolling(W_beta, min_periods=W_beta).mean()
    spy_var_w  = spy_log_ret.rolling(W_beta, min_periods=W_beta).var()
    cross_w    = log_ret_daily.mul(spy_log_ret, axis=0)
    cross_mean_w = cross_w.rolling(W_beta, min_periods=W_beta).mean()
    lr_mean_w    = log_ret_daily.rolling(W_beta, min_periods=W_beta).mean()
    # Population covariance × W/(W-1) → sample covariance, then / sample variance.
    cov_252d = (cross_mean_w - lr_mean_w.mul(spy_mean_w, axis=0)) * (W_beta / (W_beta - 1))
    beta_252d = cov_252d.div(spy_var_w, axis=0)
    beta_lag1 = beta_252d.shift(1)
    resid_daily = log_ret_daily.sub(beta_lag1.mul(spy_log_ret, axis=0))
    feats["residual_momentum_63d"]  = resid_daily.rolling(63,  min_periods=63).sum()
    feats["residual_momentum_126d"] = resid_daily.rolling(126, min_periods=126).sum()
    feats["residual_momentum_252d"] = resid_daily.rolling(252, min_periods=252).sum()

    # --- Category 10: Structure & Pivots --------------------------------
    above_sma50 = (c > feats["sma_50"]).astype(float)
    above_sma200 = (c > feats["sma_200"]).astype(float)
    sma50_above_sma200 = (feats["sma_50"] > feats["sma_200"]).astype(float)
    stack = above_sma50 * 30 + above_sma200 * 30 + sma50_above_sma200 * 30
    aligned_bonus = ((above_sma50 == 1) & (above_sma200 == 1) & (sma50_above_sma200 == 1)).astype(float) * 10
    feats["sma_stack_score"] = stack + aligned_bonus

    e_align = (c > feats["ema_8"]) & (feats["ema_8"] > feats["ema_21"]) & (feats["ema_21"] > feats["ema_50"])
    e_partial = (c > feats["ema_8"]).astype(float) * 30 + (feats["ema_8"] > feats["ema_21"]).astype(float) * 30 + (feats["ema_21"] > feats["ema_50"]).astype(float) * 30
    feats["ema_stack_score"] = e_partial + e_align.astype(float) * 10

    feats["hh_count_60d"] = per_ticker["hh_count_60d"]
    feats["hl_count_60d"] = per_ticker["hl_count_60d"]
    feats["trend_integrity"] = ((per_ticker["hh_count_60d"] >= 2) & (per_ticker["hl_count_60d"] >= 2)).astype(float)

    high_20_prior = h.shift(1).rolling(20, min_periods=20).max()
    high_252_prior = h.shift(1).rolling(252, min_periods=252).max()
    feats["new_252d_high"] = (c >= high_252_prior).astype(float)
    feats["pct_up_days_21"] = (daily_ret > 0).astype(float).rolling(21, min_periods=21).mean()

    broke_high = (c >= high_20_prior).astype(float)
    broke_recent = broke_high.rolling(10, min_periods=1).max()
    feats["failed_breakout_flag_10d"] = ((broke_recent == 1) & (c < high_20_prior)).astype(float)

    # --- Category 11: Weekly --------------------------------------------
    weekly_close = c.resample("W-FRI").last()
    weekly_high = h.resample("W-FRI").max()
    weekly_low = l.resample("W-FRI").min()
    weekly_volume = v.resample("W-FRI").sum()
    w_ema10 = ema(weekly_close, 10)
    w_sma30 = sma(weekly_close, 30)
    w_sma40 = sma(weekly_close, 40)
    weekly_stack = ((weekly_close > w_ema10) & (w_ema10 > w_sma30) & (w_sma30 > w_sma40)).astype(float)
    weekly_hh = (weekly_high.rolling(8, min_periods=8).max() > weekly_high.shift(8).rolling(8, min_periods=8).max()).astype(float)
    w_rs_spy_line = weekly_close.div(weekly_close["SPY"], axis=0)
    weekly_rs_rising = (w_rs_spy_line > w_rs_spy_line.shift(5)).astype(float)

    def _rsi_wilder(close_df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
        ch = close_df.diff()
        gain = ch.clip(lower=0)
        loss = -ch.clip(upper=0)
        avg_gain = wilder_rma(gain, n)
        avg_loss = wilder_rma(loss, n)
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100.0 - 100.0 / (1.0 + rs)
    weekly_rsi = _rsi_wilder(weekly_close, 14)

    # Weekly MACD posture
    w_ema12 = ema(weekly_close, 12)
    w_ema26 = ema(weekly_close, 26)
    w_macd = w_ema12 - w_ema26
    w_macd_arr = np.where(w_macd > 0, "Positive", "Negative").astype(object)
    w_macd_arr[w_macd.isna().values] = None
    weekly_macd_posture = pd.DataFrame(w_macd_arr, index=w_macd.index, columns=w_macd.columns, dtype=object)

    # Weekly trend slope sign (26-week regression on log price)
    log_wc = np.log(weekly_close.replace(0, np.nan))
    w_slope, _, _, _ = _rolling_log_regression(log_wc, window=26)
    weekly_slope_sign = np.sign(w_slope)

    # Resample daily index -> nearest weekly bar
    def _ffill_weekly(weekly_df: pd.DataFrame) -> pd.DataFrame:
        return weekly_df.reindex(c.index, method="ffill")

    feats["weekly_stack_alignment"] = _ffill_weekly(weekly_stack)
    feats["weekly_higher_highs"] = _ffill_weekly(weekly_hh)
    feats["weekly_rs_rising"] = _ffill_weekly(weekly_rs_rising)
    feats["weekly_rsi_14"] = _ffill_weekly(weekly_rsi)
    feats["weekly_macd_posture"] = _ffill_weekly(weekly_macd_posture)
    feats["weekly_trend_slope_sign"] = _ffill_weekly(weekly_slope_sign)

    # --- Category 12: Monthly -------------------------------------------
    monthly_close = c.resample("ME").last()
    monthly_high = h.resample("ME").max()
    m_sma10 = sma(monthly_close, 10)
    feats["monthly_close_above_sma_10"] = (monthly_close > m_sma10).astype(float).reindex(c.index, method="ffill")
    m_hh3 = ((monthly_high > monthly_high.shift(1)) & (monthly_high.shift(1) > monthly_high.shift(2))).astype(float)
    feats["monthly_higher_highs_3m"] = m_hh3.reindex(c.index, method="ffill")

    # --- Category 13: MTF Coherence -------------------------------------
    rs_daily = rs_line_spy
    rs_weekly = weekly_close.div(weekly_close["SPY"], axis=0)
    rs_monthly = monthly_close.div(monthly_close["SPY"], axis=0)
    d_rising = (rs_daily > rs_daily.shift(5)).astype(int)
    w_rising = (rs_weekly > rs_weekly.shift(1)).astype(int).reindex(c.index, method="ffill").fillna(0).astype(int)
    m_rising = (rs_monthly > rs_monthly.shift(1)).astype(int).reindex(c.index, method="ffill").fillna(0).astype(int)
    feats["mtf_rs_coherence"] = (d_rising + w_rising + m_rising).astype(float)

    # --- Category 14: Momentum oscillators ------------------------------
    feats["rsi_14"] = _rsi_wilder(c, 14)
    macd_line = ema(c, 12) - ema(c, 26)
    macd_signal = macd_line.ewm(span=9, adjust=False, min_periods=9).mean()
    macd_hist = macd_line - macd_signal
    feats["macd_line"] = macd_line
    feats["macd_signal"] = macd_signal
    feats["macd_histogram"] = macd_hist

    # MACD posture (string): "Positive/Accelerating/Strong" etc.
    sign_arr = np.where(macd_line > 0, "Positive", "Negative").astype(object)
    hist_diff = macd_hist.diff()
    pos_acc = ((macd_line > 0) & (hist_diff > 0)).values
    neg_acc = ((macd_line < 0) & (hist_diff < 0)).values
    dir_arr = np.where(pos_acc | neg_acc, "Accelerating", "Decelerating").astype(object)
    hist_strength_thresh = macd_hist.abs().rolling(50, min_periods=10).mean() * 1.5
    strength_arr = np.where(macd_hist.abs() > hist_strength_thresh, "Strong", "Weak").astype(object)
    posture_arr = np.char.add(np.char.add(np.char.add(
        sign_arr.astype(str), "/"), dir_arr.astype(str)), "/" + strength_arr.astype(str))
    posture_arr = posture_arr.astype(object)
    posture_arr[macd_line.isna().values] = None
    feats["macd_posture"] = pd.DataFrame(posture_arr, index=c.index, columns=c.columns, dtype=object)

    # Divergences (20d)
    def _divergence(price: pd.DataFrame, osc: pd.DataFrame, window: int, kind: str) -> pd.DataFrame:
        # bullish: price LL, osc HL ; bearish: price HH, osc LH
        first_half_end = window // 2
        # split window into two halves
        if kind == "bullish":
            p_recent_min = price.rolling(first_half_end, min_periods=first_half_end).min()
            p_prior_min = price.shift(first_half_end).rolling(first_half_end, min_periods=first_half_end).min()
            o_recent_min = osc.rolling(first_half_end, min_periods=first_half_end).min()
            o_prior_min = osc.shift(first_half_end).rolling(first_half_end, min_periods=first_half_end).min()
            return ((p_recent_min < p_prior_min) & (o_recent_min > o_prior_min)).astype(float)
        else:
            p_recent_max = price.rolling(first_half_end, min_periods=first_half_end).max()
            p_prior_max = price.shift(first_half_end).rolling(first_half_end, min_periods=first_half_end).max()
            o_recent_max = osc.rolling(first_half_end, min_periods=first_half_end).max()
            o_prior_max = osc.shift(first_half_end).rolling(first_half_end, min_periods=first_half_end).max()
            return ((p_recent_max > p_prior_max) & (o_recent_max < o_prior_max)).astype(float)

    feats["bullish_divergence_20d"] = _divergence(c, feats["rsi_14"], 20, "bullish")
    feats["bearish_divergence_20d"] = _divergence(c, feats["rsi_14"], 20, "bearish")

    # --- Category 15: Pattern Setup -------------------------------------
    sma20 = sma(c, 20)
    std20 = c.rolling(20, min_periods=20).std()
    bb_upper = sma20 + 2.0 * std20
    bb_lower = sma20 - 2.0 * std20
    feats["bb_upper_20"] = bb_upper
    feats["bb_lower_20"] = bb_lower
    bb_width = (bb_upper - bb_lower) / sma20.replace(0, np.nan)
    feats["bb_width_pct_252d"] = bb_width.rolling(252, min_periods=60).rank(pct=True) * 100.0

    ema20 = ema(c, 20)
    kc_upper = ema20 + 1.5 * atr10
    kc_lower = ema20 - 1.5 * atr10
    feats["bb_squeeze_flag"] = ((bb_upper < kc_upper) & (bb_lower > kc_lower)).astype(float)

    feats["vcp_quality_score"] = per_ticker["vcp_quality_score"]

    high_252 = h.rolling(252, min_periods=60).max()
    feats["base_duration_days"] = (c < high_252 * 0.90).astype(float).rolling(252, min_periods=60).sum()

    # --- Category 16: Climax --------------------------------------------
    near_52w = (c >= 0.97 * h.rolling(252, min_periods=60).max()).astype(float)
    feats["days_near_52w_high_60d"] = near_52w.rolling(60, min_periods=20).sum()
    close_to_52w = (c >= 0.97 * h.rolling(252, min_periods=60).max()).astype(float)
    feats["consecutive_high_intensity"] = close_to_52w.rolling(5, min_periods=5).sum()
    in_top_20 = (c - low_50) / rng_50 > 0.80
    feats["climax_volume_flag"] = ((v > 4.0 * vol_avg_50) & (daily_ret > 0.05) & in_top_20).astype(float)

    # --- Category 17: Within-basket leadership --------------------------
    ret_63 = c / c.shift(63) - 1.0
    ret_126 = c / c.shift(126) - 1.0
    feats["within_basket_z_63d"] = _within_basket_z(ret_63, ticker_to_basket)
    feats["within_basket_z_126d"] = _within_basket_z(ret_126, ticker_to_basket)
    rank_df, pct_df = _within_basket_rank(ret_63, ticker_to_basket)
    feats["within_basket_rank"] = rank_df
    feats["within_basket_rank_pct"] = pct_df

    # --- Category 18: Volume leadership ---------------------------------
    ad_slope_60 = _rolling_slope(ad_line, 60)
    feats["volume_leadership_confirmed"] = (
        (feats["up_down_vol_ratio_50"] >= 1.5)
        & (ad_slope_60 > 0.05)
        & (feats["distribution_days_25"] <= 3)
    ).astype(float)

    # --- Additional 11 --------------------------------------------------
    feats["pct_above_sma_50"] = above_sma50
    feats["pct_above_sma_200"] = above_sma200

    w_rs_line_spy = weekly_close.div(weekly_close["SPY"], axis=0)
    w_rs_prior = w_rs_line_spy.shift(1).rolling(26, min_periods=26).max()
    weekly_rs_new_high = (w_rs_line_spy >= w_rs_prior).astype(float)
    feats["weekly_rs_new_high_26w"] = weekly_rs_new_high.reindex(c.index, method="ffill")

    m_rs_line_spy = monthly_close.div(monthly_close["SPY"], axis=0)
    feats["monthly_rs_rising_3m"] = (m_rs_line_spy > m_rs_line_spy.shift(3)).astype(float).reindex(c.index, method="ffill")
    feats["monthly_rs_rising_6m"] = (m_rs_line_spy > m_rs_line_spy.shift(6)).astype(float).reindex(c.index, method="ffill")

    # Removed (Path C): `recent_5d_returns_consistency`, `golden_cross_60d`,
    # `death_cross_60d`, `recent_volume_surge_5d`. All four were noisy or
    # redundant; replaced by Category 20 short-term signal features below.

    rolling_high_252 = h.rolling(252, min_periods=60).max().replace(0, np.nan)
    rolling_low_252 = l.rolling(252, min_periods=60).min().replace(0, np.nan)
    feats["pct_from_52w_high"] = (c / rolling_high_252 - 1.0) * 100.0
    feats["pct_from_52w_low"] = (c / rolling_low_252 - 1.0) * 100.0

    # --- Category 20: Trend Quality (Path D) ----------------------------
    # Persistence / smoothness signals — invisible to naked-eye chart
    # reading but informative for medium-long term trend continuation.
    log_ret = np.log1p(daily_ret)
    feats["hurst_exponent_252d"] = _rolling_hurst(log_ret, window=252)

    ret_lag1 = daily_ret.shift(1)
    feats["return_autocorrelation_60d_lag1"] = (
        daily_ret.rolling(60, min_periods=40).corr(ret_lag1)
    )

    smooth_mean_60 = daily_ret.rolling(60, min_periods=40).mean()
    smooth_std_60 = daily_ret.rolling(60, min_periods=40).std()
    feats["return_smoothness_60d"] = (
        smooth_mean_60.abs() / smooth_std_60.replace(0, np.nan)
    )

    _, r2_252, _, _ = _rolling_log_regression(log_c, window=252)
    feats["trend_rsquared_252d"] = r2_252

    # --- Category 21: Volatility Quality (Path D) -----------------------
    pos_ret = daily_ret.where(daily_ret > 0)
    neg_ret = daily_ret.where(daily_ret < 0)
    feats["upside_vol_60d"] = pos_ret.rolling(60, min_periods=20).std() * 100.0
    feats["downside_vol_60d"] = neg_ret.rolling(60, min_periods=20).std() * 100.0

    # Ulcer index: sqrt(mean(drawdown²)) over a 60d window, drawdown taken
    # against a rolling 60d high (in percent).
    rolling_max_60 = c.rolling(60, min_periods=20).max().replace(0, np.nan)
    drawdown_pct = (c / rolling_max_60 - 1.0) * 100.0
    feats["ulcer_index_60d"] = (
        (drawdown_pct ** 2).rolling(60, min_periods=20).mean().pow(0.5)
    )

    pos_sum_252 = daily_ret.where(daily_ret > 0, 0.0).rolling(252, min_periods=252).sum()
    neg_sum_252 = daily_ret.where(daily_ret < 0, 0.0).rolling(252, min_periods=252).sum()
    feats["gain_to_pain_ratio_252d"] = (
        pos_sum_252 / neg_sum_252.abs().replace(0, np.nan)
    )

    # --- Category 22: Risk-Adjusted Performance (Path D) ----------------
    mean_60 = daily_ret.rolling(60, min_periods=40).mean()
    std_60 = daily_ret.rolling(60, min_periods=40).std().replace(0, np.nan)
    sharpe_60 = mean_60 / std_60 * np.sqrt(252)
    feats["sharpe_rank_60d"] = percentile_rating(sharpe_60)

    mean_252 = daily_ret.rolling(252, min_periods=200).mean()
    std_252 = daily_ret.rolling(252, min_periods=200).std().replace(0, np.nan)
    sharpe_252 = mean_252 / std_252 * np.sqrt(252)
    feats["sharpe_rank_252d"] = percentile_rating(sharpe_252)

    # tail_ratio_252d — p95/|p5| of daily returns. The raw ratio is skewed
    # by construction, so we store the cross-sectional percentile rank to
    # keep it on the same scale as the other rank-style features.
    p95_252 = daily_ret.rolling(252, min_periods=200).quantile(0.95)
    p5_252 = daily_ret.rolling(252, min_periods=200).quantile(0.05)
    raw_tail = p95_252 / p5_252.abs().replace(0, np.nan)
    feats["tail_ratio_252d"] = percentile_rating(raw_tail)

    # information_ratio_252d — alpha vs SPY divided by tracking error.
    spy_ret = daily_ret["SPY"]
    excess = daily_ret.sub(spy_ret, axis=0)
    excess_mean_252 = excess.rolling(252, min_periods=200).mean()
    excess_std_252 = excess.rolling(252, min_periods=200).std().replace(0, np.nan)
    feats["information_ratio_252d"] = (
        excess_mean_252 / excess_std_252 * np.sqrt(252)
    )

    # --- Category 23: Horizon-Specific (Path E) -------------------------
    # 21d / 60d momentum-quality signals to lift IC at the 20–60d horizon.
    ret_21d_raw = (c / c.shift(21) - 1.0) * 100.0
    feats["momentum_21d_pct"] = percentile_rating(ret_21d_raw)

    feats["rs_line_spy_slope_21d"] = (
        (rs_line_spy / rs_line_spy.shift(21) - 1.0) * 100.0
    )
    feats["ad_line_slope_21d"] = _rolling_slope(ad_line, 21)

    # bb_position_21d — average position within the Bollinger envelope over
    # last 21 days. ~0.5 = mid-band, ~1 = near upper, ~0 = near lower.
    bb_width_raw = (bb_upper - bb_lower).replace(0, np.nan)
    bb_pos = (c - bb_lower) / bb_width_raw
    feats["bb_position_21d"] = bb_pos.rolling(21, min_periods=15).mean()

    # 60d Sharpe (raw value, complementary to sharpe_rank_60d which is the
    # cross-sectional rank of this same quantity).
    feats["sharpe_ratio_60d"] = sharpe_60

    # 60d information ratio vs SPY.
    excess_mean_60 = excess.rolling(60, min_periods=40).mean()
    excess_std_60 = excess.rolling(60, min_periods=40).std().replace(0, np.nan)
    feats["information_ratio_60d"] = (
        excess_mean_60 / excess_std_60 * np.sqrt(252)
    )

    # 60d Sortino — only-negative-day std as the denominator.
    down_60 = daily_ret.where(daily_ret < 0).rolling(60, min_periods=20).std().replace(0, np.nan)
    feats["sortino_ratio_60d"] = mean_60 / down_60 * np.sqrt(252)

    # 60d max drawdown — minimum of `drawdown_pct` over a 60d window,
    # cross-sectionally ranked so deeper drawdowns score LOWER.
    # `drawdown_pct` from Cat 21 is already in percent and against the
    # rolling-60d high; here we capture the worst point within the trailing
    # 60d window.
    max_dd_60d = drawdown_pct.rolling(60, min_periods=20).min()  # negative numbers
    feats["max_drawdown_pct_60d"] = percentile_rating(max_dd_60d)

    # 21d AR(1) coefficient of daily returns — short-horizon persistence.
    feats["return_autocorrelation_21d_lag1"] = (
        daily_ret.rolling(21, min_periods=15).corr(ret_lag1)
    )

    # 21d realized vol cross-sectional percentile.
    realized_vol_21d_raw = daily_ret.rolling(21, min_periods=21).std() * np.sqrt(252) * 100.0
    feats["vol_percentile_21d"] = percentile_rating(realized_vol_21d_raw)

    # ------------------------------------------------------------------
    # Drop benchmarks from the universe output. Stack to long form.
    # ------------------------------------------------------------------
    universe_set = set(universe)
    long_pieces: dict[str, pd.Series] = {}
    for name in FEATURE_ORDER:
        wf = feats[name]
        # Restrict to scored universe (drop benchmark cols)
        cols_keep = [t for t in wf.columns if t in universe_set]
        sub = wf[cols_keep]
        long_pieces[name] = sub.stack(future_stack=True)

    out = pd.DataFrame(long_pieces)
    out.index.names = ["date", "ticker"]
    out = out.swaplevel(0, 1).sort_index()
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    t0 = time.time()
    long_df = load_cached_ohlcv()
    logger.info(f"Loaded OHLCV cache: {len(long_df):,} rows, {long_df['ticker'].nunique()} tickers")
    features = compute_features(long_df)
    elapsed = time.time() - t0

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    features.to_parquet(FEATURES_PATH, compression="snappy")
    logger.info(f"Wrote {FEATURES_PATH}  ({len(features):,} rows, {len(features.columns)} cols) in {elapsed:.1f}s")

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "n_tickers": int(features.index.get_level_values("ticker").nunique()),
        "n_rows": int(len(features)),
        "n_features": int(len(features.columns)),
        "date_min": str(features.index.get_level_values("date").min().date()),
        "date_max": str(features.index.get_level_values("date").max().date()),
        "columns": list(features.columns),
    }
    FEATURES_META_PATH.write_text(json.dumps(meta, indent=2, default=str))
    logger.info(f"Wrote {FEATURES_META_PATH}")

    print()
    print("=" * 60)
    print("FEATURE ENGINEERING SUMMARY")
    print("=" * 60)
    print(f"Tickers:    {meta['n_tickers']}")
    print(f"Features:   {meta['n_features']}")
    print(f"Rows:       {meta['n_rows']:,}")
    print(f"Date range: {meta['date_min']} -> {meta['date_max']}")
    print(f"Elapsed:    {elapsed:.1f}s")
    print("=" * 60)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
