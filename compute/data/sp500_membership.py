"""Fetch S&P 500 constituents and cache to parquet.

Primary source: Wikipedia "List of S&P 500 companies" via pandas.read_html.
Fallback: GitHub mirror of the same Wikipedia table (datahub.io).

Output schema (data/cache/sp500_constituents.parquet):
    ticker (str)         — yfinance-compatible symbol (BRK.B -> BRK-B)
    company (str)        — official company name
    gics_sector (str)    — top-level GICS sector
    gics_sub_industry (str) — 4th-level GICS sub-industry
    headquarters (str)
    date_added (str)     — date added to the index
    cik (str)            — SEC CIK number (may be empty)
    founded (str)

Run:
    python -m compute.data.sp500_membership
"""
from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from loguru import logger

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = CACHE_DIR / "sp500_constituents.parquet"
META_PATH = CACHE_DIR / "sp500_constituents_meta.json"

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
DATAHUB_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/"
    "constituents.csv"
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _normalize_ticker(t: str) -> str:
    """Wikipedia uses BRK.B / BF.B; yfinance/our universe use BRK-B / BF-B."""
    return str(t).strip().upper().replace(".", "-")


def _fetch_wikipedia() -> pd.DataFrame:
    """Pull the first table on the Wikipedia SP500 page."""
    r = requests.get(WIKI_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    tables = pd.read_html(io.StringIO(r.text))
    if not tables:
        raise RuntimeError("Wikipedia returned no tables")
    df = tables[0].copy()
    # Wikipedia column names have shifted over time. Map to a canonical schema.
    rename_map = {
        "Symbol": "ticker",
        "Security": "company",
        "GICS Sector": "gics_sector",
        "GICS Sub-Industry": "gics_sub_industry",
        "GICS Sub Industry": "gics_sub_industry",
        "Headquarters Location": "headquarters",
        "Date added": "date_added",
        "Date first added": "date_added",
        "CIK": "cik",
        "Founded": "founded",
    }
    df = df.rename(columns=rename_map)
    needed = ["ticker", "company", "gics_sector", "gics_sub_industry"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise RuntimeError(f"Wikipedia table missing columns: {missing}")
    for opt in ("headquarters", "date_added", "cik", "founded"):
        if opt not in df.columns:
            df[opt] = ""
    df["ticker"] = df["ticker"].map(_normalize_ticker)
    df = df[
        ["ticker", "company", "gics_sector", "gics_sub_industry",
         "headquarters", "date_added", "cik", "founded"]
    ]
    df["cik"] = df["cik"].astype(str)
    return df.drop_duplicates(subset=["ticker"]).reset_index(drop=True)


def _fetch_datahub() -> pd.DataFrame:
    """datahub.io mirror — no GICS sub-industry, sector only."""
    r = requests.get(DATAHUB_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df = df.rename(columns={
        "Symbol": "ticker",
        "Name": "company",
        "Sector": "gics_sector",
    })
    df["ticker"] = df["ticker"].map(_normalize_ticker)
    df["gics_sub_industry"] = ""
    df["headquarters"] = ""
    df["date_added"] = ""
    df["cik"] = ""
    df["founded"] = ""
    return df[
        ["ticker", "company", "gics_sector", "gics_sub_industry",
         "headquarters", "date_added", "cik", "founded"]
    ].drop_duplicates(subset=["ticker"]).reset_index(drop=True)


def fetch_sp500(force: bool = False) -> pd.DataFrame:
    """Fetch SP500 constituents. Cache to parquet. Try Wikipedia, then datahub."""
    if not force and OUT_PATH.exists() and META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text())
            pulled_at = datetime.fromisoformat(meta["pulled_at"])
            age_h = (datetime.now(timezone.utc) - pulled_at).total_seconds() / 3600.0
            if age_h < 24:
                logger.info(f"SP500 cache fresh ({age_h:.1f}h old); using cached parquet.")
                return pd.read_parquet(OUT_PATH)
        except Exception:
            pass

    errors: list[str] = []
    df: pd.DataFrame | None = None
    for fn, name in [(_fetch_wikipedia, "Wikipedia"), (_fetch_datahub, "datahub.io")]:
        try:
            logger.info(f"Fetching SP500 from {name}...")
            df = fn()
            logger.info(f"  → got {len(df)} tickers from {name}")
            break
        except Exception as e:
            errors.append(f"{name}: {e}")
            logger.warning(f"  {name} failed: {e}")
            df = None
    if df is None or df.empty:
        raise RuntimeError("All SP500 sources failed: " + " | ".join(errors))

    df.to_parquet(OUT_PATH, compression="snappy")
    META_PATH.write_text(json.dumps({
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": int(len(df)),
        "n_sectors": int(df["gics_sector"].nunique()),
        "n_sub_industries": int(df["gics_sub_industry"].nunique()),
        "source_attempt_log": errors + ["used: " + ("Wikipedia" if errors == [] else "datahub.io")],
    }, indent=2))
    logger.info(f"Wrote {OUT_PATH}  ({len(df)} tickers)")
    return df


def load_sp500() -> pd.DataFrame:
    """Load cached SP500 parquet (fetch if missing)."""
    if not OUT_PATH.exists():
        return fetch_sp500()
    return pd.read_parquet(OUT_PATH)


def main() -> int:
    df = fetch_sp500(force=True)
    print()
    print("=" * 60)
    print("SP500 CONSTITUENTS — FETCH SUMMARY")
    print("=" * 60)
    print(f"Total tickers:       {len(df):,}")
    print(f"Unique sectors:      {df['gics_sector'].nunique()}")
    print(f"Unique sub-industries: {df['gics_sub_industry'].nunique()}")
    print()
    print("Sector distribution:")
    for s, n in df["gics_sector"].value_counts().items():
        print(f"  {s:<32s} {n:>4d}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
