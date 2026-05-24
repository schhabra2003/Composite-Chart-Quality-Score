"""Build a slim dashboard cache for shipping with the Streamlit app.

Full cache at data/cache/*.parquet is 6GB and contains pipeline intermediates
that the dashboard never touches. This script writes a compact subset to
data/cache/dashboard/ (~20-30MB) suitable for committing to git so Streamlit
Cloud deploys with data already in place.

Schema is identical to the full files — same MultiIndex (date, ticker) and the
column subset the dashboard reads. The loader will pick this up first if
present (see app/utils/data_loader.py).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "cache"
DST = ROOT / "data" / "cache" / "dashboard"


# Columns the dashboard actually reads (see app/utils/data_loader.py).
HISTORY_COLS = {
    "ccqs.parquet":       ["ccqs", "grade"],
    "state.parquet":      ["primary_state", "state_confidence"],
    "leadership.parquet": ["leadership_tier"],
    "setups.parquet":     ["setup"],
}

LATEST_ONLY_COLS = {
    "features.parquet": [
        "rs_rating_spy", "information_ratio_252d",
        "pct_ma_50", "pct_ma_200", "pct_from_52w_high",
        "adx_14", "rsi_14", "realized_vol_60",
        "within_basket_z_21d", "distribution_days_25",
    ],
    "components.parquet": [
        "s_rs", "s_rs_leadership", "s_rsl", "s_trend_slope",
        "s_structure", "s_mtf", "s_extension", "s_climax",
        "s_demand", "s_momentum",
    ],
}

LATEST_ONLY_ALL_COLS = ["theme_aggregates.parquet"]

COPY_AS_IS = ["benchmarks.parquet"]

JSON_FILES = ["oos_ic_summary.json", "sanity_checks.json", "anomalies.json"]


def _read(name: str) -> pd.DataFrame:
    p = SRC / name
    if not p.exists():
        print(f"  skip {name} (missing)")
        return pd.DataFrame()
    return pd.read_parquet(p)


def _write(df: pd.DataFrame, name: str) -> None:
    out = DST / name
    df.to_parquet(out, compression="zstd")
    print(f"  wrote {name:42s} rows={len(df):>10,} size={out.stat().st_size / 1024:.1f}KB")


def _latest_date(df: pd.DataFrame):
    return df.index.get_level_values("date").max()


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"No source cache at {SRC}")
    DST.mkdir(parents=True, exist_ok=True)

    print(f"Building slim dashboard cache → {DST}")

    # 1. History-preserving slim files (full date range, column subset).
    for name, cols in HISTORY_COLS.items():
        df = _read(name)
        if df.empty:
            continue
        keep = [c for c in cols if c in df.columns]
        _write(df[keep], name)

    # 2. Latest-snapshot files with a column subset.
    for name, cols in LATEST_ONLY_COLS.items():
        df = _read(name)
        if df.empty:
            continue
        latest = _latest_date(df)
        slim = df.xs(latest, level="date", drop_level=False)
        keep = [c for c in cols if c in slim.columns]
        _write(slim[keep], name)

    # 3. Latest-snapshot files keeping all columns (theme aggregates etc.).
    for name in LATEST_ONLY_ALL_COLS:
        df = _read(name)
        if df.empty:
            continue
        latest = _latest_date(df)
        slim = df.xs(latest, level="date", drop_level=False)
        _write(slim, name)

    # 4. Copy-as-is small files.
    for name in COPY_AS_IS:
        src = SRC / name
        if not src.exists():
            print(f"  skip {name} (missing)")
            continue
        shutil.copy2(src, DST / name)
        print(f"  copied {name}")

    # 5. JSON sidecars.
    for name in JSON_FILES:
        src = SRC / name
        if not src.exists():
            print(f"  skip {name} (missing)")
            continue
        shutil.copy2(src, DST / name)
        print(f"  copied {name}")

    total = sum(f.stat().st_size for f in DST.glob("*"))
    print(f"\nTotal dashboard cache: {total / 1024 / 1024:.2f} MB")


if __name__ == "__main__":
    main()
