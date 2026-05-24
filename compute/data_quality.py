"""
CCQS V1 — Data Quality Firewall (SPEC Section 13 Layer 1)

Runs BEFORE feature computation. Tickers failing critical checks are
EXCLUDED from scoring. Tickers with only warnings are scored but flagged.

Critical failures (exclude from scoring):
  - NO_DATA                  empty DataFrame
  - INSUFFICIENT_HISTORY     < 252 trading days
  - STALE_DATA               last bar > 5 trading days ago
  - INVALID_PRICES           any zero or negative price
  - ZERO_VOLUME              20-day volume sum = 0
  - INSUFFICIENT_LIQUIDITY   median 20d dollar volume < $100K
  - SUSPICIOUS_BAR           >50% intraday range, >5x avg vol, body/range<0.40
                             (wick-like print => likely data error)

Warnings (still scored):
  - LARGE_GAP_RECENT          >30% one-day move in last 20d
  - VOLUME_COLLAPSE           recent (20d) vol < 10% of historical (252d)
  - LOW_LIQUIDITY             median 20d dollar volume < $1M
  - FREQUENT_GAPS             >=5 daily gaps >5% in last 20d
  - FREQUENT_DOJI             >=5 doji bars in last 20d (|close-open|/range < 0.1)
  - POSSIBLE_CORPORATE_ACTION ratio close/adj_close jumps >10% on a day

Output:
  data/cache/data_quality_report.json
    {
      "summary": {pass, warning, fail, total},
      "results": {
        "NVDA": {"status": "PASS", "critical": [], "warnings": []},
        ...
      }
    }

Honors data/manual_overrides.yaml -> data_quality_overrides to suppress
specific codes per ticker (Layer 7).

Run standalone:
    python -m compute.data_quality
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from loguru import logger

from compute.loader import CACHE_DIR, LOG_DIR, load_cached_ohlcv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = CACHE_DIR / "data_quality_report.json"
OVERRIDES_PATH = PROJECT_ROOT / "data" / "manual_overrides.yaml"

# Critical thresholds
MIN_HISTORY_DAYS = 252
MAX_STALENESS_DAYS = 5
MIN_LIQUIDITY_USD = 100_000        # critical floor

# Suspicious-bar / large-reversal-bar detection
SUSPICIOUS_MOVE_PCT = 0.50         # >50% intraday range qualifies a bar
WICK_BODY_RATIO = 0.40             # body/range < 0.40 => wick-like (data-error
                                    # fingerprint). Bars closing with >=40% body
                                    # have directional conviction — structurally
                                    # inconsistent with a bad print.
NEXT_DAY_REVERSAL_PCT = 0.05       # next-day reversal: >5% opposite move
SUSPICIOUS_VOLUME_MULTIPLIER = 5.0  # >5x avg vol => potential data error;
                                    # wick-like + high-vol bars FAIL;
                                    # directional + high-vol bars with next-day
                                    # reversal WARN as LARGE_REVERSAL_BAR.

# Warning thresholds
LARGE_GAP_PCT = 0.30               # 30% one-day move
VOLUME_COLLAPSE_RATIO = 0.10       # recent vs historical
LOW_LIQUIDITY_USD = 1_000_000      # warning floor (above critical)
FREQUENT_GAP_PCT = 0.05            # 5% daily gap
FREQUENT_GAP_COUNT = 5
DOJI_BODY_RATIO = 0.10             # body / range
DOJI_COUNT = 5
CORP_ACTION_RATIO_JUMP = 0.10      # close/adj_close ratio jump

CRITICAL_CODES = {
    "NO_DATA",
    "INSUFFICIENT_HISTORY",
    "STALE_DATA",
    "INVALID_PRICES",
    "ZERO_VOLUME",
    "INSUFFICIENT_LIQUIDITY",
    "SUSPICIOUS_BAR",
}

WARNING_CODES = {
    "LARGE_GAP_RECENT",
    "VOLUME_COLLAPSE",
    "LOW_LIQUIDITY",
    "FREQUENT_GAPS",
    "FREQUENT_DOJI",
    "POSSIBLE_CORPORATE_ACTION",
    "LARGE_REVERSAL_BAR",
}


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")
logger.add(LOG_DIR / "ccqs.log", level="DEBUG", rotation="10 MB", retention="30 days")


# ---------------------------------------------------------------------------
# Manual overrides
# ---------------------------------------------------------------------------

def _load_overrides() -> dict[str, list[str]]:
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        data = yaml.safe_load(OVERRIDES_PATH.read_text()) or {}
    except yaml.YAMLError as exc:
        logger.warning(f"Could not parse {OVERRIDES_PATH}: {exc}")
        return {}
    raw = data.get("data_quality_overrides", {}) or {}
    return {k: list(v or []) for k, v in raw.items()}


# ---------------------------------------------------------------------------
# Per-ticker checks
# ---------------------------------------------------------------------------

def _critical_checks(df: pd.DataFrame, reference_date: pd.Timestamp) -> list[str]:
    """Return list of critical failure codes for one ticker's frame."""
    codes: list[str] = []

    if df is None or df.empty:
        return ["NO_DATA"]

    n = len(df)
    if n < MIN_HISTORY_DAYS:
        codes.append("INSUFFICIENT_HISTORY")

    # Staleness vs reference (max date across the universe = most recent
    # trading day available in the cache)
    last_date = df["date"].max()
    days_stale = (reference_date - last_date).days
    if days_stale > MAX_STALENESS_DAYS:
        codes.append("STALE_DATA")

    # Invalid prices: any non-positive in OHLC (allow NaN — those rows
    # simply don't contribute, but zero/negative is corrupt)
    price_cols = ["open", "high", "low", "close"]
    prices = df[price_cols]
    if (prices.fillna(1.0) <= 0).any().any():
        codes.append("INVALID_PRICES")

    # 20-day rolling volume window — use the most recent 20 bars
    recent = df.tail(20)
    if recent["volume"].fillna(0).sum() == 0:
        codes.append("ZERO_VOLUME")

    # Liquidity: median dollar volume across recent 20 bars
    if len(recent) >= 5:
        dollar_vol = (recent["close"] * recent["volume"]).dropna()
        if not dollar_vol.empty:
            med_dv = float(np.median(dollar_vol))
            if med_dv < MIN_LIQUIDITY_USD:
                codes.append("INSUFFICIENT_LIQUIDITY")

    # Suspicious / large-reversal bar detection is shared between critical and
    # warning paths — see _detect_large_reversal_bars and check_ticker.

    return codes


def _warning_checks(df: pd.DataFrame) -> list[str]:
    codes: list[str] = []
    if df is None or df.empty:
        return codes

    close = df["close"]
    open_ = df["open"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    daily_ret = close.pct_change(fill_method=None)
    recent_ret = daily_ret.tail(20)

    # LARGE_GAP_RECENT
    if (recent_ret.abs() > LARGE_GAP_PCT).any():
        codes.append("LARGE_GAP_RECENT")

    # VOLUME_COLLAPSE
    if len(df) >= 252:
        recent_vol = volume.tail(20).mean()
        hist_vol = volume.tail(252).mean()
        if hist_vol > 0 and recent_vol / hist_vol < VOLUME_COLLAPSE_RATIO:
            codes.append("VOLUME_COLLAPSE")

    # LOW_LIQUIDITY (warning band — above critical floor)
    recent = df.tail(20)
    if len(recent) >= 5:
        dollar_vol = (recent["close"] * recent["volume"]).dropna()
        if not dollar_vol.empty:
            med_dv = float(np.median(dollar_vol))
            if MIN_LIQUIDITY_USD <= med_dv < LOW_LIQUIDITY_USD:
                codes.append("LOW_LIQUIDITY")

    # FREQUENT_GAPS
    if (recent_ret.abs() > FREQUENT_GAP_PCT).sum() >= FREQUENT_GAP_COUNT:
        codes.append("FREQUENT_GAPS")

    # FREQUENT_DOJI
    rng = (high - low).replace(0, np.nan)
    body = (close - open_).abs()
    body_ratio = body / rng
    recent_body = body_ratio.tail(20)
    if (recent_body < DOJI_BODY_RATIO).sum() >= DOJI_COUNT:
        codes.append("FREQUENT_DOJI")

    # POSSIBLE_CORPORATE_ACTION
    if "adj_close" in df.columns:
        adj = df["adj_close"]
        ratio = (close / adj.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
        ratio_change = ratio.pct_change(fill_method=None).abs()
        if (ratio_change > CORP_ACTION_RATIO_JUMP).any():
            codes.append("POSSIBLE_CORPORATE_ACTION")

    return codes


def _detect_large_reversal_bars(df: pd.DataFrame) -> tuple[bool, bool]:
    """
    Detect bars with > 50% intraday range under two pathways.

    Common gate (both pathways): big_range AND volume > 5x 50-day prior avg.
    The discriminator between FAIL and WARN is the body/range ratio — a bar
    closing with >=40% body has directional conviction (real move), while
    body<40% looks like a wick artifact (data error).

    Pathway A — same-day partial reversal:
      big_range + body_ratio < 0.40 + high_volume
        -> SUSPICIOUS_BAR (critical / FAIL)

    Pathway B — next-day reversal:
      big_range + high_volume + body_ratio < 0.40 + next-day >5% opposite
        -> SUSPICIOUS_BAR (critical / FAIL)
      (subset of pathway A — included for explicitness)

    Downgrade — directional conviction:
      big_range + high_volume + body_ratio >= 0.40 + next-day >5% opposite
        -> LARGE_REVERSAL_BAR (warning) — real but unusual move (e.g. earnings
        crash where the stock closes near its low and bottom-fishes the
        following day).

    Returns (is_suspicious, is_large_reversal_only).
    """
    if df is None or df.empty:
        return (False, False)

    high = df["high"]
    low = df["low"]
    open_ = df["open"]
    close = df["close"]
    volume = df["volume"]

    with np.errstate(divide="ignore", invalid="ignore"):
        intraday_range_pct = (high - low) / low.replace(0, np.nan)
        rng = (high - low).replace(0, np.nan)
        body_ratio = (close - open_).abs() / rng

    big_range = (intraday_range_pct > SUSPICIOUS_MOVE_PCT).fillna(False)
    if not big_range.any():
        return (False, False)

    vol_avg = volume.rolling(50, min_periods=20).mean()
    high_volume = (volume > SUSPICIOUS_VOLUME_MULTIPLIER * vol_avg).fillna(False)

    qualifying = big_range & high_volume
    if not qualifying.any():
        return (False, False)

    wick_like = (body_ratio < WICK_BODY_RATIO).fillna(False)

    # Next-day reversal: next bar moves >5% in the opposite direction.
    bar_dir = np.sign(close - open_)
    next_open = open_.shift(-1)
    next_close = close.shift(-1)
    with np.errstate(divide="ignore", invalid="ignore"):
        next_change_pct = (next_close - next_open) / next_open.replace(0, np.nan)
    next_dir = np.sign(next_change_pct)
    next_day_rev = (
        (bar_dir != 0)
        & (next_dir == -bar_dir)
        & (next_change_pct.abs() > NEXT_DAY_REVERSAL_PCT)
    ).fillna(False)

    # FAIL: wick-like high-volume big-range bar (covers pathways A and B —
    # pathway B is a subset since wick-like is the discriminator).
    suspicious = qualifying & wick_like

    # WARNING: directional high-volume big-range bar with next-day reversal.
    large_reversal = qualifying & ~wick_like & next_day_rev

    is_suspicious = bool(suspicious.any())
    is_large_reversal = bool((large_reversal & ~suspicious).any())
    return (is_suspicious, is_large_reversal)


def check_ticker(
    df: pd.DataFrame,
    reference_date: pd.Timestamp,
    suppressed: set[str] | None = None,
) -> dict[str, Any]:
    """Run all checks for one ticker. Return structured result."""
    suppressed = suppressed or set()

    crit = _critical_checks(df, reference_date)
    warn = _warning_checks(df)

    # Shared detection for large-range reversal bars: high-volume variant is
    # critical (SUSPICIOUS_BAR), normal-volume variant is a warning.
    is_suspicious, is_large_reversal = _detect_large_reversal_bars(df)
    if is_suspicious:
        crit.append("SUSPICIOUS_BAR")
    if is_large_reversal:
        warn.append("LARGE_REVERSAL_BAR")

    crit = [c for c in crit if c not in suppressed]
    warn = [c for c in warn if c not in suppressed]

    if crit:
        status = "FAIL"
    elif warn:
        status = "WARNING"
    else:
        status = "PASS"

    return {
        "status": status,
        "critical": crit,
        "warnings": warn,
        "rows": int(len(df)) if df is not None else 0,
    }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_quality_firewall(
    long_df: pd.DataFrame,
    overrides: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Run firewall over all tickers in the long frame."""
    if long_df.empty:
        logger.error("OHLCV cache is empty — nothing to check.")
        return {"summary": {"pass": 0, "warning": 0, "fail": 0, "total": 0}, "results": {}}

    overrides = overrides or {}
    reference_date = long_df["date"].max()
    logger.info(f"Reference date (most recent bar in cache): {reference_date.date()}")

    results: dict[str, dict[str, Any]] = {}
    counts = {"PASS": 0, "WARNING": 0, "FAIL": 0}

    tickers = sorted(long_df["ticker"].unique())
    logger.info(f"Running quality firewall on {len(tickers)} tickers")

    grouped = long_df.groupby("ticker", sort=False)
    for ticker in tickers:
        sub = grouped.get_group(ticker).sort_values("date").reset_index(drop=True)
        suppressed = set(overrides.get(ticker, []))
        result = check_ticker(sub, reference_date, suppressed=suppressed)
        if suppressed:
            result["suppressed"] = sorted(suppressed)
        results[ticker] = result
        counts[result["status"]] += 1

    summary = {
        "pass": counts["PASS"],
        "warning": counts["WARNING"],
        "fail": counts["FAIL"],
        "total": len(tickers),
        "reference_date": reference_date.date().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"summary": summary, "results": results}


def write_report(report: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True))
    logger.info(f"Wrote {REPORT_PATH}")


def main() -> int:
    try:
        long_df = load_cached_ohlcv()
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 1

    overrides = _load_overrides()
    if overrides:
        logger.info(f"Loaded data-quality overrides for {len(overrides)} tickers")

    report = run_quality_firewall(long_df, overrides=overrides)
    write_report(report)

    s = report["summary"]
    print()
    print("=" * 60)
    print("DATA QUALITY FIREWALL SUMMARY")
    print("=" * 60)
    print(f"Reference date:  {s['reference_date']}")
    print(f"Total tickers:   {s['total']}")
    print(f"  PASS:          {s['pass']}")
    print(f"  WARNING:       {s['warning']}")
    print(f"  FAIL:          {s['fail']}")
    print("=" * 60)

    # Top reasons
    fail_reasons: dict[str, int] = {}
    warn_reasons: dict[str, int] = {}
    for r in report["results"].values():
        for c in r.get("critical", []):
            fail_reasons[c] = fail_reasons.get(c, 0) + 1
        for c in r.get("warnings", []):
            warn_reasons[c] = warn_reasons.get(c, 0) + 1

    if fail_reasons:
        print("\nFAIL codes:")
        for code, n in sorted(fail_reasons.items(), key=lambda x: -x[1]):
            print(f"  {code:30s} {n}")
    if warn_reasons:
        print("\nWARNING codes:")
        for code, n in sorted(warn_reasons.items(), key=lambda x: -x[1]):
            print(f"  {code:30s} {n}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
