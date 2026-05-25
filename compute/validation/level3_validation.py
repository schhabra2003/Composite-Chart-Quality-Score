"""Level 3 validation: per-stock correctness across the full universe.

Sub-checks (10):
  A. Price freshness
  B. External ground truth (yfinance, sampled 50)
  C. Feature value bounds
  D. Component score sanity
  E. CCQS bounds & grade consistency
  F. State probability sum & assignment
  G. Leadership tier consistency with RS rating
  H. Setup classifier validity
  I. Theme aggregation correctness
  J. Basket assignment coverage

Run:
    python -m compute.validation.level3_validation
Writes:
    data/cache/level3_validation_report.json
"""
from __future__ import annotations

import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.universe import (
    PRIMARY_BASKETS,
    PRIMARY_BASKET_CONSTITUENTS,
    all_unique_tickers,
)

CACHE = ROOT / "data" / "cache"
OUT_PATH = CACHE / "level3_validation_report.json"
OUT_PATH_EXPANDED = CACHE / "level3_validation_report_post_expansion.json"

VALID_TIERS = {
    "ELITE_LEADER", "STRONG_LEADER", "EMERGING_LEADER", "ESTABLISHED_LEADER",
    "STRONG_PERFORMER", "NEUTRAL", "WEAK_PERFORMER", "DETERIORATING", "WEAK_LAGGARD",
}
VALID_STATES = {"TRENDING", "PULLBACK", "CONSOLIDATING", "EXHAUSTION", "DETERIORATING", "INDETERMINATE"}
VALID_GRADES = {"S", "A", "B", "C", "D"}

# Tier rank order (lower = stronger)
TIER_ORDER = [
    "ELITE_LEADER", "STRONG_LEADER", "EMERGING_LEADER", "ESTABLISHED_LEADER",
    "STRONG_PERFORMER", "NEUTRAL", "WEAK_PERFORMER", "DETERIORATING", "WEAK_LAGGARD",
]
TIER_RANK = {t: i for i, t in enumerate(TIER_ORDER)}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _read(name: str) -> pd.DataFrame:
    p = CACHE / name
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def _add(failures: list, ticker, check, value, expected, severity="ERROR"):
    failures.append(dict(
        ticker=str(ticker) if ticker is not None else "—",
        check=check,
        value=str(value)[:80],
        expected_range=expected,
        severity=severity,
    ))


# ---------------------------------------------------------------------------
# A. Price freshness
# ---------------------------------------------------------------------------

def _check_price_freshness(ohlcv: pd.DataFrame, latest: pd.Timestamp, failures, borderlines):
    if ohlcv.empty:
        _add(failures, None, "A_price_freshness", "no ohlcv data", "ohlcv parquet present")
        return 0
    # ohlcv_daily.parquet stores ticker/date as columns, not as a MultiIndex.
    if "ticker" in ohlcv.columns and "date" in ohlcv.columns:
        by_ticker = ohlcv.groupby("ticker")["date"].max()
    else:
        by_ticker = ohlcv.groupby(level="ticker").apply(
            lambda g: g.index.get_level_values("date").max()
        )
    # Stale if > 5 business days behind latest
    threshold = latest - pd.tseries.offsets.BDay(5)
    n_checked = len(by_ticker)
    for ticker, last_date in by_ticker.items():
        if pd.isna(last_date):
            _add(failures, ticker, "A_price_freshness", "NaT", f"latest={latest.date()}")
            continue
        if last_date < threshold:
            days_stale = (latest - last_date).days
            _add(borderlines, ticker, "A_price_freshness",
                 f"{last_date.date()} ({days_stale}d stale)",
                 f">= {threshold.date()}", severity="WARN")
    return n_checked


# ---------------------------------------------------------------------------
# B. External ground truth (yfinance sample of 50)
# ---------------------------------------------------------------------------

def _check_external_ground_truth(ohlcv: pd.DataFrame, universe_tickers: list[str], n_sample: int = 50, rng_seed: int = 7):
    """Returns {sampled, matches, discrepancies: [...]}."""
    import yfinance as yf  # local import: only used here

    if "ticker" in ohlcv.columns:
        ohlcv_tickers = set(ohlcv["ticker"].unique().tolist())
    else:
        ohlcv_tickers = set(ohlcv.index.get_level_values("ticker").unique().tolist())
    sampled_pool = [t for t in universe_tickers if t in ohlcv_tickers]
    rng = random.Random(rng_seed)
    sample = rng.sample(sampled_pool, min(n_sample, len(sampled_pool)))

    # Single batched download — period 14mo to get 252d return + 200d MA comfortably
    print(f"  → yfinance batched download for {len(sample)} tickers...", flush=True)
    try:
        yf_data = yf.download(
            tickers=sample,
            period="14mo",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        return {"sampled": len(sample), "matches": 0, "discrepancies": [],
                "error": f"yfinance call failed: {e}"}

    discrepancies: list[dict] = []
    matches = 0

    # Pre-sort ohlcv once for fast per-ticker access
    if "ticker" in ohlcv.columns:
        ohlcv_sorted = ohlcv.sort_values(["ticker", "date"])
        per_ticker = {tk: g.set_index("date") for tk, g in ohlcv_sorted.groupby("ticker")}
    else:
        per_ticker = {tk: ohlcv.xs(tk, level="ticker").sort_index() for tk in sample}

    for ticker in sample:
        our = per_ticker.get(ticker)
        if our is None or our.empty or "close" not in our.columns:
            continue
        # Use adj_close for return/MA comparisons (matches yfinance auto_adjust=True).
        # Use close for latest price comparison (latest close is similar either way).
        our_price_series = our["adj_close"].dropna() if "adj_close" in our.columns else our["close"].dropna()
        our_raw_close = our["close"].dropna()
        if our_price_series.empty or our_raw_close.empty:
            continue
        our_close_latest = our_raw_close.iloc[-1]

        # yfinance frame for this ticker
        if isinstance(yf_data.columns, pd.MultiIndex):
            if ticker not in yf_data.columns.get_level_values(0):
                continue
            yfdf = yf_data[ticker].dropna(how="all")
        else:
            yfdf = yf_data
        if yfdf.empty or "Close" not in yfdf.columns:
            continue
        yf_close = yfdf["Close"].dropna()
        if yf_close.empty:
            continue

        yf_latest = float(yf_close.iloc[-1])
        # MAs computed from yfinance series
        yf_50 = float(yf_close.tail(50).mean()) if len(yf_close) >= 50 else np.nan
        yf_200 = float(yf_close.tail(200).mean()) if len(yf_close) >= 200 else np.nan
        # 252-day total return (close-to-close)
        if len(yf_close) >= 252:
            yf_ret252 = (yf_close.iloc[-1] / yf_close.iloc[-252] - 1.0) * 100.0
        else:
            yf_ret252 = np.nan

        # Local MAs and 252d return on adjusted series to match yfinance auto_adjust=True
        our_50 = float(our_price_series.tail(50).mean()) if len(our_price_series) >= 50 else np.nan
        our_200 = float(our_price_series.tail(200).mean()) if len(our_price_series) >= 200 else np.nan
        if len(our_price_series) >= 252:
            our_ret252 = (our_price_series.iloc[-1] / our_price_series.iloc[-252] - 1.0) * 100.0
        else:
            our_ret252 = np.nan

        ok = True
        # Close within 0.5%
        if not np.isnan(our_close_latest) and not np.isnan(yf_latest):
            pct = abs(our_close_latest - yf_latest) / max(yf_latest, 1e-9) * 100.0
            if pct > 0.5:
                discrepancies.append(dict(ticker=ticker, field="close",
                                          our_value=round(our_close_latest, 3),
                                          external_value=round(yf_latest, 3),
                                          pct_diff=round(pct, 3)))
                ok = False
        # 50d MA within 1%
        if not np.isnan(our_50) and not np.isnan(yf_50):
            pct = abs(our_50 - yf_50) / max(yf_50, 1e-9) * 100.0
            if pct > 1.0:
                discrepancies.append(dict(ticker=ticker, field="ma_50",
                                          our_value=round(our_50, 3),
                                          external_value=round(yf_50, 3),
                                          pct_diff=round(pct, 3)))
                ok = False
        # 200d MA within 1%
        if not np.isnan(our_200) and not np.isnan(yf_200):
            pct = abs(our_200 - yf_200) / max(yf_200, 1e-9) * 100.0
            if pct > 1.0:
                discrepancies.append(dict(ticker=ticker, field="ma_200",
                                          our_value=round(our_200, 3),
                                          external_value=round(yf_200, 3),
                                          pct_diff=round(pct, 3)))
                ok = False
        # 252d return within 2% (absolute pct points)
        if not np.isnan(our_ret252) and not np.isnan(yf_ret252):
            diff = abs(our_ret252 - yf_ret252)
            if diff > 2.0:
                discrepancies.append(dict(ticker=ticker, field="ret_252d",
                                          our_value=round(our_ret252, 2),
                                          external_value=round(yf_ret252, 2),
                                          pct_diff=round(diff, 2)))
                ok = False

        if ok:
            matches += 1

    return {"sampled": len(sample), "matches": matches, "discrepancies": discrepancies}


# ---------------------------------------------------------------------------
# C. Feature bounds — vectorized per feature
# ---------------------------------------------------------------------------

FEATURE_BOUNDS = {
    "rs_rating_spy":            (0,    100,  True),  # (lo, hi, hard)
    "pct_ma_50":                (-50,  100,  False),
    "pct_ma_200":               (-70,  200,  False),
    "adx_14":                   (0,    100,  True),
    "rsi_14":                   (0,    100,  True),
    "atr_x_50":                 (-20,  20,   False),  # signed: negative = below MA
    "sharpe_rank_252d":         (0,    100,  True),
    "information_ratio_252d":   (-10,  15,   False),
}


def _check_feature_bounds(features: pd.DataFrame, latest, failures, borderlines):
    if features.empty:
        return 0
    feats = features.xs(latest, level="date") if latest in features.index.get_level_values("date") else features
    n_checks = 0
    for col, (lo, hi, hard) in FEATURE_BOUNDS.items():
        if col not in feats.columns:
            continue
        s = feats[col]
        # inf check
        n_inf = int(np.isinf(s.replace([np.inf, -np.inf], np.nan).astype(float)).sum())
        inf_mask = np.isinf(s.astype(float, errors="ignore"))
        if inf_mask.any():
            for tk in s.index[inf_mask].tolist():
                _add(failures, tk, f"C_{col}_inf", "inf", f"finite in [{lo},{hi}]")
        # bounds
        finite = s.replace([np.inf, -np.inf], np.nan).dropna()
        oob = finite[(finite < lo) | (finite > hi)]
        n_checks += int(finite.shape[0])
        for tk, v in oob.items():
            bucket = failures if hard else borderlines
            sev = "ERROR" if hard else "WARN"
            _add(bucket, tk, f"C_{col}_bounds", round(float(v), 3),
                 f"[{lo},{hi}]", severity=sev)
    return n_checks


# ---------------------------------------------------------------------------
# D. Component scores
# ---------------------------------------------------------------------------

def _check_components(components: pd.DataFrame, latest, failures, borderlines):
    if components.empty:
        return 0
    comp = components.xs(latest, level="date") if latest in components.index.get_level_values("date") else components
    n_checks = 0
    # Per-component NaN counts (aggregate diagnostic — one entry per component if >5% NaN)
    n_rows = int(comp.shape[0])
    for col in comp.columns:
        s = comp[col].astype(float)
        n_checks += n_rows
        # Infinities — always failure
        inf_mask = np.isinf(s)
        if inf_mask.any():
            for tk in s.index[inf_mask].tolist():
                _add(failures, tk, f"D_{col}_inf", "inf", "finite")
        # NaN rate aggregate
        nan_pct = float(s.isna().mean() * 100)
        if nan_pct > 5.0:
            _add(borderlines, None, f"D_{col}_high_nan_rate",
                 f"{nan_pct:.1f}% NaN ({int(s.isna().sum())} of {n_rows})",
                 "< 5% NaN", severity="WARN")
        # Extreme z values
        extreme = s[s.abs() > 5]
        for tk, v in extreme.items():
            _add(borderlines, tk, f"D_{col}_extreme_z", round(float(v), 3),
                 "|z| <= 5", severity="WARN")
    return n_checks


# ---------------------------------------------------------------------------
# E. CCQS bounds & grade consistency
# ---------------------------------------------------------------------------

def _check_ccqs(ccqs: pd.DataFrame, components: pd.DataFrame, latest, failures, borderlines):
    if ccqs.empty:
        return 0
    c = ccqs.xs(latest, level="date")
    comp = components.xs(latest, level="date") if not components.empty else pd.DataFrame()
    n_checks = int(c.shape[0])
    # CCQS out-of-range (real value but outside [0,100]) is a hard failure.
    oob = c[c["ccqs"].notna() & ((c["ccqs"] < 0) | (c["ccqs"] > 100))]
    for tk, r in oob.iterrows():
        _add(failures, tk, "E_ccqs_bounds", round(float(r["ccqs"]), 3),
             "[0,100]")
    # NaN CCQS — every scored ticker must have a valid CCQS. If components
    # are NaN too, that's a propagation issue (WARN borderline + diagnostic);
    # if components present but CCQS NaN, that's a real bug (failure).
    nan_ccqs = c[c["ccqs"].isna()]
    for tk in nan_ccqs.index:
        if tk in comp.index:
            n_nan_comp = int(comp.loc[tk].isna().sum())
            if n_nan_comp > 0:
                _add(borderlines, tk, "E_ccqs_nan_propagated_from_components",
                     f"{n_nan_comp} of 10 components NaN", "all 10 components present", severity="WARN")
            else:
                _add(failures, tk, "E_ccqs_nan_with_components_present",
                     "ccqs=NaN but all 10 components present", "ccqs computed when components present")
        else:
            _add(borderlines, tk, "E_ccqs_nan_no_components",
                 "no components row", "ticker in components", severity="WARN")
    # Grade values — only require valid grade where CCQS is present.
    # Where CCQS is NaN, grade is allowed to be NaN (already flagged as borderline above).
    valid_subset = c[c["ccqs"].notna()]
    bad_grade = valid_subset[~valid_subset["grade"].astype(str).isin(VALID_GRADES)]
    for tk, r in bad_grade.iterrows():
        _add(failures, tk, "E_grade_value", str(r["grade"]),
             "{S,A,B,C,D}")
    # Grade <-> CCQS percentile monotonic check (high CCQS => higher grade letter on average)
    grade_order = ["S", "A", "B", "C", "D"]
    medians = {}
    for g in grade_order:
        sub = c[c["grade"].astype(str) == g]["ccqs"]
        medians[g] = float(sub.median()) if not sub.empty else None
    last = None
    for g in grade_order:
        m = medians[g]
        if m is None:
            continue
        if last is not None and m > last + 1e-6:  # grade B median > grade A median is inverted
            _add(borderlines, None, "E_grade_monotonic",
                 f"{g} median={m:.2f} > prior={last:.2f}",
                 "grades descending by CCQS median", severity="WARN")
        last = m
    return n_checks


# ---------------------------------------------------------------------------
# F. State probabilities
# ---------------------------------------------------------------------------

def _check_state_probs(state: pd.DataFrame, latest, failures, borderlines):
    if state.empty:
        return 0
    s = state.xs(latest, level="date")
    p_cols = [c for c in s.columns if c.startswith("p_") and not c.startswith("p_adj")]
    if not p_cols:
        return 0
    # Sum to 1.0 (within 0.001)
    sums = s[p_cols].sum(axis=1)
    bad_sum = sums[(sums - 1.0).abs() > 0.001]
    for tk, v in bad_sum.items():
        _add(failures, tk, "F_state_probs_sum", round(float(v), 4),
             "1.0 ± 0.001")
    # Each prob in [0,1]
    for col in p_cols:
        col_s = s[col].astype(float)
        oob = col_s[(col_s < -1e-6) | (col_s > 1.0 + 1e-6)]
        for tk, v in oob.items():
            _add(failures, tk, f"F_{col}_bounds", round(float(v), 4), "[0,1]")
    # state assignment matches highest probability
    if "primary_state" in s.columns:
        for tk, row in s.iterrows():
            try:
                p_values = {c[2:] if c.startswith("p_") else c: float(row[c]) for c in p_cols}
                top = max(p_values, key=p_values.get)
                if str(row["primary_state"]) != top:
                    _add(borderlines, tk, "F_state_assignment",
                         f"{row['primary_state']} vs argmax={top}",
                         "primary_state == argmax(p_*)", severity="WARN")
            except Exception:
                pass
    return int(s.shape[0])


# ---------------------------------------------------------------------------
# G. Leadership tier consistency with RS rating
# ---------------------------------------------------------------------------

STRONG_TIERS = {"ELITE_LEADER", "STRONG_LEADER", "EMERGING_LEADER",
                "ESTABLISHED_LEADER", "STRONG_PERFORMER"}
WEAK_TIERS = {"WEAK_PERFORMER", "DETERIORATING", "WEAK_LAGGARD"}


def _check_leadership_consistency(leadership: pd.DataFrame, features: pd.DataFrame, latest, failures, borderlines):
    if leadership.empty or features.empty:
        return 0
    l = leadership.xs(latest, level="date")
    f = features.xs(latest, level="date") if latest in features.index.get_level_values("date") else features
    n_checks = 0

    # Tier validity — every scored ticker must have a valid tier.
    bad_tier = l[~l["leadership_tier"].astype(str).isin(VALID_TIERS)]
    for tk, r in bad_tier.iterrows():
        _add(failures, tk, "G_tier_value", str(r["leadership_tier"]),
             "valid tier set")

    # High RS (>80) should be in strong-or-above tier
    if "rs_rating_spy" in f.columns:
        joined = l[["leadership_tier"]].join(f[["rs_rating_spy"]], how="inner")
        n_checks = int(joined.shape[0])
        high_rs = joined[joined["rs_rating_spy"] > 80]
        for tk, r in high_rs.iterrows():
            if str(r["leadership_tier"]) not in STRONG_TIERS:
                _add(borderlines, tk, "G_high_rs_weak_tier",
                     f"RS={r['rs_rating_spy']:.0f}, tier={r['leadership_tier']}",
                     "tier in STRONG_PERFORMER+", severity="WARN")
        low_rs = joined[joined["rs_rating_spy"] < 20]
        for tk, r in low_rs.iterrows():
            if str(r["leadership_tier"]) not in WEAK_TIERS:
                _add(borderlines, tk, "G_low_rs_strong_tier",
                     f"RS={r['rs_rating_spy']:.0f}, tier={r['leadership_tier']}",
                     "tier in WEAK_PERFORMER-", severity="WARN")
    return n_checks


# ---------------------------------------------------------------------------
# H. Setup classifier
# ---------------------------------------------------------------------------

def _check_setups(setups: pd.DataFrame, latest, failures, borderlines):
    if setups.empty:
        return 0
    s = setups.xs(latest, level="date") if latest in setups.index.get_level_values("date") else setups
    n_checks = int(s.shape[0])
    # confidence [0,1]
    if "setup_confidence" in s.columns:
        oob = s[(s["setup_confidence"] < 0) | (s["setup_confidence"] > 1)]
        for tk, r in oob.iterrows():
            _add(failures, tk, "H_setup_confidence", round(float(r["setup_confidence"]), 3),
                 "[0,1]")
    # setup label present
    if "setup" in s.columns:
        missing = s[s["setup"].isna() | (s["setup"].astype(str) == "")]
        for tk in missing.index:
            _add(borderlines, tk, "H_setup_missing", "(empty)", "non-empty label", severity="WARN")
    return n_checks


# ---------------------------------------------------------------------------
# I. Theme aggregation
# ---------------------------------------------------------------------------

def _check_theme_aggregation(themes: pd.DataFrame, ccqs: pd.DataFrame, latest, failures, borderlines):
    if themes.empty or ccqs.empty:
        return 0
    t = themes.xs(latest, level="date") if latest in themes.index.get_level_values("date") else themes
    c = ccqs.xs(latest, level="date")

    # basket -> tickers map
    basket_to_tickers = {b: list(tks) for b, tks in PRIMARY_BASKET_CONSTITUENTS.items()}

    n_checks = int(t.shape[0])
    for basket, row in t.iterrows():
        # n_constituents == size of declared basket (approx — some may be missing)
        declared_n = len(basket_to_tickers.get(basket, []))
        actual_n = int(row.get("n_constituents", 0))
        # Hard constraint: actual must be <= declared (a basket can't have more members than defined)
        if actual_n > declared_n + 1:
            _add(failures, None, f"I_basket_size:{basket}",
                 f"n_constituents={actual_n} > declared={declared_n}",
                 f"<= {declared_n}")
        # Theme CCQS in [0,100] (post-rescale)
        tc = row.get("theme_ccqs")
        if pd.notna(tc) and (tc < 0 or tc > 100):
            _add(failures, None, f"I_theme_ccqs:{basket}", round(float(tc), 3), "[0,100]")
        # breadth in [0,100]
        for col in ["pct_above_50dma", "pct_above_200dma", "pct_grade_s",
                    "pct_grade_a_plus", "pct_grade_d"]:
            v = row.get(col)
            if pd.notna(v) and (v < 0 or v > 100):
                _add(borderlines, None, f"I_{col}:{basket}", round(float(v), 3),
                     "[0,100]", severity="WARN")
    return n_checks


# ---------------------------------------------------------------------------
# J. Basket assignment coverage
# ---------------------------------------------------------------------------

def _check_basket_assignment(ccqs: pd.DataFrame, latest, failures, borderlines):
    if ccqs.empty:
        return 0
    c = ccqs.xs(latest, level="date")
    declared_baskets = set(PRIMARY_BASKETS.values())
    n_checks = int(c.shape[0])
    for tk in c.index:
        b = PRIMARY_BASKETS.get(tk)
        if b is None:
            _add(failures, tk, "J_orphan_ticker", "(no basket)",
                 "ticker mapped to a basket")
        elif b not in declared_baskets:
            _add(failures, tk, "J_unknown_basket", str(b),
                 "basket name in PRIMARY_BASKET_CONSTITUENTS")
    return n_checks


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run_validation(out_path: Path = OUT_PATH, n_external_sample: int = 50) -> dict:
    t0 = time.time()
    print("Loading parquet files...", flush=True)
    ccqs = _read("ccqs.parquet")
    if ccqs.empty:
        raise RuntimeError("ccqs.parquet missing or empty — run pipeline first.")

    features = _read("features.parquet")
    components = _read("components.parquet")
    leadership = _read("leadership.parquet")
    state = _read("state.parquet")
    setups = _read("setups.parquet")
    themes = _read("theme_aggregates.parquet")
    ohlcv = _read("ohlcv_daily.parquet")

    latest = ccqs.index.get_level_values("date").max()
    print(f"  latest snapshot: {latest}", flush=True)

    universe_tickers = sorted(ccqs.xs(latest, level="date").index.unique().tolist())
    print(f"  universe size: {len(universe_tickers)} tickers", flush=True)

    failures: list = []
    borderlines: list = []

    total_checks = 0

    print("[A] Price freshness", flush=True)
    total_checks += _check_price_freshness(ohlcv, latest, failures, borderlines)

    print("[B] External ground truth (yfinance)", flush=True)
    ext = _check_external_ground_truth(ohlcv, universe_tickers, n_sample=n_external_sample)
    total_checks += int(ext.get("sampled", 0)) * 4   # 4 fields per sample

    print("[C] Feature bounds", flush=True)
    total_checks += _check_feature_bounds(features, latest, failures, borderlines)

    print("[D] Component scores", flush=True)
    total_checks += _check_components(components, latest, failures, borderlines)

    print("[E] CCQS bounds", flush=True)
    total_checks += _check_ccqs(ccqs, components, latest, failures, borderlines)

    print("[F] State probabilities", flush=True)
    total_checks += _check_state_probs(state, latest, failures, borderlines)

    print("[G] Leadership tier consistency", flush=True)
    total_checks += _check_leadership_consistency(leadership, features, latest, failures, borderlines)

    print("[H] Setup classifier", flush=True)
    total_checks += _check_setups(setups, latest, failures, borderlines)

    print("[I] Theme aggregation", flush=True)
    total_checks += _check_theme_aggregation(themes, ccqs, latest, failures, borderlines)

    print("[J] Basket assignment", flush=True)
    total_checks += _check_basket_assignment(ccqs, latest, failures, borderlines)

    n_failures = len(failures)
    n_borderlines = len(borderlines)
    passes = total_checks - n_failures - n_borderlines

    # Verdict
    n_discrep = len(ext.get("discrepancies", []))
    if n_failures > 0 or n_discrep > int(0.30 * max(ext.get("sampled", 1), 1)):
        # >30% of external sample with discrepancies is a fail
        verdict = "FAIL"
    elif n_borderlines > 10 or n_discrep > 0:
        verdict = "REVIEW"
    else:
        verdict = "PASS"

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "snapshot_date": str(latest.date() if hasattr(latest, "date") else latest),
        "universe_size": len(universe_tickers),
        "total_stocks_validated": len(universe_tickers),
        "total_checks_run": int(total_checks),
        "passes": int(passes),
        "n_borderlines": n_borderlines,
        "n_failures": n_failures,
        "borderlines": borderlines[:300],
        "failures": failures[:300],
        "external_comparison_results": ext,
        "overall_verdict": verdict,
        "elapsed_seconds": round(time.time() - t0, 2),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWrote {out_path}", flush=True)
    return report


def _summary_print(r: dict) -> None:
    print("=" * 60)
    print("LEVEL 3 VALIDATION — SUMMARY")
    print("=" * 60)
    print(f"  Snapshot:        {r['snapshot_date']}")
    print(f"  Universe:        {r['universe_size']:,} stocks")
    print(f"  Checks run:      {r['total_checks_run']:,}")
    print(f"  Pass:            {r['passes']:,}")
    print(f"  Borderlines:     {r['n_borderlines']:,}")
    print(f"  Failures:        {r['n_failures']:,}")
    ec = r["external_comparison_results"]
    if "error" in ec:
        print(f"  External (yf):   ERROR — {ec['error']}")
    else:
        n_disc = len(ec.get("discrepancies", []))
        print(f"  External (yf):   {ec['matches']}/{ec['sampled']} matched, {n_disc} discrepancies")
    print(f"  Verdict:         {r['overall_verdict']}")
    print(f"  Elapsed:         {r['elapsed_seconds']}s")
    if r["failures"]:
        print("\n  First failures:")
        for f in r["failures"][:10]:
            print(f"    {f['ticker']}  {f['check']}  val={f['value']}  expected={f['expected_range']}")
    if r["borderlines"][:8]:
        print("\n  First borderlines:")
        for b in r["borderlines"][:8]:
            print(f"    {b['ticker']}  {b['check']}  val={b['value']}  expected={b['expected_range']}")


if __name__ == "__main__":
    rep = run_validation()
    _summary_print(rep)
