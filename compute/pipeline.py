"""
CCQS V1 — End-to-End Pipeline (Phase 4 orchestrator)

Chains:
    features.parquet + z_scores.parquet
        → components.parquet
        → state.parquet
        → leadership.parquet
        → ccqs.parquet
        → setups.parquet
        → theme_aggregates.parquet      (Phase 4: theme rollup)
        → corporate_actions.json        (Phase 4: reliability)
        → anomalies.json                (Phase 4: reliability)
        → sanity_checks.json            (Phase 4: reliability)
        → ic_tracker.json               (Phase 4: reliability)
        → snapshots/YYYY-MM-DD/         (Phase 4: snapshot archive)

Assumes Phase 1/2 outputs (features.parquet, z_scores.parquet) are already on
disk. Run `python -m compute.features` and `python -m compute.standardization`
first if not.

Run:
    python -m compute.pipeline
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
from data.universe import BENCHMARKS
from compute.components import compute_components, COMPONENT_COLS, COMPONENTS_PATH
from compute.state import classify_states, STATES, STATE_PATH
from compute.leadership import classify_leadership, TIERS, LEADERSHIP_PATH
from compute.ccqs import compute_ccqs, CCQS_PATH
from compute.setup_classifier import classify_setups, SETUP_LABELS, SETUP_PATH
from compute.aggregation import aggregate_themes, AGG_PATH, AGG_META_PATH, THEME_TIERS
from compute.reliability.corporate_actions import detect_corporate_actions, OUT_PATH as CA_PATH
from compute.reliability.anomaly_detection import detect_anomalies, OUT_PATH as ANOM_PATH
from compute.reliability.sanity_checks import run_sanity_checks, OUT_PATH as SANITY_PATH
from compute.reliability.ic_tracker import compute_ic, OUT_PATH as IC_PATH
from compute.reliability.snapshot import take_snapshot

FEATURES_PATH = CACHE_DIR / "features.parquet"
Z_SCORES_PATH = CACHE_DIR / "z_scores.parquet"
OHLCV_PATH = CACHE_DIR / "ohlcv_daily.parquet"
BENCHMARKS_PATH = CACHE_DIR / "benchmarks.parquet"
PIPELINE_META_PATH = CACHE_DIR / "pipeline_meta.json"

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")
logger.add(LOG_DIR / "ccqs.log", level="DEBUG", rotation="10 MB", retention="30 days")


def _stage(name: str, t_start: float) -> None:
    logger.info(f"[{name}] done in {time.time() - t_start:.1f}s")


def run_pipeline() -> dict:
    """Run all Phase 3 + Phase 4 stages end-to-end. Returns timing+summary dict."""
    if not FEATURES_PATH.exists() or not Z_SCORES_PATH.exists():
        raise FileNotFoundError(
            "Missing Phase 1/2 outputs. Run `python -m compute.features` and "
            "`python -m compute.standardization` first."
        )

    overall_t0 = time.time()
    stage_times: dict[str, float] = {}

    # ---- Load inputs ------------------------------------------------------
    t = time.time()
    features = pd.read_parquet(FEATURES_PATH)
    z_scores = pd.read_parquet(Z_SCORES_PATH)
    ohlcv = pd.read_parquet(OHLCV_PATH)
    stage_times["load_inputs"] = time.time() - t
    logger.info(
        f"Loaded features {features.shape}, z_scores {z_scores.shape}, "
        f"ohlcv {ohlcv.shape} in {stage_times['load_inputs']:.1f}s"
    )

    # ---- Carve out benchmarks OHLCV (SPY/QQQ) -----------------------------
    # Benchmarks are excluded from CCQS scoring but their OHLCV is persisted
    # separately for chart overlays and downstream context.
    t = time.time()
    if "ticker" in ohlcv.index.names:
        bench_mask = ohlcv.index.get_level_values("ticker").isin(BENCHMARKS)
        bench_ohlcv = ohlcv.loc[bench_mask]
    else:
        bench_ohlcv = ohlcv[ohlcv["ticker"].isin(BENCHMARKS)] if "ticker" in ohlcv.columns else ohlcv.iloc[0:0]
    bench_ohlcv.to_parquet(BENCHMARKS_PATH, compression="snappy")
    stage_times["benchmarks_carveout"] = time.time() - t
    logger.info(
        f"[benchmarks_carveout] wrote {len(bench_ohlcv):,} rows for "
        f"{sorted(BENCHMARKS)} -> {BENCHMARKS_PATH.name}"
    )

    # ---- Components -------------------------------------------------------
    t = time.time()
    components = compute_components(features, z_scores)
    components.to_parquet(COMPONENTS_PATH, compression="snappy")
    stage_times["components"] = time.time() - t
    _stage("components", t)

    # ---- State ------------------------------------------------------------
    t = time.time()
    state = classify_states(features)
    state.to_parquet(STATE_PATH, compression="snappy")
    stage_times["state"] = time.time() - t
    _stage("state", t)

    # ---- Leadership -------------------------------------------------------
    t = time.time()
    leadership = classify_leadership(features, components)
    leadership.to_parquet(LEADERSHIP_PATH, compression="snappy")
    stage_times["leadership"] = time.time() - t
    _stage("leadership", t)

    # ---- CCQS -------------------------------------------------------------
    t = time.time()
    ccqs = compute_ccqs(components, state)
    ccqs.to_parquet(CCQS_PATH, compression="snappy")
    stage_times["ccqs"] = time.time() - t
    _stage("ccqs", t)

    # ---- Setups -----------------------------------------------------------
    # Phase 25 — replaced the legacy 27-label classify_setups() with the
    # 12-label chart-evocative cascade classify_setup_v2(). Pure display-layer
    # change; CCQS / state / tier / regime / TV reference values unchanged.
    # The legacy classifier remains in compute/setup_classifier.py for
    # reference; this is the only call site that flipped over.
    t = time.time()
    from compute.setup_classifier_v2 import classify_setup_v2
    setups = classify_setup_v2(features)
    setups.to_parquet(SETUP_PATH, compression="snappy")
    stage_times["setups"] = time.time() - t
    _stage("setups", t)

    # ---- Theme aggregation (Phase 4) --------------------------------------
    t = time.time()
    theme_agg = aggregate_themes(features, ccqs, state, leadership, setups, ohlcv)
    theme_agg.to_parquet(AGG_PATH, compression="snappy")
    stage_times["aggregation"] = time.time() - t
    _stage("aggregation", t)

    # ---- Corporate actions (Phase 4) --------------------------------------
    t = time.time()
    ca = detect_corporate_actions(ohlcv)
    CA_PATH.write_text(json.dumps(ca, indent=2, default=str))
    stage_times["corporate_actions"] = time.time() - t
    _stage("corporate_actions", t)

    # ---- Anomaly detection (Phase 4) --------------------------------------
    t = time.time()
    anomalies = detect_anomalies(ccqs, state)
    ANOM_PATH.write_text(json.dumps(anomalies, indent=2, default=str))
    stage_times["anomaly_detection"] = time.time() - t
    _stage("anomaly_detection", t)

    # ---- Sanity checks (Phase 4) ------------------------------------------
    t = time.time()
    sanity = run_sanity_checks()
    SANITY_PATH.write_text(json.dumps(sanity, indent=2, default=str))
    stage_times["sanity_checks"] = time.time() - t
    _stage("sanity_checks", t)

    # ---- IC tracker (Phase 4) ---------------------------------------------
    t = time.time()
    ic = compute_ic(ccqs, ohlcv)
    IC_PATH.write_text(json.dumps(ic, indent=2, default=str))
    stage_times["ic_tracker"] = time.time() - t
    _stage("ic_tracker", t)

    elapsed = time.time() - overall_t0

    # ---- Summary metrics --------------------------------------------------
    grade_dist = ccqs["grade"].astype(str).value_counts(normalize=True).to_dict()
    state_dist = state["primary_state"].astype(str).value_counts(normalize=True).to_dict()
    tier_dist = leadership["leadership_tier"].astype(str).value_counts(normalize=True).to_dict()
    setup_dist = setups["setup"].astype(str).value_counts(normalize=True).to_dict()
    theme_dist = theme_agg["theme_class"].astype(str).value_counts(normalize=True).to_dict()

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "stage_times_seconds": {k: round(v, 2) for k, v in stage_times.items()},
        "n_rows": int(len(features)),
        "n_tickers": int(features.index.get_level_values("ticker").nunique()),
        "n_dates": int(features.index.get_level_values("date").nunique()),
        "n_themes": int(theme_agg.index.get_level_values("basket").nunique()),
        "ccqs_mean": float(ccqs["ccqs"].mean()),
        "ccqs_median": float(ccqs["ccqs"].median()),
        "ccqs_p1": float(np.nanpercentile(ccqs["ccqs"].to_numpy(), 1.0)),
        "ccqs_p99": float(np.nanpercentile(ccqs["ccqs"].to_numpy(), 99.0)),
        "grade_distribution": {k: round(v, 4) for k, v in grade_dist.items()},
        "state_distribution": {k: round(v, 4) for k, v in state_dist.items()},
        "tier_distribution": {k: round(v, 4) for k, v in tier_dist.items()},
        "theme_class_distribution": {k: round(v, 4) for k, v in theme_dist.items()},
        "top_10_setups": [
            {"setup": k, "share": round(v, 4)}
            for k, v in sorted(setup_dist.items(), key=lambda kv: -kv[1])[:10]
        ],
        "reliability": {
            "corporate_actions_summary": ca["summary"],
            "anomalies_summary": anomalies["summary"],
            "sanity_checks_passed": sanity["passed"],
            "sanity_checks_failed": sanity["n_failed"],
            "ic_summary": ic["summary"],
        },
    }
    PIPELINE_META_PATH.write_text(json.dumps(meta, indent=2, default=str))

    # ---- Snapshot (Phase 4, runs after pipeline_meta is written) ----------
    t = time.time()
    snap = take_snapshot()
    stage_times["snapshot"] = time.time() - t
    _stage("snapshot", t)
    meta["stage_times_seconds"]["snapshot"] = round(stage_times["snapshot"], 2)
    meta["snapshot_dir"] = snap["snapshot_dir"]
    meta["snapshot_date"] = snap["snapshot_date"]
    meta["elapsed_seconds"] = round(time.time() - overall_t0, 2)
    PIPELINE_META_PATH.write_text(json.dumps(meta, indent=2, default=str))

    elapsed = meta["elapsed_seconds"]

    # ---- Print headline ---------------------------------------------------
    print()
    print("=" * 72)
    print("CCQS PIPELINE — PHASE 4 SUMMARY")
    print("=" * 72)
    print(f"  Rows:               {meta['n_rows']:,}")
    print(f"  Tickers:            {meta['n_tickers']}")
    print(f"  Dates:              {meta['n_dates']}")
    print(f"  Themes:             {meta['n_themes']}")
    print(f"  Total runtime:      {elapsed:.1f}s")
    print()
    print("  Stage timings:")
    for k, v in meta["stage_times_seconds"].items():
        print(f"    {k:<20}{v:>6.1f}s")
    print()
    print(f"  CCQS mean / median: {meta['ccqs_mean']:.2f} / {meta['ccqs_median']:.2f}")
    print(f"  CCQS p1 / p99:      {meta['ccqs_p1']:.2f} / {meta['ccqs_p99']:.2f}")
    print()
    print("  Grade distribution:")
    for g in ["S", "A", "B", "C", "D"]:
        pct = grade_dist.get(g, 0.0) * 100
        print(f"    Grade {g}: {pct:6.2f}%")
    print()
    print("  State distribution:")
    for s in STATES:
        pct = state_dist.get(s, 0.0) * 100
        print(f"    {s:<12} {pct:6.2f}%")
    print()
    print("  Leadership tier distribution:")
    for t_label in TIERS:
        pct = tier_dist.get(t_label, 0.0) * 100
        print(f"    {t_label:<20} {pct:6.2f}%")
    print()
    print("  Theme class distribution:")
    for t_label in THEME_TIERS:
        pct = theme_dist.get(t_label, 0.0) * 100
        print(f"    {t_label:<20} {pct:6.2f}%")
    print()
    print("  Top 10 setups:")
    for label, share in sorted(setup_dist.items(), key=lambda kv: -kv[1])[:10]:
        print(f"    {label:<40} {share*100:6.2f}%")
    print()
    print("  Reliability:")
    print(f"    sanity_checks   : {sanity['n_checks']-sanity['n_failed']}/{sanity['n_checks']} passed")
    print(f"    anomalies       : {anomalies['summary']['n_total']} total ({anomalies['summary']['n_high_severity']} high)")
    print(f"    corporate actions: {ca['summary']['total_splits']} splits / {ca['summary']['total_spinoffs']} spinoffs / {ca['summary']['total_halts']} halts")
    print(f"    IC_5d mean      : {ic['summary']['ic_5d_mean']}")
    print(f"    IC_60d mean     : {ic['summary'].get('ic_60d_mean')}")
    print(f"    IC_126d mean    : {ic['summary'].get('ic_126d_mean')}")
    print(f"    snapshot dir    : {meta['snapshot_dir']}")
    print("=" * 72)

    return meta


def main() -> int:
    try:
        run_pipeline()
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
