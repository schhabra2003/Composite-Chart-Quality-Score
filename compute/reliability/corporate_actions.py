"""
CCQS V1 — Corporate Actions Detection (SPEC Section 13, Layer 2)

Detect splits, possible spinoffs, and trading halts from `ohlcv_daily.parquet`.

Detection heuristics:
  - SPLIT: ratio = close / adj_close. A jump in this ratio (|pct_change| > 0.10)
    on a single day indicates a corporate action that adjusts historical prices
    relative to today's close (forward / reverse split, large special dividend).
  - SPINOFF (possible): divergence between close return and adj_close return
    larger than 5% on a day NOT already flagged as a split. The unadjusted
    close drops while the dividend-adjusted return does not — classic spinoff
    or large special-dividend shape.
  - HALT: missing trading-day gap on the per-ticker date sequence that exceeds
    5 calendar days (so weekends + a single holiday are excluded). Anything
    longer is a likely trading halt or de-listing pause.

Output: `data/cache/corporate_actions.json` — per-ticker dictionary of dates,
plus a summary block (totals, last 30 days, top-affected tickers).

Run:
    python -m compute.reliability.corporate_actions
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

from compute.loader import CACHE_DIR, LOG_DIR

OHLCV_PATH = CACHE_DIR / "ohlcv_daily.parquet"
OUT_PATH = CACHE_DIR / "corporate_actions.json"

SPLIT_RATIO_THRESHOLD = 0.10        # 10% jump in close/adj_close
SPINOFF_RETURN_THRESHOLD = 0.05      # 5% divergence between close/adj returns
HALT_GAP_DAYS = 5                    # >5 calendar days = halt

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")
logger.add(LOG_DIR / "ccqs.log", level="DEBUG", rotation="10 MB", retention="30 days")


def _detect_one(g: pd.DataFrame) -> dict[str, list[str]]:
    """Per-ticker detection. `g` is sorted by date for one ticker."""
    g = g.sort_values("date").reset_index(drop=True)
    close = g["close"].astype(float)
    adj = g["adj_close"].astype(float)
    dates = g["date"]

    # Avoid /0 noise — drop rows where adj_close is 0 or NaN.
    safe = (adj > 0) & adj.notna() & (close > 0) & close.notna()
    ratio = close.where(safe) / adj.where(safe)
    ratio_pct = ratio.pct_change(fill_method=None)
    split_mask = ratio_pct.abs() > SPLIT_RATIO_THRESHOLD
    split_mask = split_mask.fillna(False)

    close_ret = close.pct_change(fill_method=None)
    adj_ret = adj.pct_change(fill_method=None)
    div = (close_ret - adj_ret).abs()
    spinoff_mask = (div > SPINOFF_RETURN_THRESHOLD).fillna(False) & ~split_mask

    # Halts: gaps in trading-day sequence > HALT_GAP_DAYS calendar days.
    gaps_days = dates.diff().dt.days
    halt_mask = (gaps_days > HALT_GAP_DAYS).fillna(False)

    def _to_iso(mask: pd.Series) -> list[str]:
        return [d.strftime("%Y-%m-%d") for d in dates[mask].tolist()]

    return {
        "splits": _to_iso(split_mask),
        "spinoffs": _to_iso(spinoff_mask),
        "halts": _to_iso(halt_mask),
    }


def detect_corporate_actions(ohlcv: pd.DataFrame) -> dict[str, dict]:
    """Run detection per ticker and assemble the output dict."""
    tickers = sorted(ohlcv["ticker"].unique())
    per_ticker: dict[str, dict[str, list[str]]] = {}
    total_splits = 0
    total_spinoffs = 0
    total_halts = 0
    for tk in tickers:
        g = ohlcv[ohlcv["ticker"] == tk]
        if len(g) < 2:
            continue
        events = _detect_one(g)
        if events["splits"] or events["spinoffs"] or events["halts"]:
            per_ticker[tk] = events
            total_splits += len(events["splits"])
            total_spinoffs += len(events["spinoffs"])
            total_halts += len(events["halts"])

    # Last 30 days summary — count events whose date >= max_date - 30d.
    max_date = ohlcv["date"].max()
    cutoff = max_date - pd.Timedelta(days=30)
    cutoff_iso = cutoff.strftime("%Y-%m-%d")

    def _recent(lst: list[str]) -> int:
        return sum(1 for d in lst if d >= cutoff_iso)

    recent_splits = sum(_recent(v["splits"]) for v in per_ticker.values())
    recent_spinoffs = sum(_recent(v["spinoffs"]) for v in per_ticker.values())
    recent_halts = sum(_recent(v["halts"]) for v in per_ticker.values())

    # Top-affected tickers (>1 event total)
    affected = sorted(
        (
            (
                tk,
                len(v["splits"]) + len(v["spinoffs"]) + len(v["halts"]),
                v,
            )
            for tk, v in per_ticker.items()
        ),
        key=lambda x: x[1],
        reverse=True,
    )
    top_affected = [
        {
            "ticker": tk,
            "n_events": n,
            "splits": v["splits"],
            "spinoffs": v["spinoffs"],
            "halts": v["halts"],
        }
        for tk, n, v in affected[:20]
        if n > 0
    ]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "max_date": max_date.strftime("%Y-%m-%d"),
        "n_tickers_scanned": len(tickers),
        "n_tickers_with_events": len(per_ticker),
        "total_splits": total_splits,
        "total_spinoffs": total_spinoffs,
        "total_halts": total_halts,
        "last_30d": {
            "splits": recent_splits,
            "spinoffs": recent_spinoffs,
            "halts": recent_halts,
        },
        "top_affected": top_affected,
    }
    return {"summary": summary, "per_ticker": per_ticker}


def main() -> int:
    t0 = time.time()
    if not OHLCV_PATH.exists():
        logger.error(f"Missing {OHLCV_PATH}. Run `python -m compute.loader` first.")
        return 1
    ohlcv = pd.read_parquet(OHLCV_PATH)
    logger.info(f"Loaded ohlcv {ohlcv.shape}")
    out = detect_corporate_actions(ohlcv)
    elapsed = time.time() - t0
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))

    s = out["summary"]
    print()
    print("=" * 60)
    print("CORPORATE ACTIONS DETECTION")
    print("=" * 60)
    print(f"  Tickers scanned         : {s['n_tickers_scanned']}")
    print(f"  Tickers with events     : {s['n_tickers_with_events']}")
    print(f"  Total splits            : {s['total_splits']}")
    print(f"  Total spinoffs          : {s['total_spinoffs']}")
    print(f"  Total halts             : {s['total_halts']}")
    print(f"  Last 30d splits         : {s['last_30d']['splits']}")
    print(f"  Last 30d spinoffs       : {s['last_30d']['spinoffs']}")
    print(f"  Last 30d halts          : {s['last_30d']['halts']}")
    print(f"Elapsed: {elapsed:.1f}s")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
