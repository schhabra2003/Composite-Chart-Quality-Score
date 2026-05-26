"""
CCQS V1 — Setup Classification (SPEC Section 10)

23 priority-ordered specific setups + 5 state-aware catch-alls + 1 final
fallback ("Indeterminate Pattern") = 28 active labels. First-match-wins
along the priority chain.

Phase 11.B.1 (2026-05-26): removed "Consolidation Within Strong Theme"
(setup #18 in the prior cascade) which was dead code — it required a
`theme_strong` flag from the aggregation layer that was never wired
through, so the rule never fired (n=0 over 1.53M rows in the Phase 11B
audit). The aggregation layer's `theme_class` remains available for a
future revival of theme-aware setups, but the empty rule is no longer
on the cascade.

Run:
    python -m compute.setup_classifier
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

FEATURES_PATH = CACHE_DIR / "features.parquet"
COMPONENTS_PATH = CACHE_DIR / "components.parquet"
STATE_PATH = CACHE_DIR / "state.parquet"
CCQS_PATH = CACHE_DIR / "ccqs.parquet"
LEADERSHIP_PATH = CACHE_DIR / "leadership.parquet"
SETUP_PATH = CACHE_DIR / "setups.parquet"
SETUP_META_PATH = CACHE_DIR / "setups_meta.json"

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")
logger.add(LOG_DIR / "ccqs.log", level="DEBUG", rotation="10 MB", retention="30 days")


SETUP_LABELS: list[str] = [
    # Exhaustion (1-4)
    "Extreme Extension", "Exhaustion w/ Bearish Divergence",
    "Volume-Confirmed Exhaustion", "Extended Exhaustion",
    # Deteriorating (5-8)
    "Capitulation Selling", "Deteriorating w/ Bullish Divergence",
    "Distribution Pattern", "Sustained Weakness",
    # Elite Leader (9-10)
    "Elite Leader Continuation", "Elite Leader Pullback",
    # Premium Long (11-13)
    "Premium Pullback", "Emerging Leader",
    "Theme Leader Pullback",
    # Trending (14-15)
    "Trend Continuation", "Trending Leadership",
    # Pullback (16-17)
    "Pullback to 21EMA", "Pullback to 50MA",
    # Consolidating (18-21) — Phase 11.B.1: removed dead
    # "Consolidation Within Strong Theme" (n=0, theme_strong hardcoded False).
    "Tight Consolidation Pre-Breakout",
    "VCP Setup", "BB Squeeze with RS", "Range Consolidation",
    # Failure / Transition (22)
    "Failed Breakout",
    # State-aware catch-alls (23-28) — assigned when no specific rule fired.
    "Trending (Generic)", "Routine Pullback", "Consolidating (Generic)",
    "Exhaustion (Generic)", "Deteriorating (Generic)", "Indeterminate Pattern",
]


def _bool(s: pd.Series) -> pd.Series:
    """Coerce to a NaN-safe boolean Series."""
    return s.astype(float).fillna(0).astype(bool)


def classify_setups(
    features: pd.DataFrame,
    state: pd.DataFrame,
    leadership: pd.DataFrame,
) -> pd.DataFrame:
    """Vectorized first-match-wins setup classifier (24 categories)."""
    idx = features.index
    setup = pd.Series("", index=idx, dtype=object)
    confidence = pd.Series(0.0, index=idx)
    assigned = pd.Series(False, index=idx)

    # ---- Pull the columns we need -----------------------------------------
    f = features
    state = state.reindex(idx)
    leadership = leadership.reindex(idx)

    atr_x_50 = f["atr_x_50"].astype(float)
    rs_spy = f["rs_rating_spy"].astype(float)
    rs_slope_60 = f["rs_rating_slope_60d"].astype(float)
    pct_ma_50 = f["pct_ma_50"].astype(float)
    sma_stack = f["sma_stack_score"].astype(float)
    ema_stack = f["ema_stack_score"].astype(float)
    adx_14 = f["adx_14"].astype(float)
    udvr_50 = f["up_down_vol_ratio_50"].astype(float)
    mtf_coh = f["mtf_rs_coherence"].astype(float)
    volume_lead = _bool(f["volume_leadership_confirmed"])
    bb_sq = _bool(f["bb_squeeze_flag"])
    bb_w = f["bb_width_pct_252d"].astype(float)
    vcp_q = f["vcp_quality_score"].astype(float)
    vol_z = f["volume_z_20_252"].astype(float)
    new_252_high = _bool(f["new_252d_high"])
    failed_brk = _bool(f["failed_breakout_flag_10d"])
    days_near_high = f["days_near_52w_high_60d"].astype(float)
    bear_div = _bool(f["bearish_divergence_20d"])
    bull_div = _bool(f["bullish_divergence_20d"])
    climax_vol = _bool(f["climax_volume_flag"])
    capit_vol = _bool(f["capitulation_volume_flag"])
    dist_days = f["distribution_days_25"].astype(float)
    supertrend_dir = f["supertrend_direction"].astype(float)
    close = f["close"].astype(float)
    ema_21 = f["ema_21"].astype(float)
    sma_50 = f["sma_50"].astype(float)
    atr_14 = f["atr_14"].astype(float)

    p_trending = state["p_TRENDING"].astype(float).fillna(0)
    p_pullback = state["p_PULLBACK"].astype(float).fillna(0)

    tier = leadership["leadership_tier"].astype(str)
    is_elite = tier == "ELITE_LEADER"
    is_basket_leader = _bool(leadership["is_basket_leader"])

    # Helper: only fill where unassigned.
    def _apply(mask: pd.Series, label: str, conf: float) -> None:
        take = mask.fillna(False) & ~assigned
        setup[take] = label
        confidence[take] = conf
        assigned[take] = True

    # ---- 1. Extreme Extension --------------------------------------------
    # Pure extension trigger (atr_x_50 ≥ 6.5). No volume/shape requirement,
    # so prior "Parabolic Blow-Off" naming overclaimed the pattern.
    _apply(atr_x_50 >= 6.5, "Extreme Extension", 0.95)

    # ---- 2. Exhaustion w/ Bearish Divergence -----------------------------
    _apply(
        (atr_x_50 >= 4.0) & bear_div & (rs_spy >= 85),
        "Exhaustion w/ Bearish Divergence", 0.90,
    )

    # ---- 3. Volume-Confirmed Exhaustion ----------------------------------
    _apply(
        (atr_x_50 >= 4.5) & climax_vol,
        "Volume-Confirmed Exhaustion", 0.90,
    )

    # ---- 4. Extended Exhaustion ------------------------------------------
    _apply(
        (atr_x_50 >= 4.0) & (days_near_high >= 15) & (rs_spy >= 80),
        "Extended Exhaustion", 0.75,
    )

    # ---- 5. Capitulation Selling -----------------------------------------
    _apply(
        (pct_ma_50 < -8) & capit_vol,
        "Capitulation Selling", 0.85,
    )

    # ---- 6. Deteriorating w/ Bullish Divergence --------------------------
    _apply(
        (pct_ma_50 < -5) & bull_div,
        "Deteriorating w/ Bullish Divergence", 0.80,
    )

    # ---- 7. Distribution Pattern -----------------------------------------
    _apply(
        (pct_ma_50 < -5) & (dist_days >= 8),
        "Distribution Pattern", 0.85,
    )

    # ---- 8. Sustained Weakness -------------------------------------------
    # Static position threshold (>8% below 50MA). Prior "Trend Failure" name
    # implied a transition event the math doesn't verify.
    _apply(pct_ma_50 < -8, "Sustained Weakness", 0.70)

    # ---- 9. Elite Leader Continuation ------------------------------------
    _apply(
        (p_trending > 0.5) & is_elite,
        "Elite Leader Continuation", 0.95,
    )

    # ---- 10. Elite Leader Pullback ---------------------------------------
    _apply(
        (p_pullback > 0.5) & is_elite,
        "Elite Leader Pullback", 0.95,
    )

    # ---- 11. Premium Pullback --------------------------------------------
    # Comprehensive high-quality pullback gates. Prior "Tier S Pullback" name
    # mixed grade vocabulary with setup detection — math never checks CCQS grade.
    _apply(
        (sma_stack >= 85)
        & (ema_stack >= 70)
        & (pct_ma_50 > 0) & (pct_ma_50 < 10)
        & (atr_x_50 < 2.5)
        & (rs_spy >= 80)
        & (udvr_50 >= 1.3),
        "Premium Pullback", 0.95,
    )

    # ---- 12. Emerging Leader ---------------------------------------------
    # Mid-tier RS rapidly accelerating with multi-timeframe + volume confirm.
    # Prior "(Multibagger Setup)" parenthetical claimed a forward outcome the
    # math does not predict — dropped.
    _apply(
        (rs_spy >= 60) & (rs_spy <= 85)
        & (rs_slope_60 >= 10)
        & (mtf_coh >= 2)
        & volume_lead,
        "Emerging Leader", 0.85,
    )

    # ---- 13. Theme Leader Pullback ---------------------------------------
    _apply(
        is_basket_leader & (p_pullback > 0.4),
        "Theme Leader Pullback", 0.80,
    )

    # ---- 14. Trend Continuation ------------------------------------------
    _apply(
        (sma_stack >= 85)
        & (adx_14 >= 25)
        & (atr_x_50 < 4.5)
        & (rs_spy >= 80)
        & (supertrend_dir == 1),
        "Trend Continuation", 0.90,
    )

    # ---- 15. Trending Leadership -----------------------------------------
    _apply(
        (sma_stack >= 75)
        & (rs_spy >= 80)
        & (adx_14 >= 20),
        "Trending Leadership", 0.85,
    )

    # ---- 16. Pullback to 21EMA -------------------------------------------
    near_21ema = ((close - ema_21).abs() / atr_14.clip(lower=1e-6)) < 0.7
    _apply(
        (sma_stack >= 80) & near_21ema & (rs_spy >= 75),
        "Pullback to 21EMA", 0.85,
    )

    # ---- 17. Pullback to 50MA --------------------------------------------
    near_50ma = ((close - sma_50).abs() / atr_14.clip(lower=1e-6)) < 1.2
    _apply(
        (sma_stack >= 75) & near_50ma & (rs_spy >= 70),
        "Pullback to 50MA", 0.80,
    )

    # ---- 18. Tight Consolidation Pre-Breakout ---------------------------
    # (Previous #18 "Consolidation Within Strong Theme" removed in Phase
    # 11.B.1 — dead code that never fired; see module docstring.)
    _apply(
        bb_sq & (vcp_q >= 70) & (rs_spy >= 85) & (vol_z >= 0.5),
        "Tight Consolidation Pre-Breakout", 0.90,
    )

    # ---- 19. VCP Setup ---------------------------------------------------
    _apply(
        (vcp_q >= 60) & (rs_spy >= 75) & (sma_stack >= 75),
        "VCP Setup", 0.80,
    )

    # ---- 20. BB Squeeze with RS ------------------------------------------
    _apply(
        bb_sq & (bb_w < 20) & (rs_spy >= 70),
        "BB Squeeze with RS", 0.75,
    )

    # ---- 21. Range Consolidation -----------------------------------------
    _apply(bb_sq | (bb_w < 15), "Range Consolidation", 0.70)

    # ---- 22. Failed Breakout ---------------------------------------------
    # Tightened: a true failed breakout requires both a flag AND post-failure
    # weakness (below the 50MA) AND non-leadership. Otherwise a "flag tap"
    # on a strong stock got mis-labeled as failure.
    _apply(
        failed_brk & (pct_ma_50 < 0) & (rs_spy < 70),
        "Failed Breakout", 0.85,
    )

    # ---- 23-28. State-aware catch-alls -----------------------------------
    # Anything still unassigned gets a label that reflects its primary state,
    # rather than collapsing into a single "Mixed" bucket. This keeps
    # downstream consumers informed about whether the stock is in a healthy
    # state without a sharp setup, or in a degenerate state.
    primary = state["primary_state"].astype(str)
    unassigned = ~assigned

    def _catchall(state_name: str, label: str, conf: float) -> None:
        mask = unassigned & (primary == state_name)
        setup[mask] = label
        confidence[mask] = conf
        assigned[mask] = True

    # Catch-all naming convention: "<State> (Generic)" when no specific
    # pattern matched. Prior names ("Sustained Uptrend", "Constructive
    # Consolidation", "Late-Cycle Pattern", "Low-Confidence Pattern")
    # overclaimed by implying duration, bias, macro-cycle position, or
    # confidence judgments that the catch-all doesn't verify.
    _catchall("TRENDING", "Trending (Generic)", 0.65)
    _catchall("PULLBACK", "Routine Pullback", 0.65)
    _catchall("CONSOLIDATING", "Consolidating (Generic)", 0.65)
    _catchall("EXHAUSTION", "Exhaustion (Generic)", 0.65)
    _catchall("DETERIORATING", "Deteriorating (Generic)", 0.65)

    # Final fallback for INDETERMINATE / unknown.
    remaining = ~assigned
    setup[remaining] = "Indeterminate Pattern"
    confidence[remaining] = 0.55

    out = pd.DataFrame(index=idx)
    out["setup"] = pd.Categorical(setup, categories=SETUP_LABELS)
    out["setup_confidence"] = confidence
    return out


def main() -> int:
    t0 = time.time()
    for path in (FEATURES_PATH, STATE_PATH, LEADERSHIP_PATH):
        if not path.exists():
            logger.error(f"Missing input {path}. Run earlier stages first.")
            return 1

    features = pd.read_parquet(FEATURES_PATH)
    state = pd.read_parquet(STATE_PATH)
    leadership = pd.read_parquet(LEADERSHIP_PATH)

    setups = classify_setups(features, state, leadership)
    elapsed = time.time() - t0

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    setups.to_parquet(SETUP_PATH, compression="snappy")
    logger.info(
        f"Wrote {SETUP_PATH} ({len(setups):,} rows × {len(setups.columns)} cols) in {elapsed:.1f}s"
    )

    dist = setups["setup"].astype(str).value_counts(normalize=True).to_dict()
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "n_rows": int(len(setups)),
        "setup_labels": SETUP_LABELS,
        "setup_distribution": {k: round(v, 4) for k, v in dist.items()},
    }
    SETUP_META_PATH.write_text(json.dumps(meta, indent=2, default=str))

    print()
    print("=" * 60)
    print("SETUP DISTRIBUTION (all rows)")
    print("=" * 60)
    top = sorted(dist.items(), key=lambda kv: -kv[1])[:24]
    for label, frac in top:
        print(f"  {label:<40} {frac*100:6.2f}%")
    print(f"Elapsed: {elapsed:.1f}s")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
