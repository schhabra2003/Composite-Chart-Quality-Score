"""
CCQS V1 — Daily Snapshot Archive (SPEC Section 13, Layer 5)

Capture the latest trading day's full pipeline output to a date-stamped folder
under `data/snapshots/YYYY-MM-DD/`. Used for:

  - Forensic recall ("what did we publish on 2026-05-22?")
  - Anomaly detection (today vs yesterday's snapshot)
  - IC tracker (forward returns vs snapshotted CCQS)

The snapshot writes per-table parquet files for the latest-date slice of:
    features, components, state, leadership, ccqs, setups
plus a copy of `theme_aggregates.parquet` filtered to the latest date,
and a `meta.json` describing the snapshot.

Run:
    python -m compute.reliability.snapshot
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from loguru import logger

from compute.loader import CACHE_DIR, LOG_DIR

SNAP_ROOT = CACHE_DIR.parent / "snapshots"

# Inputs we snapshot:
INPUT_FILES: dict[str, Path] = {
    "features": CACHE_DIR / "features.parquet",
    "components": CACHE_DIR / "components.parquet",
    "state": CACHE_DIR / "state.parquet",
    "leadership": CACHE_DIR / "leadership.parquet",
    "ccqs": CACHE_DIR / "ccqs.parquet",
    "setups": CACHE_DIR / "setups.parquet",
    "theme_aggregates": CACHE_DIR / "theme_aggregates.parquet",
}

# Auxiliary JSON files copied as-is:
AUX_FILES: list[Path] = [
    CACHE_DIR / "pipeline_meta.json",
    CACHE_DIR / "corporate_actions.json",
    CACHE_DIR / "anomalies.json",
    CACHE_DIR / "sanity_checks.json",
]

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")
logger.add(LOG_DIR / "ccqs.log", level="DEBUG", rotation="10 MB", retention="30 days")


def _filter_to_latest(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Slice df (which has a 'date' index level) to the latest date present."""
    dates = df.index.get_level_values("date")
    max_d = dates.max()
    return df.loc[dates == max_d].copy(), max_d


def take_snapshot() -> dict:
    """Write the latest-date slice of every input to `data/snapshots/YYYY-MM-DD/`."""
    SNAP_ROOT.mkdir(parents=True, exist_ok=True)

    # Determine snapshot date from ccqs (canonical pipeline output).
    if not INPUT_FILES["ccqs"].exists():
        raise FileNotFoundError(f"{INPUT_FILES['ccqs']} missing — run pipeline first")
    ccqs = pd.read_parquet(INPUT_FILES["ccqs"])
    _, snap_date = _filter_to_latest(ccqs)
    date_str = pd.Timestamp(snap_date).strftime("%Y-%m-%d")
    out_dir = SNAP_ROOT / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    rows_written: dict[str, int] = {}

    # ccqs already loaded
    ccqs_latest, _ = _filter_to_latest(ccqs)
    ccqs_latest.to_parquet(out_dir / "ccqs.parquet", compression="snappy")
    rows_written["ccqs"] = len(ccqs_latest)

    for name, path in INPUT_FILES.items():
        if name == "ccqs":
            continue
        if not path.exists():
            logger.warning(f"missing input {path} — skipping in snapshot")
            continue
        df = pd.read_parquet(path)
        if "date" in df.index.names:
            latest, _ = _filter_to_latest(df)
        elif "date" in df.columns:
            max_d = df["date"].max()
            latest = df[df["date"] == max_d].copy()
        else:
            logger.warning(f"{name} has no date axis — copying full file")
            latest = df
        latest.to_parquet(out_dir / f"{name}.parquet", compression="snappy")
        rows_written[name] = len(latest)

    aux_copied: list[str] = []
    for src in AUX_FILES:
        if src.exists():
            shutil.copy2(src, out_dir / src.name)
            aux_copied.append(src.name)

    meta = {
        "snapshot_date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows_written": rows_written,
        "aux_files_copied": aux_copied,
        "snapshot_dir": str(out_dir),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    return meta


def main() -> int:
    t0 = time.time()
    meta = take_snapshot()
    elapsed = time.time() - t0

    print()
    print("=" * 60)
    print("DAILY SNAPSHOT")
    print("=" * 60)
    print(f"  Date           : {meta['snapshot_date']}")
    print(f"  Directory      : {meta['snapshot_dir']}")
    print(f"  Tables written :")
    for k, n in meta["rows_written"].items():
        print(f"    {k:<22} {n:,} rows")
    print(f"  Aux files      : {', '.join(meta['aux_files_copied']) or 'none'}")
    print(f"Elapsed: {elapsed:.1f}s")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
