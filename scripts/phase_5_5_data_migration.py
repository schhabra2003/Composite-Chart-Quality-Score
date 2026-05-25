"""
Phase 5.5 Data Migration — naming standardization for cached data.

Applies the same renames as Phase C (code) to all persisted parquet caches,
snapshots, and JSON sidecars so the data layer aligns with the new vocabulary
the code now emits.

Renames:
  State values:   COILING → CONSOLIDATING, CLIMACTIC → EXHAUSTION,
                  BROKEN → DETERIORATING, MIXED → INDETERMINATE
  State columns:  p_{old} → p_{new}, p_adj_{old} → p_adj_{new}
  Setup labels:   10 renames (see SETUP_RENAMES)
  Theme columns:  pct_climactic → pct_exhaustion, pct_broken → pct_deteriorating

Preserved (intentionally NOT renamed):
  leadership_tier value DETERIORATING
  theme_class values MIXED, BROKEN_THEME, WEAKENING, STABLE
  "Distribution" in basket / metric names

Run once after Phase C code migration:
    venv/bin/python scripts/phase_5_5_data_migration.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]

STATE_VALUE_RENAMES: dict[str, str] = {
    "COILING": "CONSOLIDATING",
    "CLIMACTIC": "EXHAUSTION",
    "BROKEN": "DETERIORATING",
    "MIXED": "INDETERMINATE",
}

STATE_COLUMN_RENAMES: dict[str, str] = {}
for _old, _new in STATE_VALUE_RENAMES.items():
    STATE_COLUMN_RENAMES[f"p_{_old}"] = f"p_{_new}"
    STATE_COLUMN_RENAMES[f"p_adj_{_old}"] = f"p_adj_{_new}"

THEME_COLUMN_RENAMES: dict[str, str] = {
    "pct_climactic": "pct_exhaustion",
    "pct_broken": "pct_deteriorating",
}

SETUP_RENAMES: dict[str, str] = {
    "Healthy Trend": "Sustained Uptrend",
    "Healthy Pullback": "Routine Pullback",
    "Healthy Consolidation": "Constructive Consolidation",
    "Strong Continuation": "Trend Continuation",
    "Weak Setup": "Low-Confidence Pattern",
    "Range-Bound Coil": "Range Consolidation",
    "Mixed / Indeterminate": "Indeterminate Pattern",
    "Late Stage": "Late-Cycle Pattern",
    "Broken Downtrend": "Trend Failure",
    "Broken Distribution": "Distribution Pattern",
}


def migrate_parquet(path: Path) -> dict:
    """Open parquet, apply renames, write back. Returns a status dict."""
    if not path.exists():
        return {"path": str(path.relative_to(REPO)), "status": "MISSING"}

    df = pd.read_parquet(path)
    changes: list[str] = []

    col_renames = {c: STATE_COLUMN_RENAMES[c] for c in df.columns if c in STATE_COLUMN_RENAMES}
    if col_renames:
        df = df.rename(columns=col_renames)
        changes.append(f"state cols: {len(col_renames)} renamed")

    theme_renames = {c: THEME_COLUMN_RENAMES[c] for c in df.columns if c in THEME_COLUMN_RENAMES}
    if theme_renames:
        df = df.rename(columns=theme_renames)
        changes.append(f"theme cols: {len(theme_renames)} renamed")

    if "primary_state" in df.columns:
        before = df["primary_state"].dropna().unique().tolist()
        df["primary_state"] = df["primary_state"].replace(STATE_VALUE_RENAMES)
        renamed = [v for v in before if v in STATE_VALUE_RENAMES]
        if renamed:
            changes.append(f"primary_state: {len(renamed)} values renamed ({', '.join(sorted(renamed))})")

    if "setup" in df.columns:
        before = df["setup"].dropna().unique().tolist()
        df["setup"] = df["setup"].replace(SETUP_RENAMES)
        renamed = [v for v in before if v in SETUP_RENAMES]
        if renamed:
            changes.append(f"setup: {len(renamed)} labels renamed")

    if not changes:
        return {"path": str(path.relative_to(REPO)), "status": "NO_CHANGES", "rows": len(df)}

    df.to_parquet(path, compression="snappy")
    return {
        "path": str(path.relative_to(REPO)),
        "status": "MIGRATED",
        "rows": len(df),
        "changes": changes,
    }


def migrate_anomalies_json(path: Path) -> dict:
    """Anomalies records reference state names inside `states` arrays.

    Replace fully-quoted state tokens to avoid touching theme_class values
    (which are never bare 'BROKEN' or 'MIXED' — they are 'BROKEN_THEME' etc.).
    """
    if not path.exists():
        return {"path": str(path.relative_to(REPO)), "status": "MISSING"}

    text = path.read_text()
    orig = text
    for old, new in STATE_VALUE_RENAMES.items():
        text = text.replace(f'"{old}"', f'"{new}"')

    if text == orig:
        return {"path": str(path.relative_to(REPO)), "status": "NO_CHANGES"}

    path.write_text(text)
    return {"path": str(path.relative_to(REPO)), "status": "MIGRATED"}


def migrate_pipeline_meta_json(path: Path) -> dict:
    """Selectively migrate pipeline_meta.json.

    Touch:
      - state_distribution keys (state vocabulary)
      - top_10_setups[].setup (setup vocabulary)

    Do NOT touch:
      - theme_class_distribution (theme namespace — MIXED, BROKEN_THEME are preserved)
      - tier_distribution (leadership namespace — DETERIORATING is preserved)
    """
    if not path.exists():
        return {"path": str(path.relative_to(REPO)), "status": "MISSING"}

    data = json.loads(path.read_text())
    changes: list[str] = []

    if "state_distribution" in data:
        sd = data["state_distribution"]
        new_sd = {STATE_VALUE_RENAMES.get(k, k): v for k, v in sd.items()}
        if new_sd != sd:
            data["state_distribution"] = new_sd
            n = sum(1 for k in sd if k in STATE_VALUE_RENAMES)
            changes.append(f"state_distribution: {n} keys renamed")

    if "top_10_setups" in data and isinstance(data["top_10_setups"], list):
        n = 0
        for row in data["top_10_setups"]:
            if isinstance(row, dict) and row.get("setup") in SETUP_RENAMES:
                row["setup"] = SETUP_RENAMES[row["setup"]]
                n += 1
        if n:
            changes.append(f"top_10_setups: {n} labels renamed")

    if not changes:
        return {"path": str(path.relative_to(REPO)), "status": "NO_CHANGES"}

    path.write_text(json.dumps(data, indent=2))
    return {"path": str(path.relative_to(REPO)), "status": "MIGRATED", "changes": changes}


def main() -> None:
    cache = REPO / "data" / "cache"
    snapshot = REPO / "data" / "snapshots" / "2026-05-22"

    parquet_targets = [
        cache / "state.parquet",
        cache / "ccqs.parquet",
        cache / "setups.parquet",
        cache / "theme_aggregates.parquet",
        cache / "dashboard" / "state.parquet",
        cache / "dashboard" / "setups.parquet",
        cache / "dashboard" / "theme_aggregates.parquet",
        snapshot / "state.parquet",
        snapshot / "ccqs.parquet",
        snapshot / "setups.parquet",
        snapshot / "theme_aggregates.parquet",
        cache / "sandbox" / "state.parquet",
        cache / "sandbox" / "ccqs.parquet",
        cache / "sandbox" / "setups.parquet",
        cache / "sandbox" / "theme_aggregates.parquet",
        cache / "sp100" / "state.parquet",
        cache / "sp100" / "ccqs.parquet",
    ]

    anomalies_targets = [
        cache / "anomalies.json",
        cache / "dashboard" / "anomalies.json",
        snapshot / "anomalies.json",
    ]

    pipeline_meta_targets = [
        cache / "pipeline_meta.json",
        cache / "sandbox" / "pipeline_meta.json",
        snapshot / "pipeline_meta.json",
    ]

    bar = "=" * 70

    print(bar)
    print(f"PHASE 5.5 DATA MIGRATION  ({len(parquet_targets)} parquet + "
          f"{len(anomalies_targets) + len(pipeline_meta_targets)} JSON)")
    print(bar)
    print()

    print("--- PARQUET ---")
    for p in parquet_targets:
        r = migrate_parquet(p)
        rows = f" ({r['rows']:,} rows)" if "rows" in r else ""
        print(f"  {r['status']:<11} {r['path']}{rows}")
        for c in r.get("changes", []):
            print(f"              • {c}")
    print()

    print("--- JSON: anomalies (bulk state-token replacement) ---")
    for p in anomalies_targets:
        r = migrate_anomalies_json(p)
        print(f"  {r['status']:<11} {r['path']}")
    print()

    print("--- JSON: pipeline_meta (selective: state_distribution + top_10_setups only) ---")
    for p in pipeline_meta_targets:
        r = migrate_pipeline_meta_json(p)
        print(f"  {r['status']:<11} {r['path']}")
        for c in r.get("changes", []):
            print(f"              • {c}")
    print()
    print(bar)
    print("DONE")


if __name__ == "__main__":
    main()
