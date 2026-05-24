"""CCQS V1 Sandbox — Output sanity checks.

Verifies that the sandbox pipeline produced valid outputs:
  - All expected parquet files exist
  - CCQS is in [0, 100]
  - State probabilities sum to 1.0 per (ticker, date)
  - Latest snapshot has both production and sandbox-only tickers
  - Theme aggregates include at least one SP500_ sandbox basket

Writes data/cache/sandbox/validation_report.json.

Run:
    python -m compute.sandbox.validate_sandbox
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from compute.sandbox.loader_sandbox import (
    CCQS_PATH,
    COMPONENTS_PATH,
    FEATURES_PATH,
    LEADERSHIP_PATH,
    OHLCV_PATH,
    PIPELINE_META_PATH,
    QUALITY_REPORT_PATH,
    SETUPS_PATH,
    STATE_PATH,
    THEME_AGGREGATES_PATH,
    VALIDATION_REPORT_PATH,
    Z_SCORES_PATH,
)
from data.universe_sandbox import (
    SANDBOX_BASKETS,
    get_sandbox_only_tickers,
)


REQUIRED_PARQUETS = {
    "ohlcv_daily.parquet": OHLCV_PATH,
    "features.parquet": FEATURES_PATH,
    "z_scores.parquet": Z_SCORES_PATH,
    "components.parquet": COMPONENTS_PATH,
    "state.parquet": STATE_PATH,
    "leadership.parquet": LEADERSHIP_PATH,
    "ccqs.parquet": CCQS_PATH,
    "setups.parquet": SETUPS_PATH,
    "theme_aggregates.parquet": THEME_AGGREGATES_PATH,
}


def _check_files_exist() -> tuple[bool, list[str]]:
    missing = [name for name, p in REQUIRED_PARQUETS.items() if not p.exists()]
    return (len(missing) == 0), missing


def _check_ccqs_range() -> tuple[bool, dict]:
    df = pd.read_parquet(CCQS_PATH)
    s = df["ccqs"].dropna()
    info = {
        "n_rows": int(len(s)),
        "min": float(s.min()),
        "max": float(s.max()),
        "mean": float(s.mean()),
        "p1": float(np.nanpercentile(s.to_numpy(), 1.0)),
        "p99": float(np.nanpercentile(s.to_numpy(), 99.0)),
    }
    ok = bool((s.min() >= 0.0) and (s.max() <= 100.0))
    return ok, info


def _check_state_probabilities() -> tuple[bool, dict]:
    df = pd.read_parquet(STATE_PATH)
    p_cols = [c for c in df.columns if c.startswith("p_") and not c.startswith("p_adj_")]
    if not p_cols:
        return False, {"reason": "no p_<STATE> columns found"}
    sums = df[p_cols].sum(axis=1)
    info = {
        "n_rows": int(len(sums)),
        "mean_sum": float(sums.mean()),
        "min_sum": float(sums.min()),
        "max_sum": float(sums.max()),
        "n_outside_tol": int(((sums - 1.0).abs() > 1e-6).sum()),
    }
    ok = bool(info["n_outside_tol"] == 0)
    return ok, info


def _check_universe_split() -> tuple[bool, dict]:
    """Verify both production and sandbox-only tickers were scored."""
    ccqs = pd.read_parquet(CCQS_PATH)
    latest = ccqs.index.get_level_values("date").max()
    latest_tickers = set(ccqs.xs(latest, level="date").index.unique())
    sandbox_only = set(get_sandbox_only_tickers())
    sb_in_scored = sandbox_only & latest_tickers
    prod_in_scored = latest_tickers - sandbox_only
    info = {
        "snapshot_date": str(latest.date()),
        "total_scored": int(len(latest_tickers)),
        "production_scored": int(len(prod_in_scored)),
        "sandbox_only_declared": int(len(sandbox_only)),
        "sandbox_only_scored": int(len(sb_in_scored)),
    }
    ok = bool(len(prod_in_scored) > 0 and (len(sandbox_only) == 0 or len(sb_in_scored) > 0))
    return ok, info


def _check_themes_include_sandbox() -> tuple[bool, dict]:
    df = pd.read_parquet(THEME_AGGREGATES_PATH)
    latest = df.index.get_level_values("date").max()
    latest_baskets = set(df.xs(latest, level="date").index.unique())
    sandbox_baskets_present = sorted(b for b in SANDBOX_BASKETS if b in latest_baskets)
    info = {
        "snapshot_date": str(latest.date()),
        "n_baskets_total": int(len(latest_baskets)),
        "sandbox_baskets_present": sandbox_baskets_present,
        "n_sandbox_baskets_present": int(len(sandbox_baskets_present)),
    }
    # If no SP500 missing equities were ever fetched, sandbox baskets may be
    # empty — that's allowed.
    sandbox_only = set(get_sandbox_only_tickers())
    if not sandbox_only:
        ok = True
        info["note"] = "no sandbox-only tickers; sandbox baskets not expected"
    else:
        ok = bool(len(sandbox_baskets_present) >= 1)
    return ok, info


def _check_grade_distribution() -> tuple[bool, dict]:
    df = pd.read_parquet(CCQS_PATH)
    grades = df["grade"].astype(str).value_counts(normalize=True).to_dict()
    info = {"distribution": {k: round(v, 4) for k, v in grades.items()}}
    # Sanity: expect S+A grades to be at most ~30% combined (per spec quantiles q92/q80)
    s_share = grades.get("S", 0.0)
    a_share = grades.get("A", 0.0)
    info["s_plus_a_share"] = round(s_share + a_share, 4)
    ok = bool(0.0 < info["s_plus_a_share"] <= 0.30)
    return ok, info


def run_validation() -> dict:
    logger.info("Sandbox validation: starting checks")
    results: dict[str, dict] = {}

    files_ok, missing_files = _check_files_exist()
    results["files_exist"] = {"pass": files_ok, "missing": missing_files}
    if not files_ok:
        logger.error(f"Missing required parquets: {missing_files}")

    ccqs_ok, ccqs_info = _check_ccqs_range()
    results["ccqs_range_0_100"] = {"pass": ccqs_ok, **ccqs_info}

    state_ok, state_info = _check_state_probabilities()
    results["state_probs_sum_to_1"] = {"pass": state_ok, **state_info}

    univ_ok, univ_info = _check_universe_split()
    results["universe_split"] = {"pass": univ_ok, **univ_info}

    themes_ok, themes_info = _check_themes_include_sandbox()
    results["sandbox_themes_present"] = {"pass": themes_ok, **themes_info}

    grade_ok, grade_info = _check_grade_distribution()
    results["grade_distribution_sane"] = {"pass": grade_ok, **grade_info}

    all_pass = all(v.get("pass", False) for v in results.values())
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "all_pass": all_pass,
        "checks": results,
    }
    VALIDATION_REPORT_PATH.write_text(json.dumps(report, indent=2, default=str))
    logger.info(f"Wrote {VALIDATION_REPORT_PATH}")

    # Console summary
    print()
    print("=" * 60)
    print("SANDBOX VALIDATION SUMMARY")
    print("=" * 60)
    for name, r in results.items():
        status = "PASS" if r.get("pass") else "FAIL"
        print(f"  [{status}] {name}")
    print("-" * 60)
    print(f"  OVERALL: {'PASS' if all_pass else 'FAIL'}")
    print("=" * 60)
    return report


def main() -> int:
    report = run_validation()
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
