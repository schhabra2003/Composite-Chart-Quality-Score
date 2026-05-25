"""
CCQS V1 — Anomaly Detection (SPEC Section 13, Layer 3)

Scans the most recent rolling window for per-ticker CCQS / grade / state
movements that look like outliers vs the ticker's own recent history. Helps
operators triage rows that may reflect a data-quality issue rather than a
genuine signal.

Anomalies detected (per ticker, evaluated on the latest date):

1.  CCQS jumps   — |CCQS(t) - CCQS(t-1)| > 25, or 5-day rolling z-score on
    CCQS exceeds ±2.5.
2.  Grade jumps  — grade transition skipping ≥ 2 tiers (e.g. D→B, S→C).
3.  State flips  — `primary_state` changed in 2 of the last 3 days and the
    states involved are not adjacent (TRENDING↔DETERIORATING,
    CONSOLIDATING↔EXHAUSTION).

Output: `data/cache/anomalies.json` — sorted by severity (CCQS jump > grade
jump > state flip).

Run:
    python -m compute.reliability.anomaly_detection
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

CCQS_PATH = CACHE_DIR / "ccqs.parquet"
STATE_PATH = CACHE_DIR / "state.parquet"
OUT_PATH = CACHE_DIR / "anomalies.json"

CCQS_JUMP_ABS = 25.0
CCQS_Z_THRESHOLD = 2.5
ROLL_WINDOW = 5

# Grade ordering (S best → D worst)
GRADE_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}

# Pairs of states considered "incompatible" (non-adjacent in regime space).
_NON_ADJACENT_PAIRS = {
    frozenset({"TRENDING", "DETERIORATING"}),
    frozenset({"CONSOLIDATING", "EXHAUSTION"}),
    frozenset({"TRENDING", "EXHAUSTION"}),  # also extreme jump
}

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")
logger.add(LOG_DIR / "ccqs.log", level="DEBUG", rotation="10 MB", retention="30 days")


def _ccqs_anomalies(ccqs: pd.DataFrame) -> list[dict]:
    """Detect ccqs jump + rolling-z anomalies on the latest date per ticker."""
    df = ccqs.sort_index()
    df = df.reset_index()
    df = df.sort_values(["ticker", "date"])
    df["ccqs"] = df["ccqs"].astype(float)

    grp = df.groupby("ticker", sort=False)
    df["ccqs_prev"] = grp["ccqs"].shift(1)
    df["abs_jump"] = (df["ccqs"] - df["ccqs_prev"]).abs()
    df["roll_mean"] = grp["ccqs"].transform(
        lambda s: s.rolling(ROLL_WINDOW, min_periods=ROLL_WINDOW).mean().shift(1)
    )
    df["roll_std"] = grp["ccqs"].transform(
        lambda s: s.rolling(ROLL_WINDOW, min_periods=ROLL_WINDOW).std().shift(1)
    )
    df["roll_z"] = (df["ccqs"] - df["roll_mean"]) / df["roll_std"].replace(0, np.nan)

    last_dt = df["date"].max()
    latest = df[df["date"] == last_dt].copy()

    anomalies: list[dict] = []
    big_jump = (latest["abs_jump"] > CCQS_JUMP_ABS) & latest["abs_jump"].notna()
    z_outlier = (latest["roll_z"].abs() > CCQS_Z_THRESHOLD) & latest["roll_z"].notna()

    for _, row in latest[big_jump | z_outlier].iterrows():
        anomalies.append(
            {
                "ticker": row["ticker"],
                "date": row["date"].strftime("%Y-%m-%d"),
                "type": "ccqs_jump",
                "ccqs": round(float(row["ccqs"]), 2),
                "ccqs_prev": (
                    None if pd.isna(row["ccqs_prev"]) else round(float(row["ccqs_prev"]), 2)
                ),
                "abs_jump": (
                    None if pd.isna(row["abs_jump"]) else round(float(row["abs_jump"]), 2)
                ),
                "roll_z": (
                    None if pd.isna(row["roll_z"]) else round(float(row["roll_z"]), 2)
                ),
                "severity": "high"
                if (not pd.isna(row["abs_jump"]) and row["abs_jump"] > CCQS_JUMP_ABS)
                else "medium",
            }
        )
    return anomalies


def _grade_anomalies(ccqs: pd.DataFrame) -> list[dict]:
    df = ccqs.sort_index().reset_index().sort_values(["ticker", "date"])
    df["grade"] = df["grade"].astype(str)
    df["grade_rank"] = df["grade"].map(GRADE_ORDER)
    df["grade_prev"] = df.groupby("ticker", sort=False)["grade_rank"].shift(1)
    df["grade_gap"] = (df["grade_rank"] - df["grade_prev"]).abs()

    last_dt = df["date"].max()
    latest = df[df["date"] == last_dt].copy()

    out: list[dict] = []
    for _, row in latest.iterrows():
        if pd.isna(row["grade_gap"]) or row["grade_gap"] < 2:
            continue
        prev_letter = next(
            (k for k, v in GRADE_ORDER.items() if v == int(row["grade_prev"])), None
        )
        out.append(
            {
                "ticker": row["ticker"],
                "date": row["date"].strftime("%Y-%m-%d"),
                "type": "grade_jump",
                "grade_prev": prev_letter,
                "grade": row["grade"],
                "gap": int(row["grade_gap"]),
                "severity": "high" if row["grade_gap"] >= 3 else "medium",
            }
        )
    return out


def _state_anomalies(state: pd.DataFrame) -> list[dict]:
    df = state[["primary_state"]].copy().sort_index()
    df = df.reset_index().sort_values(["ticker", "date"])
    df["state"] = df["primary_state"].astype(str)
    grp = df.groupby("ticker", sort=False)
    df["state_t1"] = grp["state"].shift(1)
    df["state_t2"] = grp["state"].shift(2)

    last_dt = df["date"].max()
    latest = df[df["date"] == last_dt].copy()

    out: list[dict] = []
    for _, row in latest.iterrows():
        s0, s1, s2 = row["state"], row["state_t1"], row["state_t2"]
        if pd.isna(s1) or pd.isna(s2):
            continue
        n_changes = int(s0 != s1) + int(s1 != s2)
        if n_changes < 2:
            continue
        # Non-adjacent transition in last 2 days?
        non_adjacent = (
            frozenset({s0, s1}) in _NON_ADJACENT_PAIRS
            or frozenset({s1, s2}) in _NON_ADJACENT_PAIRS
        )
        if not non_adjacent:
            continue
        out.append(
            {
                "ticker": row["ticker"],
                "date": row["date"].strftime("%Y-%m-%d"),
                "type": "state_flip",
                "states": [s2, s1, s0],
                "severity": "medium",
            }
        )
    return out


def detect_anomalies(ccqs: pd.DataFrame, state: pd.DataFrame) -> dict:
    ccqs_anoms = _ccqs_anomalies(ccqs)
    grade_anoms = _grade_anomalies(ccqs)
    state_anoms = _state_anomalies(state)

    sev_order = {"high": 0, "medium": 1, "low": 2}
    type_order = {"ccqs_jump": 0, "grade_jump": 1, "state_flip": 2}
    all_anoms = ccqs_anoms + grade_anoms + state_anoms
    all_anoms.sort(key=lambda a: (sev_order.get(a["severity"], 9), type_order.get(a["type"], 9), a["ticker"]))

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_ccqs_jumps": len(ccqs_anoms),
        "n_grade_jumps": len(grade_anoms),
        "n_state_flips": len(state_anoms),
        "n_total": len(all_anoms),
        "n_high_severity": sum(1 for a in all_anoms if a["severity"] == "high"),
    }
    return {"summary": summary, "anomalies": all_anoms}


def main() -> int:
    t0 = time.time()
    if not CCQS_PATH.exists() or not STATE_PATH.exists():
        logger.error("Missing inputs. Run earlier pipeline stages first.")
        return 1
    ccqs = pd.read_parquet(CCQS_PATH)
    state = pd.read_parquet(STATE_PATH)
    logger.info(f"Loaded ccqs {ccqs.shape}, state {state.shape}")

    out = detect_anomalies(ccqs, state)
    elapsed = time.time() - t0
    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))

    s = out["summary"]
    print()
    print("=" * 60)
    print("ANOMALY DETECTION (latest date)")
    print("=" * 60)
    print(f"  CCQS jumps         : {s['n_ccqs_jumps']}")
    print(f"  Grade jumps        : {s['n_grade_jumps']}")
    print(f"  State flips        : {s['n_state_flips']}")
    print(f"  Total anomalies    : {s['n_total']}")
    print(f"  High severity      : {s['n_high_severity']}")
    print(f"Elapsed: {elapsed:.1f}s")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
