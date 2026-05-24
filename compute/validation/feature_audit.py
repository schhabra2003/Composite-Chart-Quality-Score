"""
CCQS V1 — Feature-Level OOS Audit (Phase X.2)

Consumes the rolling-window diagnostics produced by
`compute.validation.oos_evaluation` and answers four questions:

  1. For each forward-return horizon, which features carry positive OOS IC,
     which carry negative OOS IC, and which look in-sample-overfit?
  2. Across all 6 horizons, which features are universally good?
  3. Which features only contribute at specific horizons?
  4. Which features are noise candidates (no OOS IC at any horizon)?
  5. How do the 10 components rank by aggregate OOS signal?

Output
------
    data/cache/feature_audit_summary.json — machine-readable audit
    stdout                                 — clean text summary

Run:
    python -m compute.validation.feature_audit
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

DIAG_PATH = CACHE_DIR / "oos_ic_diagnostics.parquet"
SUMMARY_PATH = CACHE_DIR / "oos_ic_summary.json"
AUDIT_PATH = CACHE_DIR / "feature_audit_summary.json"

HORIZONS = [1, 5, 20, 60, 126, 252]
TOP_N = 20
BOTTOM_N = 20

# Heuristics
MIN_WINDOWS_FOR_RANKING = 10     # drop scores with very few windows
OVERFIT_IS_THRESHOLD = 0.015     # IS IC needs to be ≥ this to even qualify
OVERFIT_GAP_THRESHOLD = 0.010    # IS − OOS gap ≥ this counts as overfit
NOISE_OOS_THRESHOLD = 0.005      # max |OOS IC| across horizons below this = noise
UNIVERSAL_MIN_HORIZONS = 3       # appears in top 20 at ≥ this many horizons

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")
logger.add(LOG_DIR / "ccqs.log", level="DEBUG", rotation="10 MB", retention="30 days")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _per_score_per_horizon(diag: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per (score_name, score_type, horizon)."""
    def _agg(g: pd.DataFrame) -> pd.Series:
        oos = g["oos_ic"].dropna()
        is_ = g["is_ic"].dropna()
        n = len(oos)
        oos_mean = float(oos.mean()) if n else np.nan
        oos_std = float(oos.std(ddof=1)) if n > 1 else np.nan
        t_stat = (oos_mean / (oos_std / np.sqrt(n))) if (n > 1 and oos_std and oos_std > 0) else np.nan
        return pd.Series({
            "n_windows": n,
            "oos_ic_mean": oos_mean,
            "oos_ic_std": oos_std,
            "oos_t_stat": t_stat,
            "oos_hit_rate": float((oos > 0).mean()) if n else np.nan,
            "is_ic_mean": float(is_.mean()) if len(is_) else np.nan,
            "is_minus_oos": (float(is_.mean()) - oos_mean) if (n and len(is_)) else np.nan,
        })
    out = (
        diag.groupby(["score_type", "score_name", "horizon"])
            .apply(_agg)
            .reset_index()
    )
    return out


def _round(v) -> float | None:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return None
    return round(float(v), 4)


def _to_records(df: pd.DataFrame) -> list[dict]:
    cols = ["score_name", "oos_ic_mean", "oos_t_stat", "oos_hit_rate",
            "is_ic_mean", "is_minus_oos", "n_windows"]
    out = []
    for _, r in df[cols].iterrows():
        out.append({
            "name": r["score_name"],
            "oos_ic": _round(r["oos_ic_mean"]),
            "t_stat": _round(r["oos_t_stat"]),
            "hit_rate": _round(r["oos_hit_rate"]),
            "is_ic": _round(r["is_ic_mean"]),
            "is_minus_oos": _round(r["is_minus_oos"]),
            "n_windows": int(r["n_windows"]),
        })
    return out


# ---------------------------------------------------------------------------
# Per-horizon tables
# ---------------------------------------------------------------------------

def _per_horizon_tables(per_h: pd.DataFrame, score_type: str) -> dict[int, dict]:
    """Top, bottom, overfit for each horizon, restricted to one score_type."""
    out: dict[int, dict] = {}
    sub_type = per_h[per_h["score_type"] == score_type]
    for h in HORIZONS:
        sub = sub_type[
            (sub_type["horizon"] == h) & (sub_type["n_windows"] >= MIN_WINDOWS_FOR_RANKING)
        ].copy()

        top = sub.sort_values("oos_ic_mean", ascending=False).head(TOP_N)
        bottom = sub.sort_values("oos_ic_mean", ascending=True).head(BOTTOM_N)

        overfit = sub[
            (sub["is_ic_mean"] >= OVERFIT_IS_THRESHOLD)
            & (sub["is_minus_oos"] >= OVERFIT_GAP_THRESHOLD)
        ].sort_values("is_minus_oos", ascending=False).head(TOP_N)

        out[h] = {
            "top": _to_records(top),
            "bottom": _to_records(bottom),
            "overfit_candidates": _to_records(overfit),
        }
    return out


# ---------------------------------------------------------------------------
# Cross-horizon synthesis (features only)
# ---------------------------------------------------------------------------

def _classify_features(per_h: pd.DataFrame) -> dict:
    """Universally-good, horizon-specific, and noise feature categorisations."""
    feat = per_h[per_h["score_type"] == "feature"].copy()

    # For each feature compute: how many horizons in top 20, and the OOS IC at each horizon.
    top_membership: dict[str, list[int]] = {}
    bottom_membership: dict[str, list[int]] = {}
    horizon_ic: dict[str, dict[int, dict]] = {}

    for h in HORIZONS:
        sub_h = feat[(feat["horizon"] == h) & (feat["n_windows"] >= MIN_WINDOWS_FOR_RANKING)]
        top = set(sub_h.sort_values("oos_ic_mean", ascending=False).head(TOP_N)["score_name"])
        bot = set(sub_h.sort_values("oos_ic_mean", ascending=True).head(BOTTOM_N)["score_name"])
        for name in sub_h["score_name"].unique():
            row = sub_h[sub_h["score_name"] == name].iloc[0]
            horizon_ic.setdefault(name, {})[h] = {
                "oos_ic": _round(row["oos_ic_mean"]),
                "t_stat": _round(row["oos_t_stat"]),
            }
            if name in top:
                top_membership.setdefault(name, []).append(h)
            if name in bot:
                bottom_membership.setdefault(name, []).append(h)

    # Universally-good: top-20 at ≥ UNIVERSAL_MIN_HORIZONS of 6 horizons.
    universal = []
    for name, horizons_in in top_membership.items():
        if len(horizons_in) >= UNIVERSAL_MIN_HORIZONS:
            ic_by_h = horizon_ic.get(name, {})
            mean_oos = float(np.nanmean([
                v["oos_ic"] for v in ic_by_h.values() if v["oos_ic"] is not None
            ]))
            universal.append({
                "name": name,
                "n_horizons_in_top_20": len(horizons_in),
                "horizons_in_top_20": sorted(horizons_in),
                "mean_oos_ic": _round(mean_oos),
                "per_horizon": {h: ic_by_h.get(h) for h in HORIZONS},
            })
    universal.sort(key=lambda r: -r["n_horizons_in_top_20"])

    # Horizon-specific: top-20 at exactly 1 or 2 horizons.
    horizon_specific = []
    for name, horizons_in in top_membership.items():
        if 1 <= len(horizons_in) <= 2:
            ic_by_h = horizon_ic.get(name, {})
            horizon_specific.append({
                "name": name,
                "horizons_in_top_20": sorted(horizons_in),
                "per_horizon": {h: ic_by_h.get(h) for h in HORIZONS},
            })
    horizon_specific.sort(key=lambda r: (-len(r["horizons_in_top_20"]), r["name"]))

    # Noise candidates: max |OOS IC| across horizons < NOISE_OOS_THRESHOLD.
    # i.e., the feature never gets above the noise floor in any horizon.
    noise = []
    for name in feat["score_name"].unique():
        ic_by_h = horizon_ic.get(name, {})
        ic_vals = [v["oos_ic"] for v in ic_by_h.values() if v["oos_ic"] is not None]
        if not ic_vals:
            continue
        max_abs = max(abs(v) for v in ic_vals)
        n_positive = sum(1 for v in ic_vals if v > 0)
        if max_abs < NOISE_OOS_THRESHOLD:
            noise.append({
                "name": name,
                "max_abs_oos_ic": _round(max_abs),
                "n_positive_horizons": n_positive,
                "n_total_horizons": len(ic_vals),
                "per_horizon": {h: ic_by_h.get(h) for h in HORIZONS},
            })
    noise.sort(key=lambda r: r["max_abs_oos_ic"])

    # Also: features that are NEGATIVE at every measured horizon (sign-flip candidates).
    sign_flip_candidates = []
    for name in feat["score_name"].unique():
        ic_by_h = horizon_ic.get(name, {})
        ic_vals = [v["oos_ic"] for v in ic_by_h.values() if v["oos_ic"] is not None]
        if not ic_vals or len(ic_vals) < 4:
            continue
        if all(v < 0 for v in ic_vals):
            mean_oos = float(np.nanmean(ic_vals))
            sign_flip_candidates.append({
                "name": name,
                "mean_oos_ic": _round(mean_oos),
                "n_horizons": len(ic_vals),
                "per_horizon": {h: ic_by_h.get(h) for h in HORIZONS},
            })
    sign_flip_candidates.sort(key=lambda r: r["mean_oos_ic"])

    return {
        "universally_good_features": universal,
        "horizon_specific_features": horizon_specific,
        "noise_candidate_features": noise,
        "sign_flip_candidate_features": sign_flip_candidates,
    }


# ---------------------------------------------------------------------------
# Component summary
# ---------------------------------------------------------------------------

def _component_summary(per_h: pd.DataFrame) -> list[dict]:
    """Components ranked by mean OOS IC across horizons + per-horizon detail."""
    comp = per_h[per_h["score_type"] == "component"].copy()
    rows = []
    for name in sorted(comp["score_name"].unique()):
        sub = comp[comp["score_name"] == name]
        per_horizon = {}
        for h in HORIZONS:
            row_h = sub[sub["horizon"] == h]
            if row_h.empty:
                per_horizon[h] = None
                continue
            r = row_h.iloc[0]
            per_horizon[h] = {
                "oos_ic": _round(r["oos_ic_mean"]),
                "t_stat": _round(r["oos_t_stat"]),
                "hit_rate": _round(r["oos_hit_rate"]),
                "is_minus_oos": _round(r["is_minus_oos"]),
            }
        ic_vals = [v["oos_ic"] for v in per_horizon.values() if v]
        mean_oos = float(np.nanmean(ic_vals)) if ic_vals else np.nan
        n_pos = sum(1 for v in ic_vals if v is not None and v > 0)
        n_sig_pos = sum(
            1 for v in per_horizon.values()
            if v and v["t_stat"] is not None and v["t_stat"] > 2.0
        )
        n_sig_neg = sum(
            1 for v in per_horizon.values()
            if v and v["t_stat"] is not None and v["t_stat"] < -2.0
        )
        rows.append({
            "name": name,
            "mean_oos_ic": _round(mean_oos),
            "n_positive_horizons": n_pos,
            "n_significant_positive_horizons": n_sig_pos,
            "n_significant_negative_horizons": n_sig_neg,
            "per_horizon": per_horizon,
        })
    rows.sort(key=lambda r: -(r["mean_oos_ic"] or -999))
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_audit() -> dict:
    diag = pd.read_parquet(DIAG_PATH)
    per_h = _per_score_per_horizon(diag)

    feature_tables = _per_horizon_tables(per_h, "feature")
    component_tables = _per_horizon_tables(per_h, "component")
    composite_tables = _per_horizon_tables(per_h, "composite")

    cross_horizon = _classify_features(per_h)
    component_summary = _component_summary(per_h)

    # Composite per-horizon detail
    composite_rows = []
    for h in HORIZONS:
        c = per_h[(per_h["score_type"] == "composite") & (per_h["horizon"] == h)]
        if c.empty:
            continue
        r = c.iloc[0]
        composite_rows.append({
            "horizon": h,
            "oos_ic": _round(r["oos_ic_mean"]),
            "t_stat": _round(r["oos_t_stat"]),
            "hit_rate": _round(r["oos_hit_rate"]),
            "is_ic": _round(r["is_ic_mean"]),
            "is_minus_oos": _round(r["is_minus_oos"]),
            "n_windows": int(r["n_windows"]),
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizons": HORIZONS,
        "thresholds": {
            "top_n": TOP_N,
            "bottom_n": BOTTOM_N,
            "min_windows": MIN_WINDOWS_FOR_RANKING,
            "overfit_is_threshold": OVERFIT_IS_THRESHOLD,
            "overfit_gap_threshold": OVERFIT_GAP_THRESHOLD,
            "noise_oos_threshold": NOISE_OOS_THRESHOLD,
            "universal_min_horizons": UNIVERSAL_MIN_HORIZONS,
        },
        "composite_ccqs": composite_rows,
        "per_horizon": {
            str(h): {
                "features": feature_tables[h],
                "components": component_tables[h],
                "composite": composite_tables[h],
            }
            for h in HORIZONS
        },
        "cross_horizon": cross_horizon,
        "components_ranked": component_summary,
    }


def _print_top_bottom(label: str, h: int, table: dict) -> None:
    print(f"\n  Horizon = {h}d  [{label}]")
    print(f"    {'rank':>4} {'name':<38} {'OOS IC':>10} {'t-stat':>8} {'hit':>8} {'IS-OOS':>10}")
    print("    TOP 20")
    for i, r in enumerate(table["top"][:20], 1):
        print(f"    {i:>4} {r['name']:<38} {r['oos_ic']:>10} {r['t_stat']:>8} "
              f"{(r['hit_rate'] or 0):>8} {(r['is_minus_oos'] or 0):>+10.4f}")
    print("    BOTTOM 20")
    for i, r in enumerate(table["bottom"][:20], 1):
        print(f"    {i:>4} {r['name']:<38} {r['oos_ic']:>10} {r['t_stat']:>8} "
              f"{(r['hit_rate'] or 0):>8} {(r['is_minus_oos'] or 0):>+10.4f}")
    print("    OVERFIT CANDIDATES (IS-OOS gap ≥ 0.010, IS IC ≥ 0.015)")
    if not table["overfit_candidates"]:
        print("      <none>")
    for i, r in enumerate(table["overfit_candidates"][:20], 1):
        print(f"    {i:>4} {r['name']:<38} {r['oos_ic']:>10} {r['t_stat']:>8} "
              f"{(r['hit_rate'] or 0):>8} {(r['is_minus_oos'] or 0):>+10.4f}")


def main() -> int:
    t0 = time.time()
    audit = build_audit()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(audit, indent=2, default=str))
    logger.info(f"Wrote {AUDIT_PATH}")

    print()
    print("=" * 90)
    print("FEATURE-LEVEL OOS AUDIT  —  131 scores × 6 horizons")
    print("=" * 90)
    print(f"  Windows per score: ≤48   |   Train=252d / Test=21d / Step=21d")

    # Composite CCQS quick row
    print("\n  Composite CCQS — OOS IC by horizon:")
    for r in audit["composite_ccqs"]:
        print(f"    h={r['horizon']:>3}d  OOS={r['oos_ic']:+.4f}  "
              f"t={r['t_stat']:+.2f}  hit={r['hit_rate']:.3f}  "
              f"IS-OOS={r['is_minus_oos']:+.4f}")

    # Per-horizon feature tables
    for h in HORIZONS:
        ftab = audit["per_horizon"][str(h)]["features"]
        _print_top_bottom("FEATURES", h, ftab)

    print()
    print("=" * 90)
    print("CROSS-HORIZON SYNTHESIS")
    print("=" * 90)

    # Universally good
    print("\n[A] UNIVERSALLY GOOD FEATURES  (top 20 at ≥ 3 of 6 horizons)")
    if not audit["cross_horizon"]["universally_good_features"]:
        print("  <none>")
    for r in audit["cross_horizon"]["universally_good_features"]:
        per_h = ", ".join(f"h{h}d={r['per_horizon'][h]['oos_ic'] if r['per_horizon'][h] else 'NA'}" for h in HORIZONS)
        print(f"  {r['name']:<38} top@{r['n_horizons_in_top_20']}/6  "
              f"mean_OOS={r['mean_oos_ic']:+.4f}  | {per_h}")

    # Horizon-specific
    print("\n[B] HORIZON-SPECIFIC FEATURES  (top 20 at exactly 1 or 2 horizons)")
    for r in audit["cross_horizon"]["horizon_specific_features"][:30]:
        print(f"  {r['name']:<38} top@{r['horizons_in_top_20']}")

    # Noise
    print("\n[C] NOISE CANDIDATES  (max |OOS IC| < 0.005 across all horizons)")
    if not audit["cross_horizon"]["noise_candidate_features"]:
        print("  <none>")
    for r in audit["cross_horizon"]["noise_candidate_features"][:30]:
        print(f"  {r['name']:<38} max|OOS|={r['max_abs_oos_ic']:.4f}  "
              f"({r['n_positive_horizons']}/{r['n_total_horizons']} positive)")

    # Sign-flip candidates
    print("\n[D] SIGN-FLIP CANDIDATES  (negative OOS IC at every horizon)")
    if not audit["cross_horizon"]["sign_flip_candidate_features"]:
        print("  <none>")
    for r in audit["cross_horizon"]["sign_flip_candidate_features"][:20]:
        per_h = ", ".join(f"h{h}d={r['per_horizon'][h]['oos_ic'] if r['per_horizon'][h] else 'NA'}" for h in HORIZONS)
        print(f"  {r['name']:<38} mean_OOS={r['mean_oos_ic']:+.4f}  | {per_h}")

    # Components
    print("\n[E] COMPONENTS RANKED BY MEAN OOS IC")
    print(f"  {'component':<22} {'mean OOS':>10} {'n_pos':>8} {'sig+':>6} {'sig-':>6}")
    for r in audit["components_ranked"]:
        print(f"  {r['name']:<22} {r['mean_oos_ic']:>+10.4f} "
              f"{r['n_positive_horizons']:>8}/6  "
              f"{r['n_significant_positive_horizons']:>5}  "
              f"{r['n_significant_negative_horizons']:>5}")
    print()
    print("=" * 90)
    print(f"Elapsed: {time.time() - t0:.1f}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
