"""SP100 Coverage Gap Analysis — production + 12 SP100-missing only.

Re-runs the full sandbox pipeline on a smaller universe (870 = 858 prod + 12
SP100-missing) and computes OOS IC for comparison against the production-extended
baseline and the full sandbox (970-stock) result.

Outputs:
    data/cache/sp100/  — all pipeline parquets + oos_ic_summary.json

Run:
    python -m compute.sandbox.sp100_analysis
"""
from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from scipy.stats import spearmanr, t as t_dist

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import data.universe as universe_mod
import compute.features as features_mod
from compute.features import compute_features
from compute.standardization import standardize_features
from compute.components import compute_components
from compute.state import classify_states
from compute.leadership import classify_leadership
from compute.ccqs import compute_ccqs
from compute.setup_classifier import classify_setups
from compute.aggregation import aggregate_themes
from data.universe import all_unique_tickers
from compute.sandbox.loader_sandbox import (
    OHLCV_PATH as SB_OHLCV_PATH,
    QUALITY_REPORT_PATH as SB_QUALITY_PATH,
)

# 12 SP100 names absent from production (canonical OEX list, 2024-25)
SP100_MISSING = ['AAPL', 'BNY', 'BRK-B', 'CHTR', 'GOOG', 'HON', 'MMM',
                 'SBUX', 'T', 'TGT', 'TMUS', 'VZ']

SP100_CACHE_DIR = ROOT / "data" / "cache" / "sp100"
SP100_CACHE_DIR.mkdir(parents=True, exist_ok=True)

HORIZONS = [1, 5, 20, 60, 126, 252]
TRAIN_WINDOW = 252
TEST_WINDOW = 21
STEP = 21
MIN_WINDOW_DATES = 5


def _sp100_passing_tickers() -> list[str]:
    """858 production-passing (per production cache) + 12 SP100-missing (all PASS in sandbox)."""
    prod_qpath = Path(ROOT) / "data" / "cache" / "data_quality_report.json"
    prod_qr = json.loads(prod_qpath.read_text())
    prod_pass = {t for t, r in prod_qr.get("results", {}).items()
                 if r.get("status") in ("PASS", "WARNING")}
    sandbox_qr = json.loads(SB_QUALITY_PATH.read_text())
    sp100_pass = {t for t in SP100_MISSING
                  if sandbox_qr.get("results", {}).get(t, {}).get("status") in ("PASS", "WARNING")}
    return sorted(prod_pass | sp100_pass)


@contextmanager
def _sp100_universe_gates():
    prod = set(all_unique_tickers())
    sp100_uni = sorted(prod | set(SP100_MISSING))

    orig_all = features_mod.all_unique_tickers
    orig_load = features_mod._load_passing_tickers
    features_mod.all_unique_tickers = lambda: sp100_uni
    features_mod._load_passing_tickers = _sp100_passing_tickers
    try:
        yield sp100_uni
    finally:
        features_mod.all_unique_tickers = orig_all
        features_mod._load_passing_tickers = orig_load


# ---------------------------------------------------------------------------
# OOS IC helpers (copied from oos_evaluation_sandbox)
# ---------------------------------------------------------------------------

def _forward_returns(ohlcv: pd.DataFrame, horizon: int) -> pd.Series:
    df = ohlcv[["ticker", "date", "adj_close"]].sort_values(["ticker", "date"]).copy()
    df["adj_close"] = df["adj_close"].astype(float)
    df["adj_fwd"] = df.groupby("ticker", sort=False)["adj_close"].shift(-horizon)
    df["fwd_ret"] = df["adj_fwd"] / df["adj_close"] - 1.0
    return df.set_index(["ticker", "date"])["fwd_ret"]


def _spearman_per_date(s_score: pd.Series, s_fwd: pd.Series) -> pd.Series:
    df = pd.concat([s_score.rename("c"), s_fwd.rename("f")], axis=1).dropna()
    if df.empty:
        return pd.Series(dtype=float)

    def _rho(g):
        if len(g) < 20:
            return np.nan
        r, _ = spearmanr(g["c"], g["f"])
        return float(r) if r == r else np.nan

    return df.groupby(level="date", sort=True).apply(_rho)


def _rolling_windows(dates):
    n = len(dates)
    windows, k = [], 0
    while True:
        train_lo = k * STEP
        train_hi = train_lo + TRAIN_WINDOW
        test_lo = train_hi
        test_hi = test_lo + TEST_WINDOW
        if test_hi > n:
            break
        windows.append({
            "window_idx": k,
            "train_start": dates[train_lo],
            "train_end": dates[train_hi - 1],
            "test_start": dates[test_lo],
            "test_end": dates[test_hi - 1],
        })
        k += 1
    return windows


def _aggregate_windows(ic_series, windows):
    rows = []
    ic = ic_series.dropna()
    if ic.empty:
        return rows
    for w in windows:
        tm = (ic.index >= w["train_start"]) & (ic.index <= w["train_end"])
        te = (ic.index >= w["test_start"]) & (ic.index <= w["test_end"])
        train_slice = ic[tm]
        test_slice = ic[te]
        if len(train_slice) < MIN_WINDOW_DATES or len(test_slice) < MIN_WINDOW_DATES:
            continue
        rows.append({
            **w,
            "is_ic": float(train_slice.mean()),
            "oos_ic": float(test_slice.mean()),
            "n_train_dates": int(len(train_slice)),
            "n_test_dates": int(len(test_slice)),
        })
    return rows


def run() -> dict:
    if not SB_OHLCV_PATH.exists():
        raise RuntimeError(f"Sandbox OHLCV missing: {SB_OHLCV_PATH}. Run fetch_sp500 first.")

    t0 = time.time()
    ohlcv = pd.read_parquet(SB_OHLCV_PATH)
    # Subset to (production ∪ SP100_MISSING ∪ BENCHMARKS) before pipeline
    from data.universe import BENCHMARKS
    prod = set(all_unique_tickers())
    sp100_uni = prod | set(SP100_MISSING) | set(BENCHMARKS)
    ohlcv_sp100 = ohlcv[ohlcv["ticker"].isin(sp100_uni)].reset_index(drop=True)
    logger.info(f"SP100 OHLCV slice: {ohlcv_sp100.shape}, tickers={ohlcv_sp100['ticker'].nunique()}")

    with _sp100_universe_gates() as uni:
        logger.info(f"SP100 universe size: {len(uni)} (target=870)")
        ts = time.time()
        features = compute_features(ohlcv_sp100)
        features.to_parquet(SP100_CACHE_DIR / "features.parquet", compression="snappy")
        logger.info(f"  features: {features.shape}  ({time.time()-ts:.1f}s)")

        ts = time.time()
        zsc = standardize_features(features)
        zsc.to_parquet(SP100_CACHE_DIR / "z_scores.parquet", compression="snappy")
        logger.info(f"  z_scores: {zsc.shape}  ({time.time()-ts:.1f}s)")

        ts = time.time()
        components = compute_components(features, zsc)
        components.to_parquet(SP100_CACHE_DIR / "components.parquet", compression="snappy")
        logger.info(f"  components: {components.shape}  ({time.time()-ts:.1f}s)")

        ts = time.time()
        state = classify_states(features)
        state.to_parquet(SP100_CACHE_DIR / "state.parquet", compression="snappy")
        logger.info(f"  state: {state.shape}  ({time.time()-ts:.1f}s)")

        ts = time.time()
        leadership = classify_leadership(features, components)
        leadership.to_parquet(SP100_CACHE_DIR / "leadership.parquet", compression="snappy")
        logger.info(f"  leadership: {leadership.shape}  ({time.time()-ts:.1f}s)")

        ts = time.time()
        ccqs = compute_ccqs(components, state)
        ccqs.to_parquet(SP100_CACHE_DIR / "ccqs.parquet", compression="snappy")
        logger.info(f"  ccqs: {ccqs.shape}  ({time.time()-ts:.1f}s)")

    # ---- OOS IC ----------------------------------------------------------
    logger.info("Computing OOS IC across 6 horizons...")
    fwd_by_h = {h: _forward_returns(ohlcv_sp100, h) for h in HORIZONS}
    all_dates = sorted(ccqs.index.get_level_values("date").unique())
    windows = _rolling_windows(all_dates)
    logger.info(f"  built {len(windows)} rolling windows")

    rows_all = []
    score = ccqs["ccqs"].astype(float)
    for h in HORIZONS:
        ic = _spearman_per_date(score, fwd_by_h[h])
        rows = _aggregate_windows(ic, windows)
        for r in rows:
            r["horizon"] = h
        rows_all.extend(rows)
    diag = pd.DataFrame(rows_all)
    diag.to_parquet(SP100_CACHE_DIR / "oos_ic_diagnostics.parquet", compression="snappy")

    summary_rows = []
    for h in HORIZONS:
        sub = diag[diag["horizon"] == h]
        oos = sub["oos_ic"].dropna()
        is_ = sub["is_ic"].dropna()
        n = len(oos)
        oos_mean = float(oos.mean()) if n else np.nan
        oos_std = float(oos.std(ddof=1)) if n > 1 else np.nan
        se = (oos_std / np.sqrt(n)) if (n > 1 and oos_std) else np.nan
        tstat = oos_mean / se if (se and se > 0) else np.nan
        pval = float(2.0 * (1.0 - t_dist.cdf(abs(tstat), df=max(n - 1, 1)))) if (tstat == tstat) else np.nan
        summary_rows.append({
            "horizon": h,
            "n_windows": int(n),
            "oos_ic_mean": oos_mean,
            "oos_ic_std": oos_std,
            "oos_ic_se": float(se) if se == se else np.nan,
            "oos_ic_t_stat": float(tstat) if tstat == tstat else np.nan,
            "oos_p_value": pval,
            "oos_hit_rate": float((oos > 0).mean()) if n else np.nan,
            "is_ic_mean": float(is_.mean()) if len(is_) else np.nan,
        })

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe": "production_plus_sp100_missing",
        "n_tickers_declared": 870,
        "sp100_missing_added": SP100_MISSING,
        "horizons": HORIZONS,
        "train_window": TRAIN_WINDOW,
        "test_window": TEST_WINDOW,
        "step": STEP,
        "n_windows_built": len(windows),
        "rows": summary_rows,
    }
    (SP100_CACHE_DIR / "oos_ic_summary.json").write_text(json.dumps(payload, indent=2, default=str))

    elapsed = time.time() - t0
    print()
    print("=" * 72)
    print(f"SP100 ANALYSIS — pipeline + OOS IC  ({elapsed:.1f}s total)")
    print("=" * 72)
    print(f"Universe: production + {len(SP100_MISSING)} SP100-missing names")
    print(f"CCQS rows: {len(ccqs):,}  tickers: {ccqs.index.get_level_values('ticker').nunique()}")
    print()
    print(f"  {'h':>4} {'OOS IC':>10} {'t':>6} {'p':>7} {'hit':>7} {'SE':>9} {'n_win':>6}")
    for r in summary_rows:
        print(f"  {r['horizon']:>4} {r['oos_ic_mean']:>+10.4f} {(r['oos_ic_t_stat'] or 0):>6.2f} "
              f"{(r['oos_p_value'] or 1.0):>7.4f} {(r['oos_hit_rate'] or 0):>7.4f} "
              f"{(r['oos_ic_se'] or 0):>9.4f} {r['n_windows']:>6}")
    print("=" * 72)
    return payload


if __name__ == "__main__":
    run()
