"""
CCQS V1 — Information Coefficient Tracker (SPEC Section 13, Layer 6)

Spearman rank correlation between today's CCQS and forward 1d / 5d / 20d
returns, computed cross-sectionally on each date over the full history we
have. Reports headline IC plus a rolling 60-day series so we can spot decay.

A healthy long-only quality score typically lands at:
    IC_1d  : 0.02 — 0.06
    IC_5d  : 0.03 — 0.10
    IC_20d : 0.04 — 0.12

These are alpha bands, not noise. Anything > 0.20 is suspicious (look-ahead).
Anything < -0.05 sustained means the score is anti-predictive.

Output: `data/cache/ic_tracker.json`

Run:
    python -m compute.reliability.ic_tracker
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
OHLCV_PATH = CACHE_DIR / "ohlcv_daily.parquet"
OUT_PATH = CACHE_DIR / "ic_tracker.json"

HORIZONS = [1, 5, 20, 60, 126]
ROLLING_WINDOW = 60   # rolling-window length for IC time-series

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")
logger.add(LOG_DIR / "ccqs.log", level="DEBUG", rotation="10 MB", retention="30 days")


def _forward_returns(ohlcv: pd.DataFrame, horizon: int) -> pd.Series:
    """Per (ticker,date) forward total return over `horizon` trading days, using adj_close."""
    df = ohlcv[["ticker", "date", "adj_close"]].sort_values(["ticker", "date"]).copy()
    df["adj_close"] = df["adj_close"].astype(float)
    df["adj_fwd"] = df.groupby("ticker", sort=False)["adj_close"].shift(-horizon)
    df["fwd_ret"] = df["adj_fwd"] / df["adj_close"] - 1.0
    out = df.set_index(["ticker", "date"])["fwd_ret"].rename(f"fwd_ret_{horizon}d")
    return out


def _spearman_per_date(s_ccqs: pd.Series, s_fwd: pd.Series) -> pd.Series:
    """Cross-sectional Spearman by date. Returns a Series indexed by date."""
    df = pd.concat([s_ccqs.rename("c"), s_fwd.rename("f")], axis=1).dropna()
    if df.empty:
        return pd.Series(dtype=float)

    def _rho(g: pd.DataFrame) -> float:
        if len(g) < 20:
            return np.nan
        # spearmanr returns nan if either series is constant.
        rho, _ = spearmanr(g["c"], g["f"])
        return float(rho) if rho == rho else np.nan

    return df.groupby(level="date", sort=True).apply(_rho)


def _ic_for_score(score: pd.Series, ohlcv: pd.DataFrame) -> tuple[dict, dict[str, list[dict]]]:
    """Compute mean / median / t / hit-rate IC plus rolling series for one score."""
    summary: dict = {}
    series: dict[str, list[dict]] = {}
    for h in HORIZONS:
        fwd = _forward_returns(ohlcv, h)
        ic = _spearman_per_date(score, fwd).dropna()
        if ic.empty:
            summary[f"ic_{h}d_mean"] = None
            summary[f"ic_{h}d_median"] = None
            summary[f"ic_{h}d_std"] = None
            summary[f"ic_{h}d_t_stat"] = None
            summary[f"ic_{h}d_n_dates"] = 0
            summary[f"ic_{h}d_hit_rate"] = None
            series[f"rolling_{h}d"] = []
            continue
        mean = float(ic.mean())
        med = float(ic.median())
        std = float(ic.std(ddof=1))
        n = int(len(ic))
        t_stat = mean / (std / np.sqrt(n)) if std > 0 else None
        hit_rate = float((ic > 0).mean())
        summary[f"ic_{h}d_mean"] = round(mean, 4)
        summary[f"ic_{h}d_median"] = round(med, 4)
        summary[f"ic_{h}d_std"] = round(std, 4)
        summary[f"ic_{h}d_t_stat"] = None if t_stat is None else round(t_stat, 3)
        summary[f"ic_{h}d_n_dates"] = n
        summary[f"ic_{h}d_hit_rate"] = round(hit_rate, 4)

        rolling = ic.rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW).mean().dropna()
        series[f"rolling_{h}d"] = [
            {"date": d.strftime("%Y-%m-%d"), "ic": round(float(v), 4)}
            for d, v in rolling.items()
        ]
    return summary, series


def compute_ic(
    ccqs: pd.DataFrame,
    ohlcv: pd.DataFrame,
    extra_scores: dict[str, pd.Series] | None = None,
) -> dict:
    """IC for the main CCQS plus any additional named scores (e.g. short-term signal)."""
    ccqs_summary, ccqs_series = _ic_for_score(ccqs["ccqs"].astype(float), ohlcv)

    extra_summary: dict[str, dict] = {}
    extra_series: dict[str, dict[str, list[dict]]] = {}
    for name, s in (extra_scores or {}).items():
        es, ev = _ic_for_score(s.astype(float), ohlcv)
        extra_summary[name] = es
        extra_series[name] = ev

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizons": HORIZONS,
        "rolling_window": ROLLING_WINDOW,
        "summary": ccqs_summary,
        "series": ccqs_series,
        "extra_scores_summary": extra_summary,
        "extra_scores_series": extra_series,
    }


def main() -> int:
    t0 = time.time()
    if not CCQS_PATH.exists() or not OHLCV_PATH.exists():
        logger.error("Missing inputs. Run earlier pipeline stages first.")
        return 1
    ccqs = pd.read_parquet(CCQS_PATH)
    ohlcv = pd.read_parquet(OHLCV_PATH)
    logger.info(f"Loaded ccqs {ccqs.shape}, ohlcv {ohlcv.shape}")
    out = compute_ic(ccqs, ohlcv)
    elapsed = time.time() - t0

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))

    s = out["summary"]
    print()
    print("=" * 60)
    print("INFORMATION COEFFICIENT TRACKER")
    print("=" * 60)
    for h in HORIZONS:
        print(
            f"  IC_{h}d   mean={s[f'ic_{h}d_mean']}  "
            f"median={s[f'ic_{h}d_median']}  "
            f"std={s[f'ic_{h}d_std']}  "
            f"t={s[f'ic_{h}d_t_stat']}  "
            f"hit={s[f'ic_{h}d_hit_rate']}  "
            f"n={s[f'ic_{h}d_n_dates']}"
        )
    print(f"Elapsed: {elapsed:.1f}s")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
