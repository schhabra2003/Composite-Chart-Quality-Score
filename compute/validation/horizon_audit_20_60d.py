"""
Phase X.4 — Targeted feature audit at 20d and 60d horizons.

Consumes the existing oos_ic_diagnostics.parquet (Phase X.2 output) and
cross-references each feature's OOS IC at the 20d/60d horizons against
its current effective weight in the CCQS composite (derived from
compute.components and compute.ccqs.STATE_WEIGHTS).

Categories:

    A — Underweighted positive carriers
        OOS IC at 20d OR 60d > +0.025, effective weight low relative to IC

    B — Properly weighted
        effective weight ≈ IC rank-implied weight

    C — Over-weighted for 20-60d
        effective weight is high while OOS IC at 20-60d is weak

Outputs:
    data/cache/horizon_specific_audit_20_60d.json — full audit + categorization
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from compute.loader import CACHE_DIR
from compute.ccqs import STATE_WEIGHTS
from compute.state import STATES

OOS_DIAG_PATH = CACHE_DIR / "oos_ic_diagnostics.parquet"
OUT_PATH = CACHE_DIR / "horizon_specific_audit_20_60d.json"

logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")


# State-averaged component weight (uniform prior over the 6 states — gives an
# unweighted view of "how much does this component matter on average").
def _state_avg_weight() -> dict[str, float]:
    avg: dict[str, float] = {c: 0.0 for c in next(iter(STATE_WEIGHTS.values())).keys()}
    for s in STATES:
        for c, w in STATE_WEIGHTS[s].items():
            avg[c] += w
    for c in avg:
        avg[c] /= len(STATES)
    return avg


# ---------------------------------------------------------------------------
# Feature → component intra-weight map (derived from compute/components.py).
# Each entry: feature_name -> dict[component, intra_weight].
# The intra_weight is the linear coefficient applied to z[feature] inside the
# component formula. For "negated" inclusion (e.g. -z["hh_count_60d"]), we
# store the *magnitude* but flag the sign separately.
# ---------------------------------------------------------------------------

FEATURE_WEIGHTS: dict[str, dict[str, float]] = {
    # s_rs (3 features)
    "rs_rating_spy":             {"s_rs": 0.55},
    "sharpe_momentum_rank_126d": {"s_rs": 0.30},
    "within_basket_z_21d":       {"s_rs": 0.15},

    # s_rs_leadership (nested blend)
    # primary_rs 0.30
    # quality 0.15 × { sharpe_rank_252d 0.30, gain_to_pain_252d 0.30,
    #                  info_ratio_252d 0.30, sortino_rank_126d 0.10 }
    # accel   0.10 × { rs_rating_slope_60d 0.50, rs_rating_slope_120d 0.50 }
    # rsl     0.20 × { rs_line_spy_new_high_252d 0.20, rs_line_spy_slope_60d 0.15,
    #                  rs_line_spy_r_squared_60d 0.50, rs_line_qqq_new_high_252d 0.15 }
    # conf    0.15 × { mtf_rs_coherence 0.55, within_basket_z_63d 0.45 }
    # info_ratio_252d direct 0.10
    # → for rs_rating_spy:  s_rs 0.55 + s_rs_leadership 0.30
    # → for info_ratio_252d: s_rs_leadership 0.15*0.30 + 0.10 = 0.145
    # We add s_rs_leadership shares below:
    "sharpe_rank_252d":             {"s_rs_leadership": 0.15 * 0.30},
    "gain_to_pain_ratio_252d":      {"s_rs_leadership": 0.15 * 0.30},
    "information_ratio_252d":       {"s_rs_leadership": 0.15 * 0.30 + 0.10},
    "sortino_rank_126d":            {"s_rs_leadership": 0.15 * 0.10},
    "rs_rating_slope_60d":          {"s_rs_leadership": 0.10 * 0.50},
    "rs_rating_slope_120d":         {"s_rs_leadership": 0.10 * 0.50},
    "rs_line_qqq_new_high_252d":    {"s_rs_leadership": 0.20 * 0.15},
    "mtf_rs_coherence":             {"s_rs_leadership": 0.15 * 0.55},
    "within_basket_z_63d":          {"s_rs_leadership": 0.15 * 0.45},

    # s_rsl (4 features). Some shared with s_rs_leadership.rsl block.
    "rs_line_spy_new_high_60d":  {"s_rsl": 0.25},
    "rs_line_spy_slope_20d":     {"s_rsl": 0.20},

    # s_trend_slope (intra blend; sign already absorbed in robust z)
    "adx_14":                          {"s_trend_slope": 0.20},
    "trend_r_squared_60d":             {"s_trend_slope": 0.15},
    "trend_rsquared_252d":             {"s_trend_slope": 0.10},
    "hurst_exponent_252d":             {"s_trend_slope": 0.15},
    "return_autocorrelation_60d_lag1": {"s_trend_slope": 0.15},
    "trend_slope_60d":                 {"s_trend_slope": 0.10},
    "supertrend_days_since_flip":      {"s_trend_slope": 0.10},
    "plus_di":                         {"s_trend_slope": 0.05 * 0.5},
    "minus_di":                        {"s_trend_slope": 0.05 * 0.5},

    # s_structure
    "sma_stack_score":     {"s_structure": 0.20},
    "ema_stack_score":     {"s_structure": 0.20},
    "hh_count_60d":        {"s_structure": 0.10},   # negated; magnitude stored
    "hl_count_60d":        {"s_structure": 0.25},
    "new_252d_high":       {"s_structure": 0.10},
    "pct_up_days_21":      {"s_structure": 0.05},

    # s_mtf
    "weekly_stack_alignment":    {"s_mtf": 0.80 * 0.30},
    "weekly_higher_highs":       {"s_mtf": 0.80 * 0.20},
    "weekly_rs_rising":          {"s_mtf": 0.80 * 0.20},
    "weekly_trend_slope_sign":   {"s_mtf": 0.80 * 0.15},
    "monthly_close_above_sma_10":{"s_mtf": 0.20 * 0.50},
    "monthly_higher_highs_3m":   {"s_mtf": 0.20 * 0.50},

    # s_extension (all negated; magnitude stored)
    "vol_normalized_extension": {"s_extension": 0.55},
    "pct_ma_50":                {"s_extension": 0.30},
    "price_z_score_vs_trend":   {"s_extension": 0.15},

    # s_climax was removed in Phase 6 (zero weight everywhere, inverted-name
    # math). The underlying features (atr_x_50, days_near_52w_high_60d,
    # consecutive_high_intensity, climax_volume_flag) remain for state and
    # setup classification, but no longer roll up into a CCQS component.

    # s_demand
    "up_down_vol_ratio_50": {"s_demand": 0.30},
    "distribution_days_25": {"s_demand": 0.25},
    "ad_line_slope_20":     {"s_demand": 0.20},
    "cmf_21":               {"s_demand": 0.15},
    "volume_z_20_252":      {"s_demand": 0.10},

    # s_momentum
    "momentum_21d_pct":         {"s_momentum": 0.40},
    "rs_line_spy_slope_21d":    {"s_momentum": 0.20},
    "rsi_14":                   {"s_momentum": 0.10},
    "bullish_divergence_20d":   {"s_momentum": 0.05},
    "bearish_divergence_20d":   {"s_momentum": 0.05},
}

# Shared features (appear in multiple components) — extend with cross-component shares.
def _add_shared(name: str, comp: str, w: float):
    FEATURE_WEIGHTS.setdefault(name, {})[comp] = w

_add_shared("rs_rating_spy",            "s_rs_leadership", 0.30)
_add_shared("rs_line_spy_new_high_252d", "s_rs_leadership", 0.20 * 0.20)
_add_shared("rs_line_spy_new_high_252d", "s_rsl",           0.40)
_add_shared("rs_line_spy_slope_60d",    "s_rs_leadership", 0.20 * 0.15)
_add_shared("rs_line_spy_r_squared_60d","s_rs_leadership", 0.20 * 0.50)
_add_shared("rs_line_spy_r_squared_60d","s_rsl",           0.15)
_add_shared("supertrend_direction",     "s_trend_slope",   0.10)
_add_shared("supertrend_direction",     "s_structure",     0.10)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def _effective_weight(feature: str, comp_avg: dict[str, float]) -> float:
    """Σ_c intra_weight(f, c) × state_avg_weight(c)."""
    parts = FEATURE_WEIGHTS.get(feature, {})
    return sum(comp_avg.get(c, 0.0) * w for c, w in parts.items())


def _components_for(feature: str) -> list[str]:
    return sorted(FEATURE_WEIGHTS.get(feature, {}).keys())


def run_audit() -> dict:
    if not OOS_DIAG_PATH.exists():
        raise RuntimeError(f"{OOS_DIAG_PATH} missing — run feature_audit first.")

    diag = pd.read_parquet(OOS_DIAG_PATH)
    feat = diag[diag["score_type"] == "feature"]

    comp_avg = _state_avg_weight()

    rows: list[dict] = []
    for name, grp in feat.groupby("score_name", sort=False):
        # Per-horizon mean & t-stat
        per_h: dict[int, dict[str, float]] = {}
        for h in (1, 5, 20, 60, 126, 252):
            sub = grp[grp["horizon"] == h]["oos_ic"].dropna()
            if sub.empty:
                continue
            mean = float(sub.mean())
            std = float(sub.std())
            n = int(len(sub))
            t = (mean / (std / np.sqrt(n))) if std > 0 and n > 1 else float("nan")
            per_h[h] = {"mean": mean, "std": std, "n": n, "t_stat": float(t)}

        eff_w = _effective_weight(name, comp_avg)
        comps = _components_for(name)

        rows.append({
            "feature": name,
            "components": comps,
            "effective_weight": round(eff_w, 4),
            "oos_ic_1d":   per_h.get(1,   {}).get("mean"),
            "tstat_1d":    per_h.get(1,   {}).get("t_stat"),
            "oos_ic_5d":   per_h.get(5,   {}).get("mean"),
            "tstat_5d":    per_h.get(5,   {}).get("t_stat"),
            "oos_ic_20d":  per_h.get(20,  {}).get("mean"),
            "tstat_20d":   per_h.get(20,  {}).get("t_stat"),
            "oos_ic_60d":  per_h.get(60,  {}).get("mean"),
            "tstat_60d":   per_h.get(60,  {}).get("t_stat"),
            "oos_ic_126d": per_h.get(126, {}).get("mean"),
            "tstat_126d":  per_h.get(126, {}).get("t_stat"),
            "oos_ic_252d": per_h.get(252, {}).get("mean"),
            "tstat_252d":  per_h.get(252, {}).get("t_stat"),
        })

    df = pd.DataFrame(rows)

    # Category A: features with OOS IC > 0.025 at 20d OR 60d, with low effective weight
    #   "low effective weight" = bottom half of features by effective_weight,
    #   OR effective_weight < 0.020 (less than 2% contribution to CCQS).
    ic_20 = df["oos_ic_20d"].fillna(0)
    ic_60 = df["oos_ic_60d"].fillna(0)
    best_2060 = np.maximum(ic_20.abs(), ic_60.abs()) * np.sign(np.where(ic_20.abs() >= ic_60.abs(), ic_20, ic_60))
    df["best_abs_20_60"] = np.maximum(ic_20.abs(), ic_60.abs())
    df["best_signed_20_60"] = best_2060

    # A: strong positive OOS IC at 20d or 60d AND weight under-allocated
    cat_a_mask = (
        ((df["oos_ic_20d"] > 0.025) | (df["oos_ic_60d"] > 0.025))
        & (df["effective_weight"] < 0.020)
    )
    # C: features with effective weight > 0.020 but OOS IC at 20d AND 60d < 0.005
    cat_c_mask = (
        (df["effective_weight"] > 0.020)
        & (df["oos_ic_20d"].fillna(0).abs() < 0.005)
        & (df["oos_ic_60d"].fillna(0).abs() < 0.005)
    )
    cat_b_mask = ~(cat_a_mask | cat_c_mask)

    def _sort_export(sub: pd.DataFrame) -> list[dict]:
        return (
            sub.sort_values("best_abs_20_60", ascending=False)
               .drop(columns=["best_abs_20_60", "best_signed_20_60"])
               .to_dict(orient="records")
        )

    audit = {
        "horizons_analyzed": [20, 60],
        "n_features_total": int(len(df)),
        "n_category_a": int(cat_a_mask.sum()),
        "n_category_b": int(cat_b_mask.sum()),
        "n_category_c": int(cat_c_mask.sum()),
        "state_avg_component_weight": {c: round(v, 4) for c, v in comp_avg.items()},
        "category_a_features": _sort_export(df[cat_a_mask]),
        "category_b_features": _sort_export(df[cat_b_mask]),
        "category_c_features": _sort_export(df[cat_c_mask]),
        "top_15_by_20d_ic":     _sort_export(df.sort_values("oos_ic_20d",  ascending=False).head(15)),
        "top_15_by_60d_ic":     _sort_export(df.sort_values("oos_ic_60d",  ascending=False).head(15)),
        "bottom_15_by_20d_ic":  _sort_export(df.sort_values("oos_ic_20d",  ascending=True).head(15)),
        "bottom_15_by_60d_ic":  _sort_export(df.sort_values("oos_ic_60d",  ascending=True).head(15)),
    }

    return audit, df


def _fmt_row(r: dict, hk: str = "20d") -> str:
    ic = r.get(f"oos_ic_{hk}", float("nan")) or float("nan")
    t = r.get(f"tstat_{hk}", float("nan")) or float("nan")
    ew = r["effective_weight"]
    comps = ",".join(r["components"]) if r["components"] else "(none)"
    return f"  {r['feature']:<35} ic={ic:+.4f}  t={t:+5.2f}  eff_w={ew:.4f}  ← {comps}"


def main() -> int:
    audit, df = run_audit()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(audit, indent=2, default=str))
    logger.info(f"Wrote {OUT_PATH}")

    print()
    print("=" * 92)
    print("PHASE X.4 — TARGETED FEATURE AUDIT @ 20d / 60d HORIZONS")
    print("=" * 92)
    print(f"Features audited: {audit['n_features_total']}")
    print(f"Category A (underweighted strong): {audit['n_category_a']}")
    print(f"Category B (properly weighted):    {audit['n_category_b']}")
    print(f"Category C (overweighted weak):    {audit['n_category_c']}")
    print()
    print("State-avg component weight (uniform prior over 6 states):")
    for c, w in audit["state_avg_component_weight"].items():
        print(f"  {c:<22} {w:.4f}")

    print()
    print("[1] TOP 15 BY 20d OOS IC (with current effective weight in CCQS)")
    print("-" * 92)
    for r in audit["top_15_by_20d_ic"]:
        print(_fmt_row(r, "20d"))

    print()
    print("[2] TOP 15 BY 60d OOS IC")
    print("-" * 92)
    for r in audit["top_15_by_60d_ic"]:
        print(_fmt_row(r, "60d"))

    print()
    print(f"[3] CATEGORY A FEATURES — strong 20d/60d OOS IC, under-allocated  (n={audit['n_category_a']})")
    print("-" * 92)
    for r in audit["category_a_features"]:
        # show whichever horizon is stronger
        ic20 = abs(r.get("oos_ic_20d") or 0)
        ic60 = abs(r.get("oos_ic_60d") or 0)
        hk = "20d" if ic20 >= ic60 else "60d"
        print(_fmt_row(r, hk))

    print()
    print(f"[4] CATEGORY C — over-weighted for 20-60d  (n={audit['n_category_c']})")
    print("-" * 92)
    for r in audit["category_c_features"]:
        ic20 = r.get("oos_ic_20d") or 0.0
        ic60 = r.get("oos_ic_60d") or 0.0
        ew = r["effective_weight"]
        comps = ",".join(r["components"])
        print(f"  {r['feature']:<35} ic20={ic20:+.4f}  ic60={ic60:+.4f}  eff_w={ew:.4f}  ← {comps}")

    print()
    print("[5] CATEGORY A — COMPONENT CLUSTERING")
    print("-" * 92)
    from collections import Counter
    a_comps_counter: Counter = Counter()
    for r in audit["category_a_features"]:
        for c in r["components"]:
            a_comps_counter[c] += 1
    if a_comps_counter:
        for c, n in a_comps_counter.most_common():
            print(f"  {c:<22} {n} feature(s)")
    else:
        print("  (no Category A features)")

    print("=" * 92)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
