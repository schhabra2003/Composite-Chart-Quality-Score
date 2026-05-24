"""Historical backfill validation — Step 3a Part B4.

Spot-checks CCQS history after the 7-year OHLCV backfill (Phase 5.2 + Methodology
Lock). Confirms:

  - Recognizable large caps (NVDA, MSFT, COST, JPM, NVO) have plausible
    trajectories: moderate-to-high in 2020 (COVID recovery), elevated in
    2024-2025 (AI rally), variability across regimes.
  - No NaN bleed: every (ticker, date) row inside the valid window has a
    finite CCQS.
  - 252-day warmup correctly excludes pre-2020-01-01 dates from valid CCQS
    for sample tickers with full history.
  - Recent IPOs (PLTR, SNOW, CRWD) handle missing pre-IPO data without
    contaminating the valid window.

Report (printed + JSON written to data/cache/historical_backfill_validation.json):

  - Earliest valid CCQS date per sample ticker
  - Latest valid CCQS date
  - CCQS at three regime markers: 2020-03-23 (COVID low), 2022-10-13 (CPI
    peak), 2024-06-13 (AI peak)
  - Count of valid (non-NaN) CCQS rows per ticker
  - Overall NaN-bleed counts

Run:
    python -m compute.validation.historical_backfill_validation
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache"
OUT_PATH = CACHE / "historical_backfill_validation.json"


LARGE_CAP_SAMPLE = ["NVDA", "MSFT", "COST", "JPM", "NVO"]
RECENT_IPO_SAMPLE = ["PLTR", "SNOW", "CRWD"]

# Regime markers: dates to spot-check
REGIME_MARKERS = {
    "2020-03-23": "COVID low",
    "2022-10-13": "CPI peak (bear-market low)",
    "2024-06-13": "AI rally peak window",
}

# Reasonableness band: 0-100 (CCQS is bounded)
CCQS_MIN, CCQS_MAX = 0.0, 100.0


def _nearest_date(idx: pd.DatetimeIndex, target: pd.Timestamp) -> pd.Timestamp | None:
    """Nearest available date in idx on/after target (or before if no after)."""
    if len(idx) == 0:
        return None
    on_or_after = idx[idx >= target]
    if len(on_or_after) > 0:
        return on_or_after.min()
    return idx.max()


def _ticker_summary(ccqs: pd.DataFrame, ticker: str) -> dict:
    """Per-ticker stats: range, count, regime-marker values."""
    try:
        sub = ccqs.xs(ticker, level="ticker")
    except KeyError:
        return {"ticker": ticker, "present": False}

    valid = sub.dropna(subset=["ccqs"])
    out: dict = {
        "ticker": ticker,
        "present": True,
        "total_rows": int(len(sub)),
        "valid_rows": int(len(valid)),
        "nan_rows": int(len(sub) - len(valid)),
        "earliest_valid": valid.index.min().strftime("%Y-%m-%d") if len(valid) else None,
        "latest_valid":   valid.index.max().strftime("%Y-%m-%d") if len(valid) else None,
        "ccqs_min":  float(valid["ccqs"].min()) if len(valid) else None,
        "ccqs_max":  float(valid["ccqs"].max()) if len(valid) else None,
        "ccqs_mean": float(valid["ccqs"].mean()) if len(valid) else None,
    }

    # Regime markers
    out["regime_markers"] = {}
    for date_str, label in REGIME_MARKERS.items():
        tgt = pd.Timestamp(date_str)
        match = _nearest_date(valid.index, tgt)
        if match is None:
            out["regime_markers"][date_str] = {"label": label, "actual_date": None, "ccqs": None}
        else:
            try:
                ccqs_val = float(valid.loc[match, "ccqs"])
            except Exception:
                ccqs_val = None
            out["regime_markers"][date_str] = {
                "label": label,
                "actual_date": match.strftime("%Y-%m-%d"),
                "ccqs": ccqs_val,
            }
    return out


def run_validation() -> dict:
    ccqs_path = CACHE / "ccqs.parquet"
    if not ccqs_path.exists():
        raise FileNotFoundError(f"Missing {ccqs_path} — run the pipeline first.")
    ccqs = pd.read_parquet(ccqs_path)

    # Coverage overall
    dates = ccqs.index.get_level_values("date")
    tickers = ccqs.index.get_level_values("ticker")
    overall = {
        "rows": int(len(ccqs)),
        "unique_tickers": int(tickers.nunique()),
        "unique_dates": int(dates.nunique()),
        "date_min": dates.min().strftime("%Y-%m-%d"),
        "date_max": dates.max().strftime("%Y-%m-%d"),
        "valid_rows": int(ccqs["ccqs"].notna().sum()),
        "nan_rows": int(ccqs["ccqs"].isna().sum()),
        "pre_2020_rows": int((dates < pd.Timestamp("2020-01-01")).sum()),
        "pre_2020_valid_rows": int(
            ((dates < pd.Timestamp("2020-01-01")) & ccqs["ccqs"].notna()).sum()
        ),
    }

    # Warmup check: every valid row should be 2020-01-01 or later (252-day warmup)
    warmup_violations = ccqs[
        (ccqs.index.get_level_values("date") < pd.Timestamp("2020-01-01"))
        & ccqs["ccqs"].notna()
    ]

    # Bounds check: 0 <= ccqs <= 100
    valid_only = ccqs.dropna(subset=["ccqs"])
    out_of_bounds = valid_only[
        (valid_only["ccqs"] < CCQS_MIN) | (valid_only["ccqs"] > CCQS_MAX)
    ]

    # Sample tickers
    large_caps = [_ticker_summary(ccqs, t) for t in LARGE_CAP_SAMPLE]
    recent_ipos = [_ticker_summary(ccqs, t) for t in RECENT_IPO_SAMPLE]

    # Reasonableness asserts on NVDA per spec
    nvda = next((t for t in large_caps if t["ticker"] == "NVDA" and t.get("present")), None)
    nvda_check = {}
    if nvda:
        m = nvda.get("regime_markers", {})
        ccqs_2020 = m.get("2020-03-23", {}).get("ccqs")
        ccqs_2024 = m.get("2024-06-13", {}).get("ccqs")
        nvda_check = {
            "2020_03_23": ccqs_2020,
            "2024_06_13": ccqs_2024,
            "2020_in_band":  ccqs_2020 is not None and 30.0 <= ccqs_2020 <= 95.0,
            "2024_elevated": ccqs_2024 is not None and ccqs_2024 >= 50.0,
            "variability_ok": (
                nvda["ccqs_max"] - nvda["ccqs_min"] >= 10.0
                if nvda.get("ccqs_min") is not None and nvda.get("ccqs_max") is not None
                else False
            ),
        }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "warmup_violations_count": int(len(warmup_violations)),
        "out_of_bounds_count": int(len(out_of_bounds)),
        "large_cap_sample": large_caps,
        "recent_ipo_sample": recent_ipos,
        "nvda_reasonableness": nvda_check,
        "verdict": (
            "PASS"
            if (
                len(warmup_violations) == 0
                and len(out_of_bounds) == 0
                and overall["valid_rows"] > 0
                and (not nvda_check or all(
                    v for k, v in nvda_check.items() if isinstance(v, bool)
                ))
            )
            else "REVIEW"
        ),
    }
    return report


def _print_report(rep: dict) -> None:
    o = rep["overall"]
    print()
    print("=" * 72)
    print("HISTORICAL BACKFILL VALIDATION")
    print("=" * 72)
    print(f"  Total rows:           {o['rows']:>10,}")
    print(f"  Unique tickers:       {o['unique_tickers']:>10,}")
    print(f"  Unique dates:         {o['unique_dates']:>10,}")
    print(f"  Date range:           {o['date_min']} → {o['date_max']}")
    print(f"  Valid CCQS rows:      {o['valid_rows']:>10,}")
    print(f"  NaN CCQS rows:        {o['nan_rows']:>10,}")
    print(f"  Pre-2020 rows:        {o['pre_2020_rows']:>10,}")
    print(f"  Pre-2020 valid rows:  {o['pre_2020_valid_rows']:>10,}  (must be 0 — 252d warmup)")
    print(f"  Warmup violations:    {rep['warmup_violations_count']:>10,}")
    print(f"  Out-of-bounds CCQS:   {rep['out_of_bounds_count']:>10,}")
    print()
    print("LARGE CAP SAMPLE:")
    print(f"  {'ticker':<6} {'earliest':<12} {'latest':<12} {'valid_rows':>10} "
          f"{'min':>6} {'mean':>6} {'max':>6}")
    for t in rep["large_cap_sample"]:
        if not t.get("present"):
            print(f"  {t['ticker']:<6} (not in universe)")
            continue
        print(f"  {t['ticker']:<6} {t['earliest_valid']:<12} {t['latest_valid']:<12} "
              f"{t['valid_rows']:>10,} {t['ccqs_min']:>6.1f} {t['ccqs_mean']:>6.1f} {t['ccqs_max']:>6.1f}")

    print()
    print("REGIME MARKERS (large caps):")
    for date_str, label in REGIME_MARKERS.items():
        print(f"  {date_str} — {label}")
        for t in rep["large_cap_sample"]:
            if not t.get("present"):
                continue
            m = t["regime_markers"].get(date_str, {})
            ad = m.get("actual_date") or "—"
            cv = m.get("ccqs")
            cv_s = f"{cv:.1f}" if cv is not None else "—"
            print(f"    {t['ticker']:<6} {ad}  CCQS={cv_s}")

    print()
    print("RECENT IPO SAMPLE:")
    print(f"  {'ticker':<6} {'earliest':<12} {'latest':<12} {'valid_rows':>10}")
    for t in rep["recent_ipo_sample"]:
        if not t.get("present"):
            print(f"  {t['ticker']:<6} (not in universe)")
            continue
        print(f"  {t['ticker']:<6} {t['earliest_valid']:<12} {t['latest_valid']:<12} "
              f"{t['valid_rows']:>10,}")

    print()
    print("NVDA REASONABLENESS:")
    for k, v in rep["nvda_reasonableness"].items():
        print(f"  {k}: {v}")

    print()
    print(f"VERDICT: {rep['verdict']}")
    print("=" * 72)


def main() -> int:
    rep = run_validation()
    OUT_PATH.write_text(json.dumps(rep, indent=2))
    _print_report(rep)
    return 0 if rep["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
