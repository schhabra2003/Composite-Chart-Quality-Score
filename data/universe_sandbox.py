"""CCQS V1 Sandbox Universe — production + missing SP500 equities (non-REIT).

This module extends the production universe with SP500 tickers that are not
in `data/universe.py`. SP500-only tickers are assigned to GICS-style sandbox
baskets so they appear in theme aggregation alongside production baskets.

Sandbox baskets are prefixed `SP500_<SECTOR>` so they're trivially separable
from production baskets in the dashboard.

Reads `data/cache/sandbox/sp500_missing_equities.json` (produced by
`compute.sandbox.fetch_sp500`). If that file does not exist, sandbox is empty
and `get_sandbox_universe()` returns the production list verbatim.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from data.universe import (
    BENCHMARKS,
    CATEGORIES,
    PRIMARY_BASKETS,
    PRIMARY_BASKET_CONSTITUENTS,
    all_unique_tickers,
)

ROOT = Path(__file__).resolve().parent.parent
SANDBOX_CACHE_DIR = ROOT / "data" / "cache" / "sandbox"
MISSING_EQUITIES_PATH = SANDBOX_CACHE_DIR / "sp500_missing_equities.json"


# GICS sector → sandbox basket name. Prefixed SP500_ so they're identifiable.
GICS_TO_SANDBOX_BASKET: Dict[str, str] = {
    "Information Technology":   "SP500_INFO_TECH",
    "Health Care":              "SP500_HEALTHCARE",
    "Financials":               "SP500_FINANCIALS",
    "Consumer Discretionary":   "SP500_CONSUMER_DISC",
    "Consumer Staples":         "SP500_CONSUMER_STAPLES",
    "Industrials":              "SP500_INDUSTRIALS",
    "Energy":                   "SP500_ENERGY",
    "Materials":                "SP500_MATERIALS",
    "Utilities":                "SP500_UTILITIES",
    "Communication Services":   "SP500_COMM_SERVICES",
}

# 10 GICS-style sandbox baskets (REIT excluded).
SANDBOX_BASKETS: List[str] = list(GICS_TO_SANDBOX_BASKET.values())


def _load_missing_equities_payload() -> dict:
    """Read the JSON produced by compute.sandbox.fetch_sp500. Empty dict if missing."""
    if not MISSING_EQUITIES_PATH.exists():
        return {}
    try:
        return json.loads(MISSING_EQUITIES_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _build_sandbox_basket_constituents() -> Dict[str, List[str]]:
    """Map each GICS sandbox basket to its SP500-only ticker list (sorted)."""
    payload = _load_missing_equities_payload()
    if not payload:
        return {b: [] for b in SANDBOX_BASKETS}
    status = payload.get("missing_equity_status", {})
    out: Dict[str, List[str]] = {b: [] for b in SANDBOX_BASKETS}
    for t, meta in status.items():
        sector = meta.get("gics_sector", "")
        basket = GICS_TO_SANDBOX_BASKET.get(sector)
        if basket is None:
            continue
        # Only include tickers that have data (fetched OK) — quality status
        # is enforced downstream by the same _load_passing_tickers gate.
        if not meta.get("fetched"):
            continue
        out[basket].append(t)
    for b in out:
        out[b] = sorted(out[b])
    return out


# Compute at import time so callers get a stable view.
SANDBOX_BASKET_CONSTITUENTS: Dict[str, List[str]] = _build_sandbox_basket_constituents()


def get_sandbox_only_tickers() -> List[str]:
    """Tickers present in sandbox but not in production (SP500 missing equities)."""
    out: set[str] = set()
    for tickers in SANDBOX_BASKET_CONSTITUENTS.values():
        out.update(tickers)
    return sorted(out)


def get_production_universe() -> List[str]:
    """Production declared universe (unchanged)."""
    return all_unique_tickers()


def get_sandbox_universe() -> List[str]:
    """Combined declared universe = production ∪ SP500-only fetched tickers."""
    return sorted(set(get_production_universe()) | set(get_sandbox_only_tickers()))


def get_all_baskets_sandbox() -> List[str]:
    """All baskets visible in sandbox = production primary baskets + sandbox baskets."""
    prod_baskets = sorted(set(PRIMARY_BASKETS.values()))
    return prod_baskets + [b for b in SANDBOX_BASKETS if SANDBOX_BASKET_CONSTITUENTS.get(b)]


def get_all_basket_constituents_sandbox() -> Dict[str, List[str]]:
    """Map of basket -> tickers, combining production + sandbox baskets."""
    out: Dict[str, List[str]] = dict(PRIMARY_BASKET_CONSTITUENTS)
    for b, tickers in SANDBOX_BASKET_CONSTITUENTS.items():
        if tickers:
            out[b] = tickers
    return out


def get_sandbox_primary_basket_map() -> Dict[str, str]:
    """Map of ticker -> primary basket, including sandbox ticker assignments."""
    out: Dict[str, str] = dict(PRIMARY_BASKETS)
    for b, tickers in SANDBOX_BASKET_CONSTITUENTS.items():
        for t in tickers:
            out.setdefault(t, b)
    return out


if __name__ == "__main__":
    prod = get_production_universe()
    sand = get_sandbox_only_tickers()
    print(f"Production universe:    {len(prod)} tickers")
    print(f"Sandbox-only tickers:   {len(sand)}")
    print(f"Combined:               {len(get_sandbox_universe())}")
    print(f"Sandbox baskets active: "
          f"{sum(1 for b in SANDBOX_BASKETS if SANDBOX_BASKET_CONSTITUENTS.get(b))}/{len(SANDBOX_BASKETS)}")
    for b in SANDBOX_BASKETS:
        n = len(SANDBOX_BASKET_CONSTITUENTS.get(b, []))
        if n:
            print(f"  {b:30s} {n}")
