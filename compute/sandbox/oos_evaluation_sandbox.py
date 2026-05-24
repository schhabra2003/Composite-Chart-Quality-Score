"""CCQS V1 Sandbox — OOS IC evaluation on expanded 970-stock universe.

Mirrors compute.validation.oos_evaluation but reads from data/cache/sandbox/
and writes to data/cache/sandbox/. Identical methodology (walk-forward 252/21/21,
6 horizons, Spearman cross-sectional IC). Evaluates CCQS composite only —
Phase X.3 baseline is the comparison anchor.

Outputs:
    data/cache/sandbox/oos_ic_diagnostics.parquet
    data/cache/sandbox/oos_ic_summary.json

Run:
    python -m compute.sandbox.oos_evaluation_sandbox
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
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from compute.sandbox.loader_sandbox import (
    CCQS_PATH,
    SANDBOX_CACHE_DIR,
    OHLCV_PATH,
)

OOS_DIAG_PATH = SANDBOX_CACHE_DIR / "oos_ic_diagnostics.parquet"
OOS_SUMMARY_PATH = SANDBOX_CACHE_DIR / "oos_ic_summary.json"

HORIZONS = [1, 5, 20, 60, 126, 252]
TRAIN_WINDOW = 252
TEST_WINDOW = 21
STEP = 21
MIN_WINDOW_DATES = 5


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

    def _rho(g: pd.DataFrame) -> float:
        if len(g) < 20:
            return np.nan
        rho, _ = spearmanr(g["c"], g["f"])
        return float(rho) if rho == rho else np.nan

    return df.groupby(level="date", sort=True).apply(_rho)


def _rolling_windows(dates: list[pd.Timestamp]) -> list[dict]:
    n = len(dates)
    windows: list[dict] = []
    k = 0
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


def _aggregate_windows(ic_series: pd.Series, windows: list[dict]) -> list[dict]:
    rows: list[dict] = []
    ic = ic_series.dropna()
    if ic.empty:
        return rows
    for w in windows:
        train_mask = (ic.index >= w["train_start"]) & (ic.index <= w["train_end"])
        test_mask = (ic.index >= w["test_start"]) & (ic.index <= w["test_end"])
        train_slice = ic[train_mask]
        test_slice = ic[test_mask]
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


def compute_sandbox_oos() -> tuple[pd.DataFrame, dict]:
    if not CCQS_PATH.exists():
        raise RuntimeError(f"Sandbox CCQS not found: {CCQS_PATH}")
    if not OHLCV_PATH.exists():
        raise RuntimeError(f"Sandbox OHLCV not found: {OHLCV_PATH}")

    ccqs = pd.read_parquet(CCQS_PATH)
    ohlcv = pd.read_parquet(OHLCV_PATH)
    if "ticker" not in ohlcv.columns:
        ohlcv = ohlcv.reset_index()
    logger.info(f"Loaded sandbox ccqs {ccqs.shape}, ohlcv {ohlcv.shape}")

    fwd_by_h: dict[int, pd.Series] = {}
    for h in HORIZONS:
        fwd_by_h[h] = _forward_returns(ohlcv, h)
        logger.info(f"  forward returns h={h}d: {fwd_by_h[h].notna().sum():,} non-NaN")

    all_dates = sorted(ccqs.index.get_level_values("date").unique())
    windows = _rolling_windows(all_dates)
    logger.info(f"Built {len(windows)} rolling windows  (train={TRAIN_WINDOW}, test={TEST_WINDOW}, step={STEP})")

    rows_all: list[dict] = []
    score = ccqs["ccqs"].astype(float)
    for h in HORIZONS:
        t0 = time.time()
        ic = _spearman_per_date(score, fwd_by_h[h])
        rows = _aggregate_windows(ic, windows)
        for r in rows:
            r["horizon"] = h
            r["score_name"] = "CCQS"
            r["score_type"] = "composite"
        rows_all.extend(rows)
        logger.info(f"  h={h}d: {len(rows)} windows  ({time.time()-t0:.1f}s)")

    diag = pd.DataFrame(rows_all)

    def _agg(g: pd.DataFrame) -> pd.Series:
        oos = g["oos_ic"].dropna()
        is_ = g["is_ic"].dropna()
        n = len(oos)
        oos_mean = float(oos.mean()) if n else np.nan
        oos_std = float(oos.std(ddof=1)) if n > 1 else np.nan
        se = (oos_std / np.sqrt(n)) if (n > 1 and oos_std) else np.nan
        t_stat = oos_mean / se if (se and se > 0) else np.nan
        # two-sided p-value from a normal approximation (large n, walk-forward)
        from scipy.stats import t as t_dist
        p_val = float(2.0 * (1.0 - t_dist.cdf(abs(t_stat), df=max(n - 1, 1)))) if (t_stat == t_stat) else np.nan
        return pd.Series({
            "n_windows": int(n),
            "oos_ic_mean": oos_mean,
            "oos_ic_std": oos_std,
            "oos_ic_se": float(se) if se == se else np.nan,
            "oos_ic_t_stat": float(t_stat) if t_stat == t_stat else np.nan,
            "oos_p_value": p_val,
            "oos_hit_rate": float((oos > 0).mean()) if n else np.nan,
            "is_ic_mean": float(is_.mean()) if len(is_) else np.nan,
            "is_minus_oos": (float(is_.mean()) - oos_mean) if (n and len(is_)) else np.nan,
        })

    summary = diag.groupby(["score_type", "score_name", "horizon"]).apply(_agg).reset_index()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe": "sandbox_970",
        "horizons": HORIZONS,
        "train_window": TRAIN_WINDOW,
        "test_window": TEST_WINDOW,
        "step": STEP,
        "n_windows": len(windows),
        "rows": summary.to_dict(orient="records"),
    }
    return diag, payload


def main() -> int:
    t0 = time.time()
    diag, summary = compute_sandbox_oos()
    diag.to_parquet(OOS_DIAG_PATH, compression="snappy")
    OOS_SUMMARY_PATH.write_text(json.dumps(summary, indent=2, default=str))
    elapsed = time.time() - t0
    logger.info(f"Wrote {OOS_DIAG_PATH} ({len(diag):,} rows)")
    logger.info(f"Wrote {OOS_SUMMARY_PATH}")

    print()
    print("=" * 72)
    print("SANDBOX OUT-OF-SAMPLE IC EVALUATION (CCQS composite)")
    print("=" * 72)
    print(f"Universe: 970 stocks  ·  Windows: {summary['n_windows']}  ·  Elapsed: {elapsed:.1f}s")
    print()
    print(f"  {'horizon':>8} {'OOS IC':>10} {'t-stat':>8} {'p-val':>8} {'hit-rate':>10} {'SE':>10} {'n_win':>6}")
    for r in sorted(summary["rows"], key=lambda x: x["horizon"]):
        print(
            f"  {r['horizon']:>8} {r['oos_ic_mean']:>+10.4f} "
            f"{(r['oos_ic_t_stat'] or 0):>8.2f} "
            f"{(r['oos_p_value'] or 1.0):>8.4f} "
            f"{(r['oos_hit_rate'] or 0):>10.4f} "
            f"{(r['oos_ic_se'] or 0):>10.4f} "
            f"{r['n_windows']:>6}"
        )
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
