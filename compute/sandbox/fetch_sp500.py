"""CCQS V1 Sandbox — Step 1: SP500 fetch, REIT filter, missing-equity OHLCV fetch.

Loads the cached SP500 constituents (data/cache/sp500_constituents.parquet),
excludes REITs, identifies SP500 tickers not in the production universe, and
fetches 7-year OHLCV for those via yfinance. Combines with production OHLCV
and runs the quality firewall on the union, writing all outputs to
data/cache/sandbox/.

Outputs:
    data/cache/sandbox/sp500_constituents_filtered.parquet
    data/cache/sandbox/sp500_missing_equities.json
    data/cache/sandbox/ohlcv_daily.parquet     (combined: prod + sandbox tickers)
    data/cache/sandbox/data_quality_report.json (combined)

Run:
    python -m compute.sandbox.fetch_sp500
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from loguru import logger

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from compute.data_quality import run_quality_firewall
from compute.loader import CACHE_DIR as PROD_CACHE_DIR, fetch_all, load_cached_ohlcv
from data.universe import all_unique_tickers

SANDBOX_CACHE_DIR = ROOT / "data" / "cache" / "sandbox"
SANDBOX_CACHE_DIR.mkdir(parents=True, exist_ok=True)

SP500_SOURCE_PATH = PROD_CACHE_DIR / "sp500_constituents.parquet"
SP500_FILTERED_PATH = SANDBOX_CACHE_DIR / "sp500_constituents_filtered.parquet"
MISSING_EQUITIES_PATH = SANDBOX_CACHE_DIR / "sp500_missing_equities.json"
SANDBOX_OHLCV_PATH = SANDBOX_CACHE_DIR / "ohlcv_daily.parquet"
SANDBOX_OHLCV_META_PATH = SANDBOX_CACHE_DIR / "ohlcv_meta.json"
SANDBOX_QUALITY_PATH = SANDBOX_CACHE_DIR / "data_quality_report.json"


def load_sp500_constituents() -> pd.DataFrame:
    """Read the cached SP500 parquet from production cache (already maintained)."""
    if not SP500_SOURCE_PATH.exists():
        raise FileNotFoundError(
            f"SP500 cache not found at {SP500_SOURCE_PATH}. "
            "Run `python -m compute.data.sp500_membership` first."
        )
    df = pd.read_parquet(SP500_SOURCE_PATH)
    logger.info(f"Loaded {len(df)} SP500 constituents from cache")
    return df


def filter_and_identify_missing(sp500: pd.DataFrame, prod_universe: set[str]) -> tuple[pd.DataFrame, list[str], dict]:
    """Apply REIT exclusion, identify SP500 tickers not in production universe."""
    n_total = len(sp500)
    is_reit = sp500["gics_sector"] == "Real Estate"
    n_reits = int(is_reit.sum())

    filtered = sp500[~is_reit].copy().reset_index(drop=True)
    n_after_reit = len(filtered)

    sp500_set = set(filtered["ticker"])
    missing_set = sp500_set - prod_universe
    missing_list = sorted(missing_set)

    # GICS sector distribution among missing
    miss_df = filtered[filtered["ticker"].isin(missing_set)]
    sector_dist = miss_df["gics_sector"].value_counts().to_dict()

    summary = {
        "sp500_total": int(n_total),
        "reits_excluded": int(n_reits),
        "sp500_after_reit_filter": int(n_after_reit),
        "production_universe_size": int(len(prod_universe)),
        "in_both": int(len(sp500_set & prod_universe)),
        "missing_equities_count": int(len(missing_set)),
        "missing_gics_sector_distribution": sector_dist,
    }
    return filtered, missing_list, summary


def fetch_missing_ohlcv(tickers: list[str]) -> tuple[pd.DataFrame, dict[str, str]]:
    """Fetch OHLCV for sandbox-only tickers via yfinance."""
    if not tickers:
        return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"]), {}
    logger.info(f"Fetching OHLCV for {len(tickers)} sandbox-only tickers")
    long_df, failed = fetch_all(tickers)
    return long_df, failed


def combine_with_production_ohlcv(sandbox_long: pd.DataFrame) -> pd.DataFrame:
    """Concat production OHLCV (already cached) with sandbox-only OHLCV."""
    prod = load_cached_ohlcv()
    if sandbox_long.empty:
        return prod.copy()
    combined = pd.concat([prod, sandbox_long], ignore_index=True)
    combined = combined.sort_values(["ticker", "date"]).reset_index(drop=True)
    return combined


def main() -> int:
    t0 = time.time()
    logger.info("=" * 60)
    logger.info("CCQS Sandbox — Step 1: SP500 fetch + missing-equity OHLCV")
    logger.info("=" * 60)

    sp500 = load_sp500_constituents()

    prod_set = set(all_unique_tickers())
    logger.info(f"Production declared universe: {len(prod_set)} tickers")

    filtered, missing_list, summary = filter_and_identify_missing(sp500, prod_set)
    filtered.to_parquet(SP500_FILTERED_PATH, index=False)
    logger.info(f"Wrote {SP500_FILTERED_PATH} ({len(filtered)} non-REIT SP500 names)")
    logger.info(f"SP500 \\ production universe: {len(missing_list)} missing equities")

    # Fetch OHLCV for missing tickers
    sandbox_long, failed = fetch_missing_ohlcv(missing_list)
    n_fetched = int(sandbox_long["ticker"].nunique()) if not sandbox_long.empty else 0
    logger.info(f"Fetched OHLCV for {n_fetched}/{len(missing_list)} sandbox-only tickers ({len(failed)} failed)")

    # Combine with production OHLCV and write to sandbox cache
    combined = combine_with_production_ohlcv(sandbox_long)
    combined.to_parquet(SANDBOX_OHLCV_PATH, index=False, compression="snappy")
    meta = {
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers_total": int(combined["ticker"].nunique()),
        "n_tickers_sandbox_only": n_fetched,
        "n_failed_fetch": len(failed),
        "date_min": combined["date"].min().date().isoformat() if not combined.empty else None,
        "date_max": combined["date"].max().date().isoformat() if not combined.empty else None,
        "rows": int(len(combined)),
    }
    SANDBOX_OHLCV_META_PATH.write_text(json.dumps(meta, indent=2))
    logger.info(f"Wrote {SANDBOX_OHLCV_PATH} ({len(combined):,} rows, {meta['n_tickers_total']} tickers)")

    # Quality firewall on combined OHLCV
    logger.info("Running quality firewall on combined (production + sandbox) OHLCV ...")
    report = run_quality_firewall(combined)
    SANDBOX_QUALITY_PATH.write_text(json.dumps(report, indent=2, sort_keys=True))
    s = report["summary"]
    logger.info(f"Quality summary: PASS={s['pass']} WARNING={s['warning']} FAIL={s['fail']} TOTAL={s['total']}")

    # Determine PASS+WARNING set for sandbox-only tickers
    sandbox_only_results = {t: report["results"].get(t, {"status": "FAIL", "critical": ["NO_DATA"], "warnings": []})
                            for t in missing_list}
    sb_status_counts = {"PASS": 0, "WARNING": 0, "FAIL": 0}
    for t, r in sandbox_only_results.items():
        sb_status_counts[r.get("status", "FAIL")] = sb_status_counts.get(r.get("status", "FAIL"), 0) + 1

    # Write missing-equities JSON
    out = {
        "summary": summary,
        "fetch_status": {
            "fetched_ok": n_fetched,
            "failed_fetch": len(failed),
            "failed_reasons_sample": dict(list(failed.items())[:20]),
        },
        "quality_status": {
            "sandbox_only_pass": sb_status_counts["PASS"],
            "sandbox_only_warning": sb_status_counts["WARNING"],
            "sandbox_only_fail": sb_status_counts["FAIL"],
            "combined_total_pass": s["pass"],
            "combined_total_warning": s["warning"],
            "combined_total_fail": s["fail"],
        },
        "missing_equities": missing_list,
        "missing_equity_status": {
            t: {
                "fetched": (t in sandbox_long["ticker"].unique() if not sandbox_long.empty else False),
                "gics_sector": filtered.loc[filtered["ticker"] == t, "gics_sector"].iloc[0] if (filtered["ticker"] == t).any() else "UNKNOWN",
                "gics_sub_industry": filtered.loc[filtered["ticker"] == t, "gics_sub_industry"].iloc[0] if (filtered["ticker"] == t).any() else "UNKNOWN",
                "quality_status": sandbox_only_results[t].get("status", "FAIL"),
            }
            for t in missing_list
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    MISSING_EQUITIES_PATH.write_text(json.dumps(out, indent=2, sort_keys=False))
    logger.info(f"Wrote {MISSING_EQUITIES_PATH}")

    elapsed = time.time() - t0
    print()
    print("=" * 60)
    print("SANDBOX STEP 1 SUMMARY")
    print("=" * 60)
    print(f"SP500 total:              {summary['sp500_total']}")
    print(f"REITs excluded:           {summary['reits_excluded']}")
    print(f"SP500 non-REIT:           {summary['sp500_after_reit_filter']}")
    print(f"Production universe:      {summary['production_universe_size']}")
    print(f"In both (overlap):        {summary['in_both']}")
    print(f"Missing equities:         {summary['missing_equities_count']}")
    print(f"  Fetched OK:             {n_fetched}")
    print(f"  Failed fetch:           {len(failed)}")
    print(f"  Quality PASS:           {sb_status_counts['PASS']}")
    print(f"  Quality WARNING:        {sb_status_counts['WARNING']}")
    print(f"  Quality FAIL:           {sb_status_counts['FAIL']}")
    print()
    print("GICS sector distribution of missing equities:")
    for sec, n in sorted(summary["missing_gics_sector_distribution"].items(), key=lambda x: -x[1]):
        print(f"  {sec:30s} {n}")
    print()
    print(f"Combined OHLCV rows:      {meta['rows']:,}")
    print(f"Combined OHLCV tickers:   {meta['n_tickers_total']}")
    print(f"Date range:               {meta['date_min']} \u2192 {meta['date_max']}")
    print(f"Elapsed:                  {elapsed:.1f}s")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
