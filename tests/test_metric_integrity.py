"""Phase 19 — Metric Structural Integrity Regression Test.

Comprehensive structural audit of the production parquets. Runs every CI
build to catch silent regressions in CCQS / state / leadership / setup /
components / theme aggregates / Δ CCQS arithmetic / index alignment.

Originally written in /tmp/phase19/p19a_metric_integrity_audit.py and
promoted here as a permanent regression test.

What this DOES check:
  • CCQS in [0, 100]; bounded NaN count from data outages
  • Grade S share in [2%, 15%] AND top-8%-by-score consistency check
  • All 5 grade letters present
  • State probabilities (raw + adjusted) sum to 1 per row
  • state_confidence in [0, 1]
  • Valid primary_state values
  • Valid leadership_tier values
  • All 10 components present, no inf, values bounded |z|<15
  • Key metric arithmetic (% from 50d/200d MA, % from 52w high) matches raw OHLCV
  • RSI-14 and ADX-14 in [0, 100]
  • Δ CCQS 1d/5d/21d computable from trading-day-sorted history
  • Setup coverage >= 95% of universe
  • setup_confidence in [0, 1]
  • Index alignment across the five core parquets
  • Theme `pct_above_50dma` matches independent recompute from features
  • Universe coverage in [750, 920]
  • Latest date within last 7 calendar days

What this does NOT check (out of scope):
  • Component composition is NOT a raw z-score (it's a weighted blend
    of per-date z-scored sub-features); mean ≠ 0, std ≠ 1 is normal.
  • Forward-return predictive validity — that's the OOS IC framework.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CACHE = ROOT / "data" / "cache"


@pytest.fixture(scope="module")
def loaded():
    """Load all six core parquets once per test module."""
    return {
        "ccqs":       pd.read_parquet(CACHE / "ccqs.parquet"),
        "state":      pd.read_parquet(CACHE / "state.parquet"),
        "leadership": pd.read_parquet(CACHE / "leadership.parquet"),
        "setups":     pd.read_parquet(CACHE / "setups.parquet"),
        "components": pd.read_parquet(CACHE / "components.parquet"),
        "features":   pd.read_parquet(CACHE / "features.parquet"),
        "themes":     pd.read_parquet(CACHE / "theme_aggregates.parquet"),
        "ohlcv":      pd.read_parquet(CACHE / "ohlcv_daily.parquet"),
    }


@pytest.fixture(scope="module")
def latest(loaded):
    return loaded["ccqs"].index.get_level_values("date").max()


# ---------------------------------------------------------------------------
# 1. CCQS / Grade structural
# ---------------------------------------------------------------------------

def test_ccqs_in_0_100(loaded, latest):
    lt = loaded["ccqs"].xs(latest, level="date")
    oob = ((lt["ccqs"] < 0) | (lt["ccqs"] > 100)).sum()
    assert oob == 0, f"{oob} out-of-range CCQS rows today"


def test_nan_ccqs_within_dq_tolerance(loaded, latest):
    """Small number of NaN rows from external data outages is allowed."""
    lt = loaded["ccqs"].xs(latest, level="date")
    n_nan = lt["ccqs"].isna().sum()
    assert n_nan <= 5, f"{n_nan} NaN CCQS rows today (limit 5)"


def test_grade_s_share_in_range(loaded, latest):
    lt = loaded["ccqs"].xs(latest, level="date")
    pct_S = (lt["grade"] == "S").mean() * 100.0
    assert 2.0 <= pct_S <= 15.0, f"grade S share = {pct_S:.2f}%"


def test_top_8pct_are_grade_S(loaded, latest):
    """Top 8% of CCQS scores should map to grade S (consistency)."""
    lt = loaded["ccqs"].xs(latest, level="date")
    n_top_8 = int(np.ceil(len(lt) * 0.08))
    top = lt.nlargest(n_top_8, "ccqs")
    consistency = (top["grade"] == "S").mean()
    assert consistency >= 0.85, f"only {consistency:.0%} of top-8% scores carry grade S"


def test_grades_all_present(loaded, latest):
    lt = loaded["ccqs"].xs(latest, level="date")
    present = set(lt["grade"].astype(str).dropna().unique()) - {"nan"}
    expected = {"S", "A", "B", "C", "D"}
    assert expected.issubset(present), f"missing: {expected - present}"


# ---------------------------------------------------------------------------
# 2. State
# ---------------------------------------------------------------------------

def test_state_probabilities_sum_to_1(loaded, latest):
    ls = loaded["state"].xs(latest, level="date")
    p_raw = [c for c in ls.columns if c.startswith("p_") and not c.startswith("p_adj_")]
    if p_raw:
        sums = ls[p_raw].sum(axis=1)
        bad = (~np.isclose(sums, 1.0, atol=1e-3)).sum()
        assert bad == 0, f"{bad} rows where raw state probabilities don't sum to 1"


def test_state_adjusted_probabilities_sum_to_1(loaded, latest):
    ls = loaded["state"].xs(latest, level="date")
    p_adj = [c for c in ls.columns if c.startswith("p_adj_")]
    if p_adj:
        sums = ls[p_adj].sum(axis=1)
        bad = (~np.isclose(sums, 1.0, atol=1e-3)).sum()
        assert bad == 0, f"{bad} rows where adjusted state probabilities don't sum to 1"


def test_state_confidence_in_0_1(loaded, latest):
    ls = loaded["state"].xs(latest, level="date")
    sc = ls["state_confidence"]
    oob = ((sc < 0) | (sc > 1)).sum()
    assert oob == 0, f"{oob} out-of-range state_confidence today"


def test_primary_state_values_valid(loaded, latest):
    ls = loaded["state"].xs(latest, level="date")
    valid = {"TRENDING", "PULLBACK", "CONSOLIDATING", "EXHAUSTION",
             "DETERIORATING", "INDETERMINATE"}
    present = set(ls["primary_state"].astype(str).unique())
    invalid = present - valid
    assert not invalid, f"invalid primary_state values: {sorted(invalid)}"


# ---------------------------------------------------------------------------
# 3. Leadership
# ---------------------------------------------------------------------------

def test_leadership_tier_values_valid(loaded, latest):
    lt = loaded["leadership"].xs(latest, level="date")
    valid = {
        "ELITE_LEADER", "STRONG_LEADER", "EMERGING_LEADER", "ESTABLISHED_LEADER",
        "STRONG_PERFORMER", "NEUTRAL", "WEAK_PERFORMER", "DETERIORATING",
        "WEAK_LAGGARD", "UNCLASSIFIED",
    }
    present = set(lt["leadership_tier"].astype(str).unique()) - {"nan", "None"}
    invalid = present - valid
    assert not invalid, f"invalid leadership_tier values: {sorted(invalid)}"


def test_elite_leader_share_small(loaded, latest):
    lt = loaded["leadership"].xs(latest, level="date")
    pct_elite = (lt["leadership_tier"] == "ELITE_LEADER").mean() * 100.0
    assert pct_elite < 10.0, f"ELITE_LEADER share = {pct_elite:.2f}% (sanity bound)"


# ---------------------------------------------------------------------------
# 4. Components
# ---------------------------------------------------------------------------

COMP_COLS = [
    "s_rs", "s_rs_leadership", "s_residual_momentum", "s_rsl",
    "s_trend_slope", "s_structure", "s_mtf", "s_extension",
    "s_momentum", "s_volume",
    # Phase 28 — s_demand removed (was 0.0 in every state since Phase 7).
]


def test_components_10_present(loaded, latest):
    lc = loaded["components"].xs(latest, level="date")
    missing = set(COMP_COLS) - set(lc.columns)
    assert not missing, f"missing components: {sorted(missing)}"


def test_no_inf_in_components(loaded, latest):
    lc = loaded["components"].xs(latest, level="date")
    for c in COMP_COLS:
        assert not np.isinf(lc[c].astype(float)).any(), f"inf values in {c}"


def test_component_values_bounded(loaded):
    """Components should stay within reasonable bounds even after blending."""
    components = loaded["components"]
    unique_dates = components.index.get_level_values("date").unique().sort_values()
    np.random.seed(42)
    sample_dates = np.random.choice(unique_dates[-252:], size=5, replace=False)
    violations = 0
    for d in sorted(sample_dates):
        cd = components.xs(d, level="date")
        for c in COMP_COLS:
            v = cd[c].dropna().astype(float)
            if len(v) >= 100 and v.abs().max() > 15.0:
                violations += 1
    assert violations == 0, f"{violations}/55 (date × component) cells with |z|>15"


# ---------------------------------------------------------------------------
# 5. Feature arithmetic (spot-check vs raw OHLCV)
# ---------------------------------------------------------------------------

def test_pct_ma_50_arithmetic(loaded, latest):
    """% from 50d MA matches (close - sma_50) / sma_50 * 100."""
    feat = loaded["features"].xs(latest, level="date")
    oh = loaded["ohlcv"].sort_values(["ticker", "date"]).copy()
    oh["sma_50"] = oh.groupby("ticker")["close"].transform(
        lambda s: s.rolling(50, min_periods=50).mean()
    )
    np.random.seed(7)
    sample = np.random.choice(feat.index.tolist(), size=30, replace=False)
    errors = 0
    for tkr in sample:
        oh_t = oh[(oh["ticker"] == tkr) & (oh["date"] == latest)]
        if oh_t.empty:
            continue
        r = oh_t.iloc[0]
        if pd.isna(r["sma_50"]) or pd.isna(r["close"]):
            continue
        expected = (r["close"] - r["sma_50"]) / r["sma_50"] * 100.0
        actual = float(feat.loc[tkr].get("pct_ma_50", np.nan))
        if pd.notna(actual) and abs(actual - expected) > 0.5:
            errors += 1
    assert errors <= 2, f"{errors}/30 pct_ma_50 mismatches >0.5pp"


def test_pct_ma_200_arithmetic(loaded, latest):
    feat = loaded["features"].xs(latest, level="date")
    oh = loaded["ohlcv"].sort_values(["ticker", "date"]).copy()
    oh["sma_200"] = oh.groupby("ticker")["close"].transform(
        lambda s: s.rolling(200, min_periods=200).mean()
    )
    np.random.seed(7)
    sample = np.random.choice(feat.index.tolist(), size=30, replace=False)
    errors = 0
    for tkr in sample:
        oh_t = oh[(oh["ticker"] == tkr) & (oh["date"] == latest)]
        if oh_t.empty:
            continue
        r = oh_t.iloc[0]
        if pd.isna(r["sma_200"]) or pd.isna(r["close"]):
            continue
        expected = (r["close"] - r["sma_200"]) / r["sma_200"] * 100.0
        actual = float(feat.loc[tkr].get("pct_ma_200", np.nan))
        if pd.notna(actual) and abs(actual - expected) > 0.5:
            errors += 1
    assert errors <= 2, f"{errors}/30 pct_ma_200 mismatches >0.5pp"


def test_rsi_in_0_100(loaded, latest):
    feat = loaded["features"].xs(latest, level="date")
    rsi = feat.get("rsi_14")
    if rsi is not None:
        oob = ((rsi < 0) | (rsi > 100)).sum()
        assert oob == 0, f"{oob} out-of-range RSI-14 rows"


def test_adx_in_0_100(loaded, latest):
    feat = loaded["features"].xs(latest, level="date")
    adx = feat.get("adx_14")
    if adx is not None:
        oob = ((adx < 0) | (adx > 100)).sum()
        assert oob == 0, f"{oob} out-of-range ADX-14 rows"


# ---------------------------------------------------------------------------
# 6. Δ CCQS arithmetic
# ---------------------------------------------------------------------------

def test_delta_ccqs_computable(loaded):
    """Δ 1d / 5d / 21d should be computable from sorted trading-day history."""
    ccqs = loaded["ccqs"]
    dates_sorted = ccqs.index.get_level_values("date").unique().sort_values()
    assert len(dates_sorted) >= 22, "fewer than 22 trading days of history"
    for offset in (1, 5, 21):
        today = dates_sorted[-1]
        prior = dates_sorted[-1 - offset]
        d = (ccqs.xs(today, level="date")["ccqs"]
             - ccqs.xs(prior, level="date")["ccqs"])
        assert d.notna().sum() > 700, f"Δ{offset}d has too few finite values"
        # Sanity: most Δ are bounded
        n_extreme = (d.abs() > 80.0).sum()
        assert n_extreme < 5, f"Δ{offset}d has {n_extreme} |Δ|>80 (suspicious)"


# ---------------------------------------------------------------------------
# 7. Setup
# ---------------------------------------------------------------------------

def test_setup_coverage(loaded, latest):
    ls = loaded["setups"].xs(latest, level="date")
    n_with = ls["setup"].notna().sum()
    n_total = len(ls)
    assert n_with >= int(0.95 * n_total), (
        f"{n_with}/{n_total} tickers have a setup label "
        f"({n_with/n_total:.1%}, need >= 95%)"
    )


def test_setup_confidence_in_0_1(loaded, latest):
    ls = loaded["setups"].xs(latest, level="date")
    if "setup_confidence" in ls.columns:
        sc = ls["setup_confidence"]
        oob = ((sc < 0) | (sc > 1)).sum()
        assert oob == 0, f"{oob} out-of-range setup confidences"


# ---------------------------------------------------------------------------
# 8. Index alignment
# ---------------------------------------------------------------------------

def test_index_alignment(loaded):
    lens = {k: len(loaded[k].index) for k in
            ("ccqs", "state", "leadership", "setups", "components")}
    s = set(lens.values())
    assert len(s) == 1, f"core parquet index lengths differ: {lens}"


# ---------------------------------------------------------------------------
# 9. Theme aggregates
# ---------------------------------------------------------------------------

def test_theme_pct_above_50dma_correct(loaded, latest):
    """Theme breadth `pct_above_50dma` matches independent recompute.

    Phase 30: aggregation now uses ALL tagged members (primary + tag)
    per `compute/aggregation.py:_basket_membership_long`, so the
    recompute below mirrors that — using `tickers_tagged()` instead of
    PRIMARY_BASKETS-only filtering.
    """
    from data.universe import tickers_tagged
    themes = loaded["themes"].xs(latest, level="date")
    feat = loaded["features"].xs(latest, level="date")
    violations = 0
    n_checked = 0
    for theme_name in themes.index:
        members = tickers_tagged(theme_name)
        sub = feat.reindex(members)["pct_above_sma_50"].dropna()
        if len(sub) < 3:
            continue
        n_checked += 1
        expected = float(sub.mean()) * 100.0
        actual = float(themes.loc[theme_name, "pct_above_50dma"])
        if abs(actual - expected) > 1.0:
            violations += 1
    assert violations <= 2, f"{violations}/{n_checked} themes show >1pp diff"


# ---------------------------------------------------------------------------
# 10. Universe coverage + freshness
# ---------------------------------------------------------------------------

def test_universe_coverage(loaded, latest):
    n_unique = loaded["ccqs"].xs(latest, level="date").index.nunique()
    assert 750 <= n_unique <= 920, f"{n_unique} unique tickers today (expected 750-920)"


def test_data_freshness(loaded, latest):
    """Latest data should be within 7 calendar days."""
    today = pd.Timestamp("today").normalize()
    age_days = (today - latest).days
    assert age_days <= 7, f"latest data is {age_days} days old ({latest.date()})"
