"""CCQS V1 Sandbox — Cache path isolation.

All sandbox outputs live under data/cache/sandbox/. Production paths are
not touched.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SANDBOX_CACHE_DIR = ROOT / "data" / "cache" / "sandbox"
SANDBOX_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Inputs (written by fetch_sp500)
SP500_FILTERED_PATH = SANDBOX_CACHE_DIR / "sp500_constituents_filtered.parquet"
MISSING_EQUITIES_PATH = SANDBOX_CACHE_DIR / "sp500_missing_equities.json"
OHLCV_PATH = SANDBOX_CACHE_DIR / "ohlcv_daily.parquet"
OHLCV_META_PATH = SANDBOX_CACHE_DIR / "ohlcv_meta.json"
QUALITY_REPORT_PATH = SANDBOX_CACHE_DIR / "data_quality_report.json"

# Pipeline outputs (written by pipeline_sandbox)
FEATURES_PATH = SANDBOX_CACHE_DIR / "features.parquet"
FEATURES_META_PATH = SANDBOX_CACHE_DIR / "features_meta.json"
Z_SCORES_PATH = SANDBOX_CACHE_DIR / "z_scores.parquet"
Z_SCORES_META_PATH = SANDBOX_CACHE_DIR / "z_scores_meta.json"
COMPONENTS_PATH = SANDBOX_CACHE_DIR / "components.parquet"
COMPONENTS_META_PATH = SANDBOX_CACHE_DIR / "components_meta.json"
STATE_PATH = SANDBOX_CACHE_DIR / "state.parquet"
LEADERSHIP_PATH = SANDBOX_CACHE_DIR / "leadership.parquet"
CCQS_PATH = SANDBOX_CACHE_DIR / "ccqs.parquet"
SETUPS_PATH = SANDBOX_CACHE_DIR / "setups.parquet"
THEME_AGGREGATES_PATH = SANDBOX_CACHE_DIR / "theme_aggregates.parquet"
THEME_AGGREGATES_META_PATH = SANDBOX_CACHE_DIR / "theme_aggregates_meta.json"
SNAPSHOT_PATH = SANDBOX_CACHE_DIR / "ccqs_snapshot.parquet"
PIPELINE_META_PATH = SANDBOX_CACHE_DIR / "pipeline_meta.json"

# Validation/diagnostics
VALIDATION_REPORT_PATH = SANDBOX_CACHE_DIR / "validation_report.json"
DIAGNOSTICS_PATH = SANDBOX_CACHE_DIR / "diagnostics.json"
