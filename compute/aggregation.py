"""
CCQS V1 — Theme-Level Aggregation (SPEC Section 12)

Roll per-stock features / CCQS / leadership / setups up to the basket
(theme) level for every populated CORE basket on every date.

Output: data/cache/theme_aggregates.parquet  (index = basket × date)

Run:
    python -m compute.aggregation
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
from data.universe import PRIMARY_BASKET_CONSTITUENTS

OHLCV_PATH = CACHE_DIR / "ohlcv_daily.parquet"
FEATURES_PATH = CACHE_DIR / "features.parquet"
CCQS_PATH = CACHE_DIR / "ccqs.parquet"
STATE_PATH = CACHE_DIR / "state.parquet"
LEADERSHIP_PATH = CACHE_DIR / "leadership.parquet"
SETUP_PATH = CACHE_DIR / "setups.parquet"

AGG_PATH = CACHE_DIR / "theme_aggregates.parquet"
AGG_META_PATH = CACHE_DIR / "theme_aggregates_meta.json"

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")
logger.add(LOG_DIR / "ccqs.log", level="DEBUG", rotation="10 MB", retention="30 days")


THEME_TIERS: list[str] = [
    "ELITE_THEME",
    "STRONG_THEME",
    "EMERGING_THEME",
    "NARROW_LEADERSHIP",
    "STABLE",
    "WEAKENING",
    "BROKEN_THEME",
    "MIXED",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _basket_membership_long() -> pd.DataFrame:
    """Long table (basket, ticker) of constituents for every populated basket."""
    rows: list[tuple[str, str]] = []
    for basket, tickers in PRIMARY_BASKET_CONSTITUENTS.items():
        if len(tickers) < 3:
            continue
        for t in tickers:
            rows.append((basket, t))
    return pd.DataFrame(rows, columns=["basket", "ticker"])


def _safe_z(series: pd.Series) -> pd.Series:
    """Cross-sectional z (mean / std) within each date level. NaNs preserved."""
    g = series.groupby(level="date", sort=False)
    mean = g.transform("mean")
    std = g.transform("std")
    std = std.where(std > 0, 1.0)
    return (series - mean) / std


def _rolling_max(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window=window, min_periods=window).max()


def _classify_momentum(change_30d: pd.Series, change_60d: pd.Series) -> pd.Series:
    """Categorical momentum class per SPEC §12."""
    out = pd.Series("STABLE", index=change_60d.index, dtype=object)
    out[(change_60d >= 7)] = "MODERATE_ACCELERATING"
    out[(change_60d >= 12) & (change_30d >= 7)] = "STRONG_ACCELERATING"
    out[(change_60d < -3) & (change_60d > -7)] = "DECELERATING"
    out[change_60d < -7] = "WEAKENING"
    # |change_60d| < 3 stays STABLE (already default)
    out[change_60d.isna()] = np.nan
    return out


def _classify_concentration(top3_share: pd.Series) -> pd.Series:
    out = pd.Series("BROAD", index=top3_share.index, dtype=object)
    out[(top3_share > 0.35) & (top3_share <= 0.50)] = "MODERATE"
    out[top3_share > 0.50] = "CONCENTRATED"
    out[top3_share.isna()] = np.nan
    return out


def _classify_theme(agg: pd.DataFrame) -> pd.Series:
    """First-match-wins 8-tier theme classifier."""
    tier = pd.Series("MIXED", index=agg.index, dtype=object)

    elite = (
        (agg["theme_ccqs"] >= 90)
        & agg["momentum_class"].isin(["STRONG_ACCELERATING", "MODERATE_ACCELERATING"])
        & agg["theme_rs_new_252d_high"].astype(float).fillna(0).astype(bool)
        & (agg["pct_above_50dma"] >= 75)
    )
    strong = (
        (agg["theme_ccqs"] >= 80)
        & (agg["pct_above_50dma"] >= 60)
        & agg["theme_rs_new_252d_high"].astype(float).fillna(0).astype(bool)
    )
    emerging = (
        (agg["theme_ccqs"] >= 60) & (agg["theme_ccqs"] < 80)
        & (agg["momentum_class"] == "STRONG_ACCELERATING")
        & (agg["pct_above_50dma"] >= 50)
    )
    narrow = (
        (agg["theme_ccqs"] >= 75)
        & (agg["leadership_concentration"] == "CONCENTRATED")
    )
    stable = (agg["theme_ccqs"] >= 50) & (agg["theme_ccqs"] < 75)
    weakening = (
        (agg["theme_ccqs"] < 50)
        & agg["momentum_class"].isin(["DECELERATING", "WEAKENING"])
    )
    broken = agg["pct_broken"] >= 30.0

    # Apply lowest priority first.
    tier[broken.fillna(False)] = "BROKEN_THEME"
    tier[weakening.fillna(False)] = "WEAKENING"
    tier[stable.fillna(False)] = "STABLE"
    tier[narrow.fillna(False)] = "NARROW_LEADERSHIP"
    tier[emerging.fillna(False)] = "EMERGING_THEME"
    tier[strong.fillna(False)] = "STRONG_THEME"
    tier[elite.fillna(False)] = "ELITE_THEME"

    # Where theme_ccqs is NaN (insufficient constituents on a date), null tier.
    tier[agg["theme_ccqs"].isna()] = np.nan
    return tier


# ---------------------------------------------------------------------------
# Main aggregation
# ---------------------------------------------------------------------------

def aggregate_themes(
    features: pd.DataFrame,
    ccqs: pd.DataFrame,
    state: pd.DataFrame,
    leadership: pd.DataFrame,
    setups: pd.DataFrame,
    ohlcv: pd.DataFrame,
) -> pd.DataFrame:
    """Theme-level rollup across all populated baskets and dates.

    Returns a DataFrame indexed by (basket, date) with the full SPEC §12
    metric set + theme_ccqs + theme_class.
    """
    membership = _basket_membership_long()
    universe_tickers = set(features.index.get_level_values("ticker").unique())
    # Keep only basket constituents we actually have data for.
    membership = membership[membership["ticker"].isin(universe_tickers)]
    # Drop baskets that now have <3 active tickers.
    counts = membership.groupby("basket")["ticker"].count()
    valid_baskets = counts[counts >= 3].index
    membership = membership[membership["basket"].isin(valid_baskets)]
    logger.info(
        f"Aggregating {membership['basket'].nunique()} baskets across "
        f"{len(membership)} membership rows"
    )

    # ---------------------------------------------------------------------
    # 1. Compute per-stock new_60d_high flag (not in features table) from ohlcv
    # ---------------------------------------------------------------------
    oh = ohlcv.copy()
    oh = oh.sort_values(["ticker", "date"])
    oh["roll_max_60"] = (
        oh.groupby("ticker")["close"].transform(lambda s: s.rolling(60, min_periods=60).max())
    )
    oh["new_60d_high"] = (oh["close"] >= oh["roll_max_60"]).astype(float)
    oh["new_60d_high"] = oh["new_60d_high"].where(oh["roll_max_60"].notna())
    # Daily close return per ticker for basket RS line.
    oh["close_ret"] = oh.groupby("ticker")["adj_close"].pct_change()
    oh_indexed = oh.set_index(["ticker", "date"]).sort_index()

    # ---------------------------------------------------------------------
    # 2. Build the consolidated per-stock daily frame with everything we need.
    # ---------------------------------------------------------------------
    # Stack subset features that we'll roll up; keep MultiIndex.
    feat_cols = [
        "rs_rating_spy", "pct_ma_50", "pct_ma_200",
        "pct_above_sma_50", "pct_above_sma_200",
        "sma_stack_score", "ema_stack_score", "supertrend_direction",
        "rs_line_spy_new_high_252d", "new_252d_high",
        "up_down_vol_ratio_50", "ad_line_slope_20",
        "cmf_21", "distribution_days_25",
    ]
    miss = [c for c in feat_cols if c not in features.columns]
    if miss:
        raise KeyError(f"Missing expected feature columns: {miss}")
    f_sub = features[feat_cols].copy()

    # ccqs grade + value, primary_state, leadership tier.
    f_sub["ccqs"] = ccqs["ccqs"].astype(float)
    f_sub["grade"] = ccqs["grade"].astype(str)
    f_sub["primary_state"] = state["primary_state"].astype(str)
    f_sub["leadership_tier"] = leadership["leadership_tier"].astype(str)
    f_sub["setup"] = setups["setup"].astype(str)
    f_sub["new_60d_high"] = oh_indexed["new_60d_high"]

    # Long-melt by basket: each membership row × each date.
    # Avoid an N_baskets × N_rows blowup by exploding constituents into the
    # consolidated frame via merge.
    panel = f_sub.reset_index().merge(membership, on="ticker", how="inner")
    # panel columns: ticker, date, <feature cols>, basket
    panel = panel.sort_values(["basket", "date", "ticker"])

    # ---------------------------------------------------------------------
    # 3. Score & breadth aggregates per (basket, date)
    # ---------------------------------------------------------------------
    g = panel.groupby(["basket", "date"], sort=True, observed=True)

    agg = pd.DataFrame(index=g.size().index)
    agg["n_constituents"] = g["ticker"].count()
    agg["n_constituents_with_valid_ccqs"] = g["ccqs"].count()

    agg["avg_ccqs"] = g["ccqs"].mean()
    agg["median_ccqs"] = g["ccqs"].median()
    agg["std_ccqs"] = g["ccqs"].std()
    agg["max_ccqs"] = g["ccqs"].max()
    agg["min_ccqs"] = g["ccqs"].min()
    agg["q25_ccqs"] = g["ccqs"].quantile(0.25)
    agg["q75_ccqs"] = g["ccqs"].quantile(0.75)

    # Breadth — pct_above_sma_50/200 are already 0/1 binaries.
    agg["pct_above_50dma"] = g["pct_above_sma_50"].mean() * 100.0
    agg["pct_above_200dma"] = g["pct_above_sma_200"].mean() * 100.0
    agg["pct_at_60d_high"] = g["new_60d_high"].mean() * 100.0
    agg["pct_at_252d_high"] = g["new_252d_high"].mean() * 100.0
    agg["pct_full_sma_stack"] = (
        g["sma_stack_score"].apply(lambda s: (s >= 75).mean()) * 100.0
    )
    agg["pct_full_ema_stack"] = (
        g["ema_stack_score"].apply(lambda s: (s >= 75).mean()) * 100.0
    )
    agg["pct_supertrend_bull"] = (
        g["supertrend_direction"].apply(lambda s: (s == 1).mean()) * 100.0
    )
    agg["pct_rs_rating_above_70"] = (
        g["rs_rating_spy"].apply(lambda s: (s >= 70).mean()) * 100.0
    )
    agg["pct_rs_rating_above_85"] = (
        g["rs_rating_spy"].apply(lambda s: (s >= 85).mean()) * 100.0
    )
    agg["pct_rs_line_new_high"] = g["rs_line_spy_new_high_252d"].mean() * 100.0
    agg["pct_grade_s"] = g["grade"].apply(lambda s: (s == "S").mean()) * 100.0
    agg["pct_grade_a_plus"] = (
        g["grade"].apply(lambda s: s.isin(["S", "A"]).mean()) * 100.0
    )
    agg["pct_grade_d"] = g["grade"].apply(lambda s: (s == "D").mean()) * 100.0
    agg["pct_climactic"] = (
        g["primary_state"].apply(lambda s: (s == "CLIMACTIC").mean()) * 100.0
    )
    agg["pct_broken"] = (
        g["primary_state"].apply(lambda s: (s == "BROKEN").mean()) * 100.0
    )

    agg["n_elite_leaders"] = g["leadership_tier"].apply(
        lambda s: (s == "ELITE_LEADER").sum()
    )
    agg["n_strong_leaders"] = g["leadership_tier"].apply(
        lambda s: (s == "STRONG_LEADER").sum()
    )
    agg["n_emerging_leaders"] = g["leadership_tier"].apply(
        lambda s: (s == "EMERGING_LEADER").sum()
    )

    # Setup counts
    agg["n_multibagger_setups"] = g["setup"].apply(
        lambda s: (s == "Emerging Leader (Multibagger Setup)").sum()
    )
    agg["n_tier_s_pullback"] = g["setup"].apply(
        lambda s: (s == "Tier S Pullback").sum()
    )
    agg["n_elite_leader_setups"] = g["setup"].apply(
        lambda s: s.isin(["Elite Leader Continuation", "Elite Leader Pullback"]).sum()
    )

    # Volume aggregates
    agg["theme_avg_ud_ratio"] = g["up_down_vol_ratio_50"].mean()
    agg["theme_median_ud_ratio"] = g["up_down_vol_ratio_50"].median()
    agg["theme_pct_strong_ud"] = (
        g["up_down_vol_ratio_50"].apply(lambda s: (s >= 1.5).mean()) * 100.0
    )
    agg["theme_pct_positive_ad"] = (
        g["ad_line_slope_20"].apply(lambda s: (s > 0).mean()) * 100.0
    )
    agg["theme_avg_cmf"] = g["cmf_21"].mean()
    agg["theme_avg_dist_days"] = g["distribution_days_25"].mean()
    agg["theme_volume_confirmation"] = (
        (agg["theme_pct_strong_ud"] >= 40.0)
        & (agg["theme_pct_positive_ad"] >= 50.0)
    )

    # Dispersion
    cv = agg["std_ccqs"] / agg["avg_ccqs"]
    agg["basket_ccqs_cv"] = cv

    def _top_n_share(grp: pd.Series, n: int) -> float:
        v = grp.dropna()
        if v.empty:
            return np.nan
        s = v.nlargest(n).sum()
        total = v.sum()
        if total <= 0:
            return np.nan
        return s / total

    agg["basket_top_3_share"] = g["ccqs"].apply(lambda s: _top_n_share(s, 3))
    agg["basket_top_quartile_share"] = g["ccqs"].apply(
        lambda s: _top_n_share(s, max(1, int(np.ceil(len(s.dropna()) / 4))))
    )
    agg["leadership_concentration"] = _classify_concentration(agg["basket_top_3_share"])

    # ---------------------------------------------------------------------
    # 4. Theme RS Line — basket equal-weighted index / SPY
    # ---------------------------------------------------------------------
    # SPY benchmark returns
    spy = oh[oh["ticker"] == "SPY"][["date", "adj_close"]].drop_duplicates(subset="date")
    spy = spy.sort_values("date").rename(columns={"adj_close": "spy_close"})
    spy["spy_ret"] = spy["spy_close"].pct_change()

    # Basket-level mean daily return — average of constituent close_ret on each date
    panel_for_rs = panel[["basket", "date", "ticker"]].merge(
        oh[["ticker", "date", "close_ret"]], on=["ticker", "date"], how="left"
    )
    bret = (
        panel_for_rs.groupby(["basket", "date"], sort=True)["close_ret"].mean()
        .reset_index()
        .rename(columns={"close_ret": "basket_ret"})
    )
    bret = bret.merge(spy[["date", "spy_ret"]], on="date", how="left")

    # Cumulative indexes per basket (start at 1.0 from first non-NaN return)
    def _cum_idx(s: pd.Series) -> pd.Series:
        return (1.0 + s.fillna(0.0)).cumprod()

    bret["basket_idx"] = bret.groupby("basket")["basket_ret"].transform(_cum_idx)
    bret["spy_idx"] = _cum_idx(bret["spy_ret"])
    bret["theme_rs_line"] = bret["basket_idx"] / bret["spy_idx"]

    # Rolling RS metrics per basket
    def _rs_metrics(g: pd.DataFrame) -> pd.DataFrame:
        x = g["theme_rs_line"].values
        n = len(x)
        out = pd.DataFrame(
            {
                "theme_rs_new_60d_high": np.nan,
                "theme_rs_new_252d_high": np.nan,
                "theme_rs_slope_20d": np.nan,
                "theme_rs_slope_60d": np.nan,
                "theme_rs_r_squared_60d": np.nan,
                "theme_rs_pct_252d": np.nan,
            },
            index=g.index,
        )
        # new highs
        rmax_60 = pd.Series(x).rolling(60, min_periods=60).max().values
        rmax_252 = pd.Series(x).rolling(252, min_periods=252).max().values
        out["theme_rs_new_60d_high"] = (x >= rmax_60).astype(float)
        out["theme_rs_new_60d_high"] = np.where(np.isnan(rmax_60), np.nan, out["theme_rs_new_60d_high"])
        out["theme_rs_new_252d_high"] = (x >= rmax_252).astype(float)
        out["theme_rs_new_252d_high"] = np.where(
            np.isnan(rmax_252), np.nan, out["theme_rs_new_252d_high"]
        )
        # percent change slopes
        out["theme_rs_slope_20d"] = (
            (pd.Series(x).pct_change(20) * 100.0).values
        )
        out["theme_rs_slope_60d"] = (
            (pd.Series(x).pct_change(60) * 100.0).values
        )
        # 60d R-squared of linear fit
        s = pd.Series(x)
        def _rsq(window: np.ndarray) -> float:
            if np.isnan(window).any():
                return np.nan
            n = len(window)
            t = np.arange(n)
            ss_xy = ((t - t.mean()) * (window - window.mean())).sum()
            ss_xx = ((t - t.mean()) ** 2).sum()
            ss_yy = ((window - window.mean()) ** 2).sum()
            if ss_xx <= 0 or ss_yy <= 0:
                return np.nan
            slope = ss_xy / ss_xx
            ss_res = ((window - (window.mean() + slope * (t - t.mean()))) ** 2).sum()
            return 1.0 - ss_res / ss_yy
        out["theme_rs_r_squared_60d"] = s.rolling(60, min_periods=60).apply(_rsq, raw=True).values
        # 252d percentile of current value
        out["theme_rs_pct_252d"] = (
            s.rolling(252, min_periods=60).apply(
                lambda w: (w[-1] >= w).mean() * 100.0, raw=True
            ).values
        )
        return out

    rs_metrics = (
        bret.sort_values(["basket", "date"])
        .groupby("basket", group_keys=False, sort=False)
        .apply(_rs_metrics)
    )

    bret_full = pd.concat([bret.set_index(["basket", "date"]), rs_metrics.set_index(bret.set_index(["basket", "date"]).index)], axis=1)
    bret_full = bret_full.rename(columns={"theme_rs_line": "theme_rs_line_value"})

    # Pull RS line metrics into agg
    rs_cols = [
        "theme_rs_line_value", "theme_rs_new_60d_high", "theme_rs_new_252d_high",
        "theme_rs_slope_20d", "theme_rs_slope_60d", "theme_rs_r_squared_60d",
        "theme_rs_pct_252d",
    ]
    agg = agg.join(bret_full[rs_cols], how="left")

    # ---------------------------------------------------------------------
    # 5. Theme momentum acceleration (avg constituent RS at lookbacks)
    # ---------------------------------------------------------------------
    avg_rs = (
        panel.groupby(["basket", "date"], sort=True)["rs_rating_spy"].mean()
        .rename("avg_rs")
    )
    avg_rs = avg_rs.unstack("basket").sort_index()
    # Shift in trading-day space (≈ calendar lookback / 1.4 but we'll go by rows)
    avg_rs_30 = avg_rs.shift(30)
    avg_rs_60 = avg_rs.shift(60)
    avg_rs_90 = avg_rs.shift(90)

    change_30 = (avg_rs - avg_rs_30).stack().rename("theme_rs_change_30d")
    change_60 = (avg_rs - avg_rs_60).stack().rename("theme_rs_change_60d")
    change_90 = (avg_rs - avg_rs_90).stack().rename("theme_rs_change_90d")
    # stack() returns index (date, basket); swap to (basket, date) to match agg
    change_30 = change_30.swaplevel().sort_index()
    change_60 = change_60.swaplevel().sort_index()
    change_90 = change_90.swaplevel().sort_index()

    agg = agg.join(change_30).join(change_60).join(change_90)
    agg["momentum_class"] = _classify_momentum(
        agg["theme_rs_change_30d"], agg["theme_rs_change_60d"]
    )

    # ---------------------------------------------------------------------
    # 6. Theme CCQS composite (per-date cross-sectional standardization)
    # ---------------------------------------------------------------------
    # Reset to use _safe_z which expects index level "date"
    # agg index is (basket, date) → date is level 1
    agg.index.names = ["basket", "date"]

    def z(col: str, negate: bool = False) -> pd.Series:
        s = agg[col].astype(float)
        if negate:
            s = -s
        return _safe_z(s.swaplevel()).swaplevel()

    breadth_comp = (
        0.30 * z("pct_above_50dma")
        + 0.20 * z("pct_above_200dma")
        + 0.15 * z("pct_at_252d_high")
        + 0.20 * z("pct_rs_rating_above_85")
        + 0.15 * z("pct_grade_a_plus")
    )
    rs_comp = (
        0.40 * z("theme_rs_new_252d_high")
        + 0.30 * z("theme_rs_slope_60d")
        + 0.15 * z("theme_rs_r_squared_60d")
        + 0.15 * z("theme_rs_pct_252d")
    )
    mom_score = (
        0.60 * z("theme_rs_change_60d")
        + 0.40 * z("theme_rs_change_30d")
    )
    vol_score = (
        0.40 * z("theme_pct_strong_ud")
        + 0.30 * z("theme_pct_positive_ad")
        + 0.20 * z("theme_avg_cmf")
        + 0.10 * z("theme_avg_dist_days", negate=True)
    )
    health_score = (
        0.50 * z("pct_climactic", negate=True)
        + 0.50 * z("pct_broken", negate=True)
    )

    theme_ccqs_z = (
        0.25 * z("avg_ccqs")
        + 0.25 * breadth_comp
        + 0.20 * rs_comp
        + 0.15 * mom_score
        + 0.10 * vol_score
        + 0.05 * health_score
    )
    agg["theme_ccqs_z"] = theme_ccqs_z
    # Convert to 0-100 via N(0,1) CDF; clip to [0, 100].
    cdf_vals = norm.cdf(theme_ccqs_z.to_numpy(dtype=float))
    agg["theme_ccqs"] = np.clip(cdf_vals * 100.0, 0.0, 100.0)
    agg["theme_ccqs"] = agg["theme_ccqs"].where(theme_ccqs_z.notna())

    # Component breakdowns (kept for downstream debugging / dashboard)
    agg["theme_breadth_score"] = breadth_comp
    agg["theme_rs_composite"] = rs_comp
    agg["theme_momentum_score"] = mom_score
    agg["theme_volume_score"] = vol_score
    agg["theme_health_score"] = health_score

    # ---------------------------------------------------------------------
    # 7. Theme classification
    # ---------------------------------------------------------------------
    agg["theme_class"] = pd.Categorical(_classify_theme(agg), categories=THEME_TIERS)

    return agg


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    t0 = time.time()
    paths = [FEATURES_PATH, CCQS_PATH, STATE_PATH, LEADERSHIP_PATH, SETUP_PATH, OHLCV_PATH]
    for p in paths:
        if not p.exists():
            logger.error(f"Missing input {p}. Run earlier pipeline stages first.")
            return 1

    features = pd.read_parquet(FEATURES_PATH)
    ccqs = pd.read_parquet(CCQS_PATH)
    state = pd.read_parquet(STATE_PATH)
    leadership = pd.read_parquet(LEADERSHIP_PATH)
    setups = pd.read_parquet(SETUP_PATH)
    ohlcv = pd.read_parquet(OHLCV_PATH)

    logger.info(
        f"Loaded features {features.shape}, ccqs {ccqs.shape}, "
        f"state {state.shape}, leadership {leadership.shape}, "
        f"setups {setups.shape}, ohlcv {ohlcv.shape}"
    )

    agg = aggregate_themes(features, ccqs, state, leadership, setups, ohlcv)
    elapsed = time.time() - t0

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    agg.to_parquet(AGG_PATH, compression="snappy")
    logger.info(
        f"Wrote {AGG_PATH} ({len(agg):,} rows × {len(agg.columns)} cols) "
        f"in {elapsed:.1f}s"
    )

    # Summary metadata
    valid = agg["theme_ccqs"].notna()
    n_baskets = int(agg.index.get_level_values("basket").nunique())
    n_dates = int(agg.index.get_level_values("date").nunique())
    tier_dist = (
        agg["theme_class"].astype(str).value_counts(normalize=True).to_dict()
    )
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "n_rows": int(len(agg)),
        "n_baskets": n_baskets,
        "n_dates": n_dates,
        "n_valid_theme_ccqs": int(valid.sum()),
        "theme_class_distribution": {k: round(v, 4) for k, v in tier_dist.items()},
    }
    AGG_META_PATH.write_text(json.dumps(meta, indent=2, default=str))

    print()
    print("=" * 60)
    print("THEME AGGREGATION SUMMARY")
    print("=" * 60)
    print(f"  Rows:              {len(agg):,}")
    print(f"  Baskets:           {n_baskets}")
    print(f"  Dates:             {n_dates}")
    print(f"  Valid theme_ccqs:  {valid.sum():,}")
    print()
    print("  Theme class distribution (all rows):")
    for t in THEME_TIERS:
        pct = tier_dist.get(t, 0.0) * 100.0
        print(f"    {t:<22} {pct:6.2f}%")
    print(f"Elapsed: {elapsed:.1f}s")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
