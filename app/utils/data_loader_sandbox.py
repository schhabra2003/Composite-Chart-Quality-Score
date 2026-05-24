"""Sandbox-side cached data loaders. Mirrors data_loader.py but reads from
data/cache/sandbox/. Production loaders remain unchanged.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SANDBOX_CACHE_DIR = ROOT / "data" / "cache" / "sandbox"
PROD_CACHE_DIR = ROOT / "data" / "cache"
TTL = 1800


# ---------------------------------------------------------------------------
# Raw parquet readers
# ---------------------------------------------------------------------------

@st.cache_data(ttl=TTL, show_spinner=False)
def _read_sandbox_parquet(name: str) -> pd.DataFrame:
    path = SANDBOX_CACHE_DIR / name
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


@st.cache_data(ttl=TTL, show_spinner=False)
def _read_sandbox_json(name: str) -> dict:
    path = SANDBOX_CACHE_DIR / name
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


@st.cache_data(ttl=TTL, show_spinner=False)
def _read_prod_parquet(name: str) -> pd.DataFrame:
    path = PROD_CACHE_DIR / name
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


# ---------------------------------------------------------------------------
# Sandbox basket map (combines production + sandbox baskets)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=TTL, show_spinner=False)
def _sandbox_basket_map() -> dict[str, str]:
    try:
        from data.universe_sandbox import get_sandbox_primary_basket_map
        return get_sandbox_primary_basket_map()
    except Exception:
        return {}


@st.cache_data(ttl=TTL, show_spinner=False)
def _sandbox_only_set() -> set[str]:
    try:
        from data.universe_sandbox import get_sandbox_only_tickers
        return set(get_sandbox_only_tickers())
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Latest-snapshot dashboard frame
# ---------------------------------------------------------------------------

@st.cache_data(ttl=TTL, show_spinner=False)
def load_sandbox_dashboard_data() -> tuple[pd.DataFrame, str]:
    """Combined sandbox latest-snapshot frame + latest date string."""
    ccqs = _read_sandbox_parquet("ccqs.parquet")
    if ccqs.empty:
        return pd.DataFrame(), ""

    states = _read_sandbox_parquet("state.parquet")
    leadership = _read_sandbox_parquet("leadership.parquet")
    setups = _read_sandbox_parquet("setups.parquet")
    features = _read_sandbox_parquet("features.parquet")

    latest = ccqs.index.get_level_values("date").max()

    ccqs_latest = ccqs.xs(latest, level="date")
    states_latest = states.xs(latest, level="date") if not states.empty else pd.DataFrame()
    leadership_latest = leadership.xs(latest, level="date") if not leadership.empty else pd.DataFrame()
    setups_latest = setups.xs(latest, level="date") if not setups.empty else pd.DataFrame()
    features_latest = features.xs(latest, level="date") if not features.empty else pd.DataFrame()

    dates_sorted = ccqs.index.get_level_values("date").unique().sort_values()
    if len(dates_sorted) >= 2:
        prev_date = dates_sorted[-2]
        ccqs_prev = ccqs.xs(prev_date, level="date")["ccqs"]
        ccqs_change = ccqs_latest["ccqs"] - ccqs_prev
    else:
        ccqs_change = pd.Series(0.0, index=ccqs_latest.index)

    basket_map = _sandbox_basket_map()
    baskets = pd.Series(
        ccqs_latest.index.map(lambda t: basket_map.get(t, "\u2014")),
        index=ccqs_latest.index,
        name="basket",
    )

    sandbox_only = _sandbox_only_set()
    sandbox_flag = pd.Series(
        ccqs_latest.index.map(lambda t: "SANDBOX" if t in sandbox_only else "PROD"),
        index=ccqs_latest.index,
        name="origin",
    )

    combined = pd.DataFrame({
        "ccqs":             ccqs_latest["ccqs"],
        "grade":            ccqs_latest["grade"],
        "ccqs_change":      ccqs_change,
        "leadership_tier":  leadership_latest.get("leadership_tier", pd.Series(index=ccqs_latest.index)),
        "primary_state":    states_latest.get("primary_state", pd.Series(index=ccqs_latest.index)),
        "setup_label":      setups_latest.get("setup", pd.Series("\u2014", index=ccqs_latest.index)),
        "basket":           baskets,
        "origin":           sandbox_flag,
        "rs_rating_spy":    features_latest.get("rs_rating_spy", pd.Series(index=ccqs_latest.index)),
    })
    combined = combined.dropna(subset=["ccqs"])
    latest_str = latest.strftime("%Y-%m-%d") if hasattr(latest, "strftime") else str(latest)
    return combined, latest_str


# ---------------------------------------------------------------------------
# Themes (sandbox combined)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=TTL, show_spinner=False)
def load_sandbox_themes_data() -> pd.DataFrame:
    themes = _read_sandbox_parquet("theme_aggregates.parquet")
    if themes.empty:
        return pd.DataFrame()
    latest = themes.index.get_level_values("date").max()
    t_latest = themes.xs(latest, level="date")
    t_latest = t_latest[
        t_latest["theme_ccqs"].notna()
        & (t_latest["n_constituents"] >= 3)
    ].sort_values("theme_ccqs", ascending=False)

    ccqs = _read_sandbox_parquet("ccqs.parquet")
    top_member_map: dict[str, str] = {}
    if not ccqs.empty:
        ccqs_latest = ccqs.xs(latest, level="date") if latest in ccqs.index.get_level_values("date") else pd.DataFrame()
        if not ccqs_latest.empty:
            basket_map = _sandbox_basket_map()
            tmp = ccqs_latest[["ccqs"]].copy()
            tmp["basket"] = tmp.index.map(basket_map)
            tmp = tmp.dropna(subset=["basket"]).reset_index()
            if "ticker" not in tmp.columns:
                tmp = tmp.rename(columns={tmp.columns[0]: "ticker"})
            tmp = tmp.sort_values("ccqs", ascending=False)
            top_member_map = tmp.groupby("basket").head(1).set_index("basket")["ticker"].to_dict()

    t_latest = t_latest.copy()
    t_latest["top_member"] = t_latest.index.map(top_member_map).fillna("\u2014")
    t_latest = t_latest.reset_index().rename(columns={"basket": "basket_name"})
    return t_latest


# ---------------------------------------------------------------------------
# Top stocks (sandbox-only & combined)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=TTL, show_spinner=False)
def load_sandbox_only_top_stocks(n: int = 50) -> pd.DataFrame:
    """Latest-snapshot top N sandbox-only tickers (sorted by CCQS desc)."""
    df, _ = load_sandbox_dashboard_data()
    if df.empty:
        return pd.DataFrame()
    sandbox_only = df[df["origin"] == "SANDBOX"].copy()
    return sandbox_only.sort_values("ccqs", ascending=False).head(n)


@st.cache_data(ttl=TTL, show_spinner=False)
def load_sandbox_top_stocks_combined(n: int = 50) -> pd.DataFrame:
    """Top N stocks across the FULL combined sandbox universe."""
    df, _ = load_sandbox_dashboard_data()
    if df.empty:
        return pd.DataFrame()
    return df.sort_values("ccqs", ascending=False).head(n)


# ---------------------------------------------------------------------------
# Production-vs-sandbox comparison (methodology stability check)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=TTL, show_spinner=False)
def load_sandbox_comparison_stocks(anchors: list[str] | None = None) -> pd.DataFrame:
    """For a list of anchor tickers (default: top 20 production names by CCQS),
    return ccqs_prod, ccqs_sandbox, delta. Validates methodology stability.
    """
    prod_ccqs = _read_prod_parquet("ccqs.parquet")
    sb_ccqs = _read_sandbox_parquet("ccqs.parquet")
    if prod_ccqs.empty or sb_ccqs.empty:
        return pd.DataFrame()

    latest_prod = prod_ccqs.index.get_level_values("date").max()
    latest_sb = sb_ccqs.index.get_level_values("date").max()

    prod_latest = prod_ccqs.xs(latest_prod, level="date")[["ccqs", "grade"]].rename(
        columns={"ccqs": "ccqs_prod", "grade": "grade_prod"}
    )
    sb_latest = sb_ccqs.xs(latest_sb, level="date")[["ccqs", "grade"]].rename(
        columns={"ccqs": "ccqs_sandbox", "grade": "grade_sandbox"}
    )

    if anchors is None:
        anchors = prod_latest.sort_values("ccqs_prod", ascending=False).head(20).index.tolist()

    joined = prod_latest.join(sb_latest, how="inner")
    joined = joined.loc[joined.index.isin(anchors)].copy()
    joined["delta"] = joined["ccqs_sandbox"] - joined["ccqs_prod"]
    joined["abs_delta"] = joined["delta"].abs()
    return joined.sort_values("abs_delta", ascending=False)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

@st.cache_data(ttl=TTL, show_spinner=False)
def load_sandbox_diagnostics() -> dict:
    """Sandbox pipeline meta + per-stage timings + sandbox-only counts."""
    pipeline_meta = _read_sandbox_json("pipeline_meta.json")
    diag = _read_sandbox_json("diagnostics.json")
    missing = _read_sandbox_json("sp500_missing_equities.json")
    out = {
        "pipeline_meta": pipeline_meta,
        "diagnostics": diag,
        "missing_equities_summary": missing.get("summary", {}),
        "fetch_status": missing.get("fetch_status", {}),
        "quality_status": missing.get("quality_status", {}),
    }
    return out


@st.cache_data(ttl=TTL, show_spinner=False)
def load_sandbox_validation_status() -> dict:
    return _read_sandbox_json("validation_report.json")


# ---------------------------------------------------------------------------
# Sector-specific visibility (bottom 10 by sector for sandbox-only)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=TTL, show_spinner=False)
def load_sandbox_top_by_basket(basket: str, n: int = 10) -> pd.DataFrame:
    df, _ = load_sandbox_dashboard_data()
    if df.empty:
        return pd.DataFrame()
    sub = df[df["basket"] == basket].copy()
    return sub.sort_values("ccqs", ascending=False).head(n)
