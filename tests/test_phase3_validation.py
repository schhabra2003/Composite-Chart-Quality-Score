"""Phase 3 validation: end-to-end pipeline sanity + headline metrics."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path("data/cache")


def _load() -> dict[str, pd.DataFrame]:
    return {
        "features": pd.read_parquet(CACHE / "features.parquet"),
        "components": pd.read_parquet(CACHE / "components.parquet"),
        "state": pd.read_parquet(CACHE / "state.parquet"),
        "leadership": pd.read_parquet(CACHE / "leadership.parquet"),
        "ccqs": pd.read_parquet(CACHE / "ccqs.parquet"),
        "setups": pd.read_parquet(CACHE / "setups.parquet"),
    }


def main() -> None:
    d = _load()
    pipeline_meta = json.loads((CACHE / "pipeline_meta.json").read_text())

    print("=" * 72)
    print("PHASE 3 VALIDATION REPORT")
    print("=" * 72)

    # --- 1. Pipeline runtime ---------------------------------------------
    print(f"\n[1] Pipeline runtime: {pipeline_meta['elapsed_seconds']:.1f}s")
    print(f"    (target: <60s)")
    for stage, t in pipeline_meta["stage_times_seconds"].items():
        print(f"      {stage:<14}{t:>6.1f}s")

    # --- 2. Universe -----------------------------------------------------
    n_tickers = pipeline_meta["n_tickers"]
    n_dates = pipeline_meta["n_dates"]
    print(f"\n[2] Universe: {n_tickers} tickers × {n_dates} dates")

    # --- 3. CCQS distribution --------------------------------------------
    ccqs = d["ccqs"]["ccqs"]
    print(f"\n[3] CCQS distribution:")
    print(f"      mean   = {ccqs.mean():.2f}")
    print(f"      median = {ccqs.median():.2f}")
    print(f"      p1     = {np.nanpercentile(ccqs, 1):.2f}")
    print(f"      p50    = {np.nanpercentile(ccqs, 50):.2f}")
    print(f"      p99    = {np.nanpercentile(ccqs, 99):.2f}")
    print(f"      min    = {ccqs.min():.2f}")
    print(f"      max    = {ccqs.max():.2f}")

    # --- 4. Grade distribution -------------------------------------------
    grade_dist = d["ccqs"]["grade"].astype(str).value_counts(normalize=True)
    print(f"\n[4] Grade distribution:")
    for g in ["S", "A", "B", "C", "D"]:
        pct = grade_dist.get(g, 0.0) * 100
        flag = ""
        if g == "S":
            if pct > 15: flag = "  <-- HIGH (target 2-15%)"
            elif pct < 2: flag = "  <-- LOW (target 2-15%)"
        print(f"      Grade {g}: {pct:6.2f}%{flag}")

    # --- 5. State distribution -------------------------------------------
    state_dist = d["state"]["primary_state"].astype(str).value_counts(normalize=True)
    print(f"\n[5] State distribution:")
    for s in ["TRENDING", "PULLBACK", "CONSOLIDATING", "EXHAUSTION", "DETERIORATING", "INDETERMINATE"]:
        pct = state_dist.get(s, 0.0) * 100
        print(f"      {s:<14} {pct:6.2f}%")
    mean_conf = d["state"]["state_confidence"].mean()
    print(f"      mean confidence: {mean_conf:.3f}")

    # --- 6. Leadership tier distribution ---------------------------------
    tier_dist = d["leadership"]["leadership_tier"].astype(str).value_counts(normalize=True)
    print(f"\n[6] Leadership tier distribution:")
    for t in ["ELITE_LEADER", "STRONG_LEADER", "EMERGING_LEADER",
              "ESTABLISHED_LEADER", "STRONG_PERFORMER", "NEUTRAL",
              "WEAK_PERFORMER", "DETERIORATING", "WEAK_LAGGARD"]:
        pct = tier_dist.get(t, 0.0) * 100
        print(f"      {t:<20} {pct:6.2f}%")

    # --- 7. Top 10 setups ------------------------------------------------
    setup_dist = d["setups"]["setup"].astype(str).value_counts(normalize=True)
    print(f"\n[7] Top 10 setups (by frequency):")
    for label, frac in setup_dist.head(10).items():
        print(f"      {label:<40} {frac*100:6.2f}%")

    # --- 8. NVDA latest detail -------------------------------------------
    print(f"\n[8] NVDA latest detail:")
    try:
        last_date = d["features"].index.get_level_values("date").max()
        nvda_idx = ("NVDA", last_date)
        f = d["features"].loc[nvda_idx]
        c = d["components"].loc[nvda_idx]
        s = d["state"].loc[nvda_idx]
        l = d["leadership"].loc[nvda_idx]
        q = d["ccqs"].loc[nvda_idx]
        st = d["setups"].loc[nvda_idx]

        print(f"      date           : {last_date}")
        print(f"      RS Rating SPY  : {f['rs_rating_spy']:.2f}")
        print(f"      ATR × 50       : {f['atr_x_50']:.2f}")
        print(f"      pct_ma_50      : {f['pct_ma_50']:.2f}%")
        print(f"      ADX(14)        : {f['adx_14']:.2f}")
        print(f"      RSI(14)        : {f['rsi_14']:.2f}")
        print()
        print(f"      Components (z-space):")
        for col in ["s_rs", "s_rs_leadership", "s_rsl", "s_trend_slope",
                    "s_structure", "s_mtf", "s_extension",
                    "s_demand", "s_momentum"]:
            print(f"        {col:<22} {c[col]: .3f}")
        print()
        print(f"      Primary state  : {s['primary_state']} (conf {s['state_confidence']:.3f})")
        print(f"      State probs    :")
        for state_name in ["TRENDING", "PULLBACK", "CONSOLIDATING", "EXHAUSTION", "DETERIORATING", "INDETERMINATE"]:
            print(f"        {state_name:<14} {s[f'p_{state_name}']:.4f}")
        print()
        print(f"      Leadership tier: {l['leadership_tier']}")
        print(f"      Basket leader  : {l['is_basket_leader']}")
        print(f"      CCQS           : {q['ccqs']:.2f}  (grade {q['grade']})")
        print(f"      CCQS z         : {q['ccqs_z']:.3f}")
        print(f"      Setup          : {st['setup']} (conf {st['setup_confidence']:.2f})")
    except KeyError as e:
        print(f"      NVDA missing for {last_date}: {e}")

    # --- 9. Sanity checks ------------------------------------------------
    print(f"\n[9] Sanity checks:")
    n = len(d["ccqs"])
    n_ccqs_nan = d["ccqs"]["ccqs"].isna().sum()
    n_grade_nan = d["ccqs"]["grade"].isna().sum()
    print(f"      n rows            : {n:,}")
    print(f"      CCQS NaN          : {n_ccqs_nan} ({n_ccqs_nan/n*100:.2f}%)")
    print(f"      Grade NaN         : {n_grade_nan} ({n_grade_nan/n*100:.2f}%)")
    print(f"      CCQS in [0,100]   : {bool(((d['ccqs']['ccqs'].dropna() >= 0) & (d['ccqs']['ccqs'].dropna() <= 100)).all())}")
    print(f"      State probs sum~1 : {bool(np.isclose(d['state'][['p_TRENDING','p_PULLBACK','p_CONSOLIDATING','p_EXHAUSTION','p_DETERIORATING','p_INDETERMINATE']].sum(axis=1).dropna(), 1.0, atol=1e-3).all())}")
    print(f"      State p_adj sum~1 : {bool(np.isclose(d['state'][['p_adj_TRENDING','p_adj_PULLBACK','p_adj_CONSOLIDATING','p_adj_EXHAUSTION','p_adj_DETERIORATING','p_adj_INDETERMINATE']].sum(axis=1).dropna(), 1.0, atol=1e-3).all())}")

    n_inf_comp = np.isinf(d["components"].select_dtypes(include=np.number)).any().any()
    print(f"      No inf components : {not bool(n_inf_comp)}")

    print()
    print("=" * 72)


if __name__ == "__main__":
    main()
