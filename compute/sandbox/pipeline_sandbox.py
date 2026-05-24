"""CCQS V1 Sandbox — Parallel pipeline (production + SP500 missing).

METHODOLOGY LOCK: this module calls the **identical** pure functions used
by compute.pipeline. The only sandbox-specific behavior is:

  1. Universe selection: uses get_sandbox_universe() (production ∪ SP500
     missing) instead of all_unique_tickers() alone.
  2. Quality gate: reads data/cache/sandbox/data_quality_report.json
     instead of data/cache/data_quality_report.json.
  3. Basket constituents: extends PRIMARY_BASKET_CONSTITUENTS with the
     SP500_<SECTOR> sandbox baskets so themes aggregation rolls them up.
  4. Outputs go to data/cache/sandbox/ — production cache is not touched.

Implementation: temporary in-process monkey-patches around the universe
gates in compute.features. The compute/* source files are NOT modified.

Run:
    python -m compute.sandbox.pipeline_sandbox
"""
from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import data.universe as universe_mod
import compute.features as features_mod
from compute.features import compute_features
from compute.standardization import standardize_features
from compute.components import compute_components
from compute.state import classify_states
from compute.leadership import classify_leadership
from compute.ccqs import compute_ccqs
from compute.setup_classifier import classify_setups
from compute.aggregation import aggregate_themes

from data.universe_sandbox import (
    SANDBOX_BASKET_CONSTITUENTS,
    get_sandbox_universe,
    get_sandbox_only_tickers,
)

from compute.sandbox.loader_sandbox import (
    CCQS_PATH,
    COMPONENTS_PATH,
    DIAGNOSTICS_PATH,
    FEATURES_PATH,
    FEATURES_META_PATH,
    LEADERSHIP_PATH,
    OHLCV_PATH as SB_OHLCV_PATH,
    PIPELINE_META_PATH,
    QUALITY_REPORT_PATH as SB_QUALITY_PATH,
    SANDBOX_CACHE_DIR,
    SETUPS_PATH,
    STATE_PATH,
    THEME_AGGREGATES_PATH,
    THEME_AGGREGATES_META_PATH,
    Z_SCORES_PATH,
    Z_SCORES_META_PATH,
)


# ---------------------------------------------------------------------------
# Monkey-patch context (universe gates only — no methodology changes)
# ---------------------------------------------------------------------------

def _sandbox_passing_tickers() -> list[str]:
    """Read PASS+WARNING tickers from the sandbox quality report."""
    if not SB_QUALITY_PATH.exists():
        raise FileNotFoundError(
            f"Sandbox quality report not found at {SB_QUALITY_PATH}. "
            "Run `python -m compute.sandbox.fetch_sp500` first."
        )
    payload = json.loads(SB_QUALITY_PATH.read_text())
    results = payload.get("results", {})
    return sorted(
        t for t, r in results.items()
        if r.get("status") in ("PASS", "WARNING")
    )


@contextmanager
def _sandbox_universe_gates():
    """Temporarily redirect compute.features universe gates to sandbox universe.

    Saves and restores the original function references so production behavior
    is unchanged outside this context.
    """
    sb_universe = set(get_sandbox_universe())
    sb_universe_sorted = sorted(sb_universe)

    # Capture originals
    orig_all = features_mod.all_unique_tickers
    orig_load = features_mod._load_passing_tickers
    orig_constituents = dict(universe_mod.PRIMARY_BASKET_CONSTITUENTS)

    # Build extended PRIMARY_BASKET_CONSTITUENTS (mutate in place so that any
    # module already holding a reference picks up the change).
    for b, tickers in SANDBOX_BASKET_CONSTITUENTS.items():
        if tickers:
            universe_mod.PRIMARY_BASKET_CONSTITUENTS[b] = list(tickers)

    # Patch the local bindings in compute.features
    features_mod.all_unique_tickers = lambda: sb_universe_sorted
    features_mod._load_passing_tickers = _sandbox_passing_tickers

    try:
        yield sb_universe_sorted
    finally:
        # Restore originals (idempotent — production code untouched on disk)
        features_mod.all_unique_tickers = orig_all
        features_mod._load_passing_tickers = orig_load
        # Restore PRIMARY_BASKET_CONSTITUENTS by removing sandbox baskets
        for b in list(universe_mod.PRIMARY_BASKET_CONSTITUENTS.keys()):
            if b not in orig_constituents:
                del universe_mod.PRIMARY_BASKET_CONSTITUENTS[b]


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def _stage(name: str, t_start: float) -> None:
    logger.info(f"[{name}] done in {time.time() - t_start:.1f}s")


def run_sandbox_pipeline() -> dict:
    """Run the full pipeline on the sandbox universe. Writes to data/cache/sandbox/."""
    if not SB_OHLCV_PATH.exists():
        raise FileNotFoundError(
            f"Sandbox OHLCV not found at {SB_OHLCV_PATH}. "
            "Run `python -m compute.sandbox.fetch_sp500` first."
        )

    overall_t0 = time.time()
    stage_times: dict[str, float] = {}

    # Load combined OHLCV
    t = time.time()
    ohlcv = pd.read_parquet(SB_OHLCV_PATH)
    stage_times["load_ohlcv"] = time.time() - t
    logger.info(f"Loaded sandbox OHLCV {ohlcv.shape}")

    with _sandbox_universe_gates() as sb_universe:
        logger.info(f"Sandbox universe size: {len(sb_universe)} tickers")

        # ---- Features --------------------------------------------------------
        t = time.time()
        features = compute_features(ohlcv)
        features.to_parquet(FEATURES_PATH, compression="snappy")
        meta_features = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "n_rows": int(len(features)),
            "n_tickers": int(features.index.get_level_values("ticker").nunique()),
            "n_dates": int(features.index.get_level_values("date").nunique()),
            "n_features": int(features.shape[1]),
        }
        FEATURES_META_PATH.write_text(json.dumps(meta_features, indent=2))
        stage_times["features"] = time.time() - t
        _stage("features", t)

        # ---- Standardization (z-scores) -------------------------------------
        t = time.time()
        z_scores = standardize_features(features)
        z_scores.to_parquet(Z_SCORES_PATH, compression="snappy")
        meta_z = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "n_rows": int(len(z_scores)),
            "n_features": int(z_scores.shape[1]),
        }
        Z_SCORES_META_PATH.write_text(json.dumps(meta_z, indent=2))
        stage_times["z_scores"] = time.time() - t
        _stage("z_scores", t)

        # ---- Components -----------------------------------------------------
        t = time.time()
        components = compute_components(features, z_scores)
        components.to_parquet(COMPONENTS_PATH, compression="snappy")
        stage_times["components"] = time.time() - t
        _stage("components", t)

        # ---- State ----------------------------------------------------------
        t = time.time()
        state = classify_states(features)
        state.to_parquet(STATE_PATH, compression="snappy")
        stage_times["state"] = time.time() - t
        _stage("state", t)

        # ---- Leadership -----------------------------------------------------
        t = time.time()
        leadership = classify_leadership(features, components)
        leadership.to_parquet(LEADERSHIP_PATH, compression="snappy")
        stage_times["leadership"] = time.time() - t
        _stage("leadership", t)

        # ---- CCQS -----------------------------------------------------------
        t = time.time()
        ccqs = compute_ccqs(components, state)
        ccqs.to_parquet(CCQS_PATH, compression="snappy")
        stage_times["ccqs"] = time.time() - t
        _stage("ccqs", t)

        # ---- Setups ---------------------------------------------------------
        t = time.time()
        setups = classify_setups(features, state, leadership)
        setups.to_parquet(SETUPS_PATH, compression="snappy")
        stage_times["setups"] = time.time() - t
        _stage("setups", t)

        # ---- Theme aggregation ----------------------------------------------
        t = time.time()
        theme_agg = aggregate_themes(features, ccqs, state, leadership, setups, ohlcv)
        theme_agg.to_parquet(THEME_AGGREGATES_PATH, compression="snappy")
        meta_agg = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "n_themes": int(theme_agg.index.get_level_values("basket").nunique()),
            "n_rows": int(len(theme_agg)),
        }
        THEME_AGGREGATES_META_PATH.write_text(json.dumps(meta_agg, indent=2))
        stage_times["aggregation"] = time.time() - t
        _stage("aggregation", t)

    # ---- Summary meta (outside monkey-patch context — uses returned data) --
    elapsed = time.time() - overall_t0
    grade_dist = ccqs["grade"].astype(str).value_counts(normalize=True).to_dict()
    state_dist = state["primary_state"].astype(str).value_counts(normalize=True).to_dict()
    tier_dist = leadership["leadership_tier"].astype(str).value_counts(normalize=True).to_dict()
    setup_dist = setups["setup"].astype(str).value_counts(normalize=True).to_dict()
    theme_dist = theme_agg["theme_class"].astype(str).value_counts(normalize=True).to_dict()

    sandbox_only = set(get_sandbox_only_tickers())
    ccqs_ticker_idx = ccqs.index.get_level_values("ticker")
    sb_in_ccqs = set(ccqs_ticker_idx.unique()) & sandbox_only

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "stage_times_seconds": {k: round(v, 2) for k, v in stage_times.items()},
        "n_rows": int(len(features)),
        "n_tickers_total": int(features.index.get_level_values("ticker").nunique()),
        "n_tickers_production": int(len(set(features.index.get_level_values("ticker").unique()) - sandbox_only)),
        "n_tickers_sandbox_only": int(len(sb_in_ccqs)),
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
    }
    PIPELINE_META_PATH.write_text(json.dumps(meta, indent=2, default=str))

    # ---- Lightweight diagnostics for the dashboard ------------------------
    latest_date = ccqs.index.get_level_values("date").max()
    latest_ccqs = ccqs.xs(latest_date, level="date")
    sb_latest = latest_ccqs.loc[latest_ccqs.index.isin(sandbox_only)] if not latest_ccqs.empty else latest_ccqs.iloc[0:0]
    prod_latest = latest_ccqs.loc[~latest_ccqs.index.isin(sandbox_only)] if not latest_ccqs.empty else latest_ccqs.iloc[0:0]

    diag = {
        "snapshot_date": str(latest_date.date()),
        "sandbox_only_tickers_in_universe": int(len(sandbox_only)),
        "sandbox_only_tickers_scored_today": int(len(sb_latest)),
        "production_tickers_scored_today": int(len(prod_latest)),
        "total_tickers_scored_today": int(len(latest_ccqs)),
        "ccqs_latest": {
            "production_mean": float(prod_latest["ccqs"].mean()) if not prod_latest.empty else None,
            "production_median": float(prod_latest["ccqs"].median()) if not prod_latest.empty else None,
            "sandbox_only_mean": float(sb_latest["ccqs"].mean()) if not sb_latest.empty else None,
            "sandbox_only_median": float(sb_latest["ccqs"].median()) if not sb_latest.empty else None,
        },
        "sandbox_only_grade_distribution": (
            sb_latest["grade"].astype(str).value_counts(normalize=True).round(4).to_dict()
            if not sb_latest.empty else {}
        ),
    }
    DIAGNOSTICS_PATH.write_text(json.dumps(diag, indent=2))

    # ---- Print headline ---------------------------------------------------
    print()
    print("=" * 72)
    print("CCQS SANDBOX PIPELINE — SUMMARY")
    print("=" * 72)
    print(f"  Rows:                       {meta['n_rows']:,}")
    print(f"  Tickers total:              {meta['n_tickers_total']}")
    print(f"    of which production:      {meta['n_tickers_production']}")
    print(f"    of which sandbox-only:    {meta['n_tickers_sandbox_only']}")
    print(f"  Dates:                      {meta['n_dates']}")
    print(f"  Themes (incl. sandbox):     {meta['n_themes']}")
    print(f"  Total runtime:              {elapsed:.1f}s")
    print()
    print("  Stage timings:")
    for k, v in meta["stage_times_seconds"].items():
        print(f"    {k:<24}{v:>6.1f}s")
    print()
    print(f"  CCQS mean / median:         {meta['ccqs_mean']:.2f} / {meta['ccqs_median']:.2f}")
    print(f"  CCQS p1 / p99:              {meta['ccqs_p1']:.2f} / {meta['ccqs_p99']:.2f}")
    if diag["ccqs_latest"]["production_mean"] is not None:
        print(f"  Latest production CCQS mean:    {diag['ccqs_latest']['production_mean']:.2f}")
    if diag["ccqs_latest"]["sandbox_only_mean"] is not None:
        print(f"  Latest sandbox-only CCQS mean:  {diag['ccqs_latest']['sandbox_only_mean']:.2f}")
    print("=" * 72)

    return meta


def main() -> int:
    try:
        run_sandbox_pipeline()
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
