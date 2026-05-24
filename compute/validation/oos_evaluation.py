"""
CCQS V1 — Out-of-Sample IC Evaluation Framework (Phase X.1)

Replaces single-window in-sample IC measurement with rigorous rolling
walk-forward analysis. For each score (CCQS composite, each component,
each feature) and each forward-return horizon in [1, 5, 20, 60, 126, 252]
days, this module computes:

    Window definition
    -----------------
    Trading dates D = [d_0, d_1, ..., d_{N-1}], sorted ascending.

    For window k = 0, 1, 2, ...:
        train_dates = D[k * step : k * step + 252]
        test_dates  = D[k * step + 252 : k * step + 252 + 21]
        step = 21

    IC_window_train = mean of cross-sectional Spearman(score_d, fwd_h_d)
                      across dates in train_dates (drop NaN per-date ICs).
    IC_window_test  = same, restricted to test_dates.

    Window k is dropped if either side has < 5 valid date-ICs.

The composite score is a fixed formula (not fitted on training data), so
"in-sample" vs "out-of-sample" here measures **temporal stability** of the
predictive signal rather than parameter-fit overfitting. A large positive
gap (IS_IC >> OOS_IC) over multiple windows means the score's edge is
front-loaded into one historical regime and erodes out of sample.

Outputs
-------
    data/cache/oos_ic_diagnostics.parquet
        Long DataFrame, one row per (score, horizon, window).
        Columns: score_name, score_type, horizon, window_idx,
                 train_start, train_end, test_start, test_end,
                 is_ic, oos_ic, n_train_dates, n_test_dates

    data/cache/oos_ic_summary.json
        Per-(score, horizon) aggregate: mean OOS IC, mean IS IC,
        OOS t-stat, OOS hit-rate, IS-OOS gap, window count.

Run:
    python -m compute.validation.oos_evaluation
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

from compute.loader import CACHE_DIR, LOG_DIR

CCQS_PATH = CACHE_DIR / "ccqs.parquet"
COMPONENTS_PATH = CACHE_DIR / "components.parquet"
FEATURES_PATH = CACHE_DIR / "features.parquet"
OHLCV_PATH = CACHE_DIR / "ohlcv_daily.parquet"

OOS_DIAG_PATH = CACHE_DIR / "oos_ic_diagnostics.parquet"
OOS_SUMMARY_PATH = CACHE_DIR / "oos_ic_summary.json"

HORIZONS = [1, 5, 20, 60, 126, 252]
TRAIN_WINDOW = 252
TEST_WINDOW = 21
STEP = 21
MIN_WINDOW_DATES = 5  # drop a window if fewer valid date-ICs than this

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")
logger.add(LOG_DIR / "ccqs.log", level="DEBUG", rotation="10 MB", retention="30 days")


# ---------------------------------------------------------------------------
# Cross-sectional IC helpers (mirror compute.reliability.ic_tracker)
# ---------------------------------------------------------------------------

def _forward_returns(ohlcv: pd.DataFrame, horizon: int) -> pd.Series:
    """Per (ticker, date) forward total return over `horizon` trading days."""
    df = ohlcv[["ticker", "date", "adj_close"]].sort_values(["ticker", "date"]).copy()
    df["adj_close"] = df["adj_close"].astype(float)
    df["adj_fwd"] = df.groupby("ticker", sort=False)["adj_close"].shift(-horizon)
    df["fwd_ret"] = df["adj_fwd"] / df["adj_close"] - 1.0
    out = df.set_index(["ticker", "date"])["fwd_ret"].rename(f"fwd_ret_{horizon}d")
    return out


def _spearman_per_date(s_score: pd.Series, s_fwd: pd.Series) -> pd.Series:
    """Cross-sectional Spearman per date. Returns Series indexed by date."""
    df = pd.concat([s_score.rename("c"), s_fwd.rename("f")], axis=1).dropna()
    if df.empty:
        return pd.Series(dtype=float)

    def _rho(g: pd.DataFrame) -> float:
        if len(g) < 20:
            return np.nan
        rho, _ = spearmanr(g["c"], g["f"])
        return float(rho) if rho == rho else np.nan

    return df.groupby(level="date", sort=True).apply(_rho)


# ---------------------------------------------------------------------------
# Walk-forward window aggregation
# ---------------------------------------------------------------------------

def _rolling_windows(dates: list[pd.Timestamp]) -> list[dict]:
    """Yield (train_start, train_end, test_start, test_end) for each window."""
    n = len(dates)
    windows = []
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
    """For each window, average the date-level IC in train and test slices."""
    rows = []
    if ic_series.empty:
        return rows
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


# ---------------------------------------------------------------------------
# Per-score evaluation
# ---------------------------------------------------------------------------

def evaluate_score(
    score: pd.Series,
    fwd_returns_by_h: dict[int, pd.Series],
    windows: list[dict],
    score_name: str,
    score_type: str,
) -> pd.DataFrame:
    """Evaluate one score across all horizons, returning long DataFrame."""
    pieces: list[pd.DataFrame] = []
    for h, fwd in fwd_returns_by_h.items():
        ic = _spearman_per_date(score, fwd)
        rows = _aggregate_windows(ic, windows)
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df["horizon"] = h
        df["score_name"] = score_name
        df["score_type"] = score_type
        pieces.append(df)
    if not pieces:
        return pd.DataFrame(
            columns=[
                "score_name", "score_type", "horizon", "window_idx",
                "train_start", "train_end", "test_start", "test_end",
                "is_ic", "oos_ic", "n_train_dates", "n_test_dates",
            ]
        )
    return pd.concat(pieces, ignore_index=True)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def compute_oos_diagnostics() -> tuple[pd.DataFrame, dict]:
    """Load all inputs, run OOS eval on CCQS + components + features."""
    if not (CCQS_PATH.exists() and COMPONENTS_PATH.exists() and FEATURES_PATH.exists() and OHLCV_PATH.exists()):
        raise RuntimeError("Missing inputs — run the main pipeline first.")

    ccqs = pd.read_parquet(CCQS_PATH)
    components = pd.read_parquet(COMPONENTS_PATH)
    features = pd.read_parquet(FEATURES_PATH)
    ohlcv = pd.read_parquet(OHLCV_PATH)
    logger.info(
        f"Loaded ccqs {ccqs.shape}, components {components.shape}, "
        f"features {features.shape}, ohlcv {ohlcv.shape}"
    )

    # Forward returns by horizon — compute once.
    fwd_by_h: dict[int, pd.Series] = {}
    for h in HORIZONS:
        fwd_by_h[h] = _forward_returns(ohlcv, h)
        logger.info(f"  forward returns h={h}d: {fwd_by_h[h].notna().sum():,} non-NaN")

    # Trading-date list (use CCQS index as canonical universe-of-dates).
    all_dates = sorted(ccqs.index.get_level_values("date").unique())
    windows = _rolling_windows(all_dates)
    logger.info(
        f"Built {len(windows)} rolling windows  "
        f"(train={TRAIN_WINDOW}, test={TEST_WINDOW}, step={STEP})"
    )

    pieces: list[pd.DataFrame] = []

    # 1. Composite CCQS
    logger.info("Evaluating composite CCQS...")
    t0 = time.time()
    pieces.append(evaluate_score(
        ccqs["ccqs"].astype(float), fwd_by_h, windows, "CCQS", "composite",
    ))
    logger.info(f"  composite done in {time.time() - t0:.1f}s")

    # 2. Each component
    logger.info(f"Evaluating {components.shape[1]} components...")
    t0 = time.time()
    for col in components.columns:
        pieces.append(evaluate_score(
            components[col].astype(float), fwd_by_h, windows, col, "component",
        ))
    logger.info(f"  components done in {time.time() - t0:.1f}s")

    # 3. Each numeric feature (skip categorical / object-typed columns)
    numeric_features = features.select_dtypes(include=[np.number]).columns.tolist()
    logger.info(f"Evaluating {len(numeric_features)} numeric features...")
    t0 = time.time()
    for i, col in enumerate(numeric_features, 1):
        pieces.append(evaluate_score(
            features[col].astype(float), fwd_by_h, windows, col, "feature",
        ))
        if i % 25 == 0:
            logger.info(f"  feature {i}/{len(numeric_features)}  ({time.time() - t0:.0f}s elapsed)")
    logger.info(f"  features done in {time.time() - t0:.1f}s")

    diag = pd.concat(pieces, ignore_index=True)

    # Aggregate summary per (score, horizon).
    def _aggregate(g: pd.DataFrame) -> pd.Series:
        oos = g["oos_ic"].dropna()
        is_ = g["is_ic"].dropna()
        n = len(oos)
        oos_mean = float(oos.mean()) if n else np.nan
        oos_std = float(oos.std(ddof=1)) if n > 1 else np.nan
        t_stat = oos_mean / (oos_std / np.sqrt(n)) if (n > 1 and oos_std and oos_std > 0) else np.nan
        return pd.Series({
            "n_windows": n,
            "oos_ic_mean": oos_mean,
            "oos_ic_std": oos_std,
            "oos_ic_t_stat": t_stat,
            "oos_hit_rate": float((oos > 0).mean()) if n else np.nan,
            "is_ic_mean": float(is_.mean()) if len(is_) else np.nan,
            "is_minus_oos": (float(is_.mean()) - oos_mean) if (n and len(is_)) else np.nan,
        })

    summary = (
        diag.groupby(["score_type", "score_name", "horizon"])
            .apply(_aggregate)
            .reset_index()
    )

    summary_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizons": HORIZONS,
        "train_window": TRAIN_WINDOW,
        "test_window": TEST_WINDOW,
        "step": STEP,
        "n_windows": len(windows),
        "n_scores_evaluated": int(summary["score_name"].nunique()),
        "rows": summary.to_dict(orient="records"),
    }

    return diag, summary_payload


def main() -> int:
    t0 = time.time()
    diag, summary = compute_oos_diagnostics()
    elapsed = time.time() - t0

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    diag.to_parquet(OOS_DIAG_PATH, compression="snappy")
    OOS_SUMMARY_PATH.write_text(json.dumps(summary, indent=2, default=str))
    logger.info(f"Wrote {OOS_DIAG_PATH} ({len(diag):,} rows)")
    logger.info(f"Wrote {OOS_SUMMARY_PATH}")

    print()
    print("=" * 70)
    print("OUT-OF-SAMPLE IC EVALUATION")
    print("=" * 70)
    print(f"Windows:        {summary['n_windows']}")
    print(f"Scores:         {summary['n_scores_evaluated']}")
    print(f"Horizons:       {HORIZONS}")
    print(f"Rows in diag:   {len(diag):,}")
    print(f"Elapsed:        {elapsed:.1f}s")

    # CCQS highlight rows
    ccqs_rows = [r for r in summary["rows"] if r["score_name"] == "CCQS"]
    print()
    print("Composite CCQS — OOS by horizon:")
    print(f"  {'horizon':>8} {'OOS IC':>10} {'t-stat':>8} {'hit-rate':>10} {'IS-OOS':>10}")
    for r in sorted(ccqs_rows, key=lambda x: x["horizon"]):
        print(
            f"  {r['horizon']:>8} {r['oos_ic_mean']:>10.4f} "
            f"{(r['oos_ic_t_stat'] or 0):>8.2f} {(r['oos_hit_rate'] or 0):>10.4f} "
            f"{(r['is_minus_oos'] or 0):>10.4f}"
        )
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
