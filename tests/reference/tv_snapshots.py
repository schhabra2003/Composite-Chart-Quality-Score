"""
TradingView reference snapshots for 10 large-cap canaries.

These values are pinned from the 2026-05-22 pipeline output and are spot-
checked against TradingView indicator screenshots for the same date. The
test in `test_tv_parity.py` re-derives the same fields from the live
parquet outputs and asserts they fall within the per-field tolerance below.

When indicators are recalibrated or upstream data changes:
  1.  Update TV_SNAPSHOTS values from the latest pipeline output. A simple
      pull script lives in `/tmp/p3a_demand_removal.py`-style format; pull
      each canary's row from `data/cache/{ccqs,state,leadership,setups,
      features,ohlcv_daily}.parquet` at REFERENCE_DATE and round to the
      precision shown below.
  2.  Visually re-cross-check ≥3 tickers against TradingView screenshots
      on the same date (technical-indicator fields only — close, RSI,
      ADX, ATR, %MA — these are direct TV equivalents).
  3.  Note the snapshot date and reason for the refresh below.

Refresh log:
  2026-05-22  Phase 4 build — initial pin.
  2026-05-25  Setup labels updated for Phase 5.8 Tier A vocabulary audit
              (NVDA / META / JPM / UNH setup fields only — partial refresh).
  2026-05-25  Full refresh to Phase 7 (post Priority 3a `s_demand` removal
              + carrier redistribution).
  2026-05-26  Full refresh to Phase 8a (residual-momentum addition).
              Phase 8a adds `s_residual_momentum` as a 10th component at
              5% per state in STATE_WEIGHTS. CCQS values drift modestly
              vs Phase 7 (NVDA 77.40 → 74.85, GOOGL 91.17 → 89.51,
              AMZN 85.92 → 83.97). Technical-indicator pins (close, RSI,
              ADX, ATR, %MA) are unchanged from Phase 7 — those don't
              depend on the composite weights. Setup labels reflect
              Phase 5.7 + 5.8 vocabulary. Empirical validation (Phase 8a
              investigation) showed walk-forward 126d t-statistic
              improves 1.87 → 2.02 with the addition.
  2026-05-26  CCQS refresh to Phase 10 (volume-pattern addition).
              Phase 10 adds `s_volume` as an 11th component at 3% per
              state, with the existing 10 components scaled by 0.97.
              CCQS drift vs Phase 8a is small (max |Δ| = 1.93 for TSLA;
              NVDA unchanged at 74.85). State labels, setup labels,
              state confidence, leadership tier, and all technical-
              indicator pins are unchanged (none of those depend on
              the composite weights). Empirical validation (Phase 10
              W1 investigation): per-date IC delta CI strict > 0 at 5d
              [+0.000012, +0.000686]; walk-forward 5d paired t = +2.01;
              20d t-stat crosses back above institutional 2.0 threshold
              (1.95 → 2.04); EXHAUSTION-state IC +0.006 to +0.016 at
              every horizon (resolves fragility documented across Phase
              3c / 8a.1 / 8b).
  2026-05-26  PATH C COMPLETE through Phase 12 (closeout doc).
              No further numerical changes from Phase 11.B.1 (dead
              setup removal), 11.C.1 (UNCLASSIFIED tier added — fall-
              through fix), 11E.1 (Emerging Leader setup removed), or
              11E.2 (dashboard regime chip) — none of those four
              patches affect CCQS computation. TV reference pins remain
              identical to the Phase 10 baseline above. Pipeline
              re-verified post-Phase-12 documentation work.
  2026-05-26  Phase 14.1 universe expansion (884 → 1,790 tickers)
              attempted. Conditional IC analysis revealed methodology
              produces near-zero / negative forward signal on the 953
              new small-cap names (5d t=+0.26, 20d t=-1.77, 60d t=-1.58,
              126d t=+2.80) while remaining intact for the original
              universe (5d t=+2.35, 20d t=+1.97, 60d t=+3.46, 126d
              t=+9.10). Phase 14.1 REVERTED in Phase 14R; AMZN setup
              restored to "Range Consolidation"/0.70.
  2026-05-26  **Phase 14R reversion to Path C state.** Universe restored
              to exact 884-ticker Path C baseline. CCQS bit-identical to
              Phase 11/12. Decision: build separate Small Cap CCQS
              (Phase 15) with empirically recalibrated methodology
              rather than force a single methodology onto two
              structurally different universes.
  2026-05-28  **Phase 25 setup-label redesign.** Setup column refreshed
              to the new 12-label chart-evocative cascade (display-layer
              only — no methodology change). Labels are descriptive,
              first-match-wins, 1-2 words. All numeric / categorical
              non-setup fields (close, RSI, ADX, ATR, %MA, CCQS, grade,
              state, state_confidence, leadership_tier) are bit-identical
              to the Phase 14R baseline — only `setup` and `setup_confidence`
              changed. Confidence is 1.0 for any assigned label, 0.0 for
              blank ("" — silence beats noise). Canary changes:
                NVDA  Trending (Generic)                → Shallow Pullback
                MSFT  Range Consolidation               → "" (blank)
                META  Deteriorating (Generic)           → "" (blank)
                GOOGL Exhaustion w/ Bearish Divergence  → Shallow Pullback
                TSLA  Theme Leader Pullback             → "" (blank)
                AMZN  Range Consolidation               → Coiling
                JPM   Deteriorating (Generic)           → Sideways
                TSM   Pullback to 21EMA                 → Coiling
                LLY   Indeterminate Pattern             → Extended
                UNH   Trending (Generic)                → Tight Base

Last refreshed: 2026-05-28 (Phase 25 setup-label redesign — display-layer only).
"""
from __future__ import annotations

REFERENCE_DATE = "2026-05-22"

# Per-field absolute tolerance. Wider on indicators where TV/our convention
# differs slightly (ADX/RSI smoothing, ATR multiple).
TOLERANCES: dict[str, float] = {
    "close": 0.50,
    "rs_rating_spy": 5.0,
    "pct_ma_50": 1.0,
    "pct_ma_200": 1.5,
    "adx_14": 3.0,
    "rsi_14": 2.0,
    "atr_x_50": 1.0,
    "ccqs": 5.0,
    "state_confidence": 0.10,
    "setup_confidence": 0.10,
}

# Exact-match fields (categorical labels).
EXACT_FIELDS: list[str] = ["grade", "state", "leadership_tier", "setup"]

TV_SNAPSHOTS: dict[str, dict] = {
    "NVDA": {
        "date": REFERENCE_DATE,
        "close": 215.33,
        "rs_rating_spy": 70.05,
        "pct_ma_50": 9.41,
        "pct_ma_200": 15.13,
        "adx_14": 28.73,
        "rsi_14": 53.71,
        "atr_x_50": 2.44,
        "ccqs": 74.85,
        "grade": "B",
        "state": "TRENDING",
        "state_confidence": 0.671,
        "leadership_tier": "STRONG_PERFORMER",
        "setup": "Shallow Pullback",
        "setup_confidence": 1.0,
    },
    "MSFT": {
        "date": REFERENCE_DATE,
        "close": 418.57,
        "rs_rating_spy": 31.79,
        "pct_ma_50": 4.53,
        "pct_ma_200": -9.09,
        "adx_14": 17.09,
        "rsi_14": 54.42,
        "atr_x_50": 1.65,
        "ccqs": 25.65,
        "grade": "C",
        "state": "PULLBACK",
        "state_confidence": 0.428,
        "leadership_tier": "WEAK_PERFORMER",
        "setup": "",
        "setup_confidence": 0.0,
    },
    "META": {
        "date": REFERENCE_DATE,
        "close": 610.26,
        "rs_rating_spy": 29.72,
        "pct_ma_50": -1.22,
        "pct_ma_200": -8.84,
        "adx_14": 20.56,
        "rsi_14": 45.34,
        "atr_x_50": -0.49,
        "ccqs": 15.51,
        "grade": "D",
        "state": "DETERIORATING",
        "state_confidence": 0.811,
        "leadership_tier": "WEAK_PERFORMER",
        "setup": "",
        "setup_confidence": 0.0,
    },
    "GOOGL": {
        "date": REFERENCE_DATE,
        "close": 382.97,
        "rs_rating_spy": 86.82,
        "pct_ma_50": 12.26,
        "pct_ma_200": 29.30,
        "adx_14": 44.55,
        "rsi_14": 57.49,
        "atr_x_50": 4.23,
        "ccqs": 88.54,
        "grade": "A",
        "state": "TRENDING",
        "state_confidence": 0.768,
        "leadership_tier": "STRONG_PERFORMER",
        "setup": "Shallow Pullback",
        "setup_confidence": 1.0,
    },
    "TSLA": {
        "date": REFERENCE_DATE,
        "close": 426.01,
        "rs_rating_spy": 62.01,
        "pct_ma_50": 9.70,
        "pct_ma_200": 3.90,
        "adx_14": 21.05,
        "rsi_14": 58.30,
        "atr_x_50": 2.29,
        "ccqs": 63.88,
        "grade": "B",
        "state": "INDETERMINATE",
        "state_confidence": 0.549,
        "leadership_tier": "STRONG_PERFORMER",
        "setup": "",
        "setup_confidence": 0.0,
    },
    "AMZN": {
        "date": REFERENCE_DATE,
        "close": 266.32,
        "rs_rating_spy": 71.66,
        "pct_ma_50": 10.08,
        "pct_ma_200": 15.51,
        "adx_14": 31.12,
        "rsi_14": 57.98,
        "atr_x_50": 3.66,
        "ccqs": 84.49,
        "grade": "A",
        "state": "TRENDING",
        "state_confidence": 0.830,
        "leadership_tier": "STRONG_PERFORMER",
        "setup": "Coiling",
        "setup_confidence": 1.0,
    },
    "JPM": {
        "date": REFERENCE_DATE,
        "close": 306.38,
        "rs_rating_spy": 47.76,
        "pct_ma_50": 1.57,
        "pct_ma_200": 0.27,
        "adx_14": 20.08,
        "rsi_14": 52.69,
        "atr_x_50": 0.79,
        "ccqs": 45.50,
        "grade": "C",
        "state": "DETERIORATING",
        "state_confidence": 0.347,
        "leadership_tier": "NEUTRAL",
        "setup": "Sideways",
        "setup_confidence": 1.0,
    },
    "TSM": {
        "date": REFERENCE_DATE,
        "close": 404.52,
        "rs_rating_spy": 84.29,
        "pct_ma_50": 8.42,
        "pct_ma_200": 27.27,
        "adx_14": 19.94,
        "rsi_14": 55.46,
        "atr_x_50": 2.22,
        "ccqs": 86.79,
        "grade": "A",
        "state": "TRENDING",
        "state_confidence": 0.523,
        "leadership_tier": "STRONG_PERFORMER",
        "setup": "Coiling",
        "setup_confidence": 1.0,
    },
    "LLY": {
        "date": REFERENCE_DATE,
        "close": 1065.00,
        "rs_rating_spy": 65.57,
        "pct_ma_50": 12.90,
        "pct_ma_200": 14.73,
        "adx_14": 20.34,
        "rsi_14": 68.31,
        "atr_x_50": 4.03,
        "ccqs": 71.73,
        "grade": "B",
        "state": "INDETERMINATE",
        "state_confidence": 0.916,
        "leadership_tier": "STRONG_PERFORMER",
        "setup": "Extended",
        "setup_confidence": 1.0,
    },
    "UNH": {
        "date": REFERENCE_DATE,
        "close": 388.47,
        "rs_rating_spy": 76.48,
        "pct_ma_50": 17.49,
        "pct_ma_200": 19.89,
        "adx_14": 48.41,
        "rsi_14": 67.84,
        "atr_x_50": 6.26,
        "ccqs": 82.47,
        "grade": "B",
        "state": "TRENDING",
        "state_confidence": 0.588,
        "leadership_tier": "STRONG_PERFORMER",
        "setup": "Tight Base",
        "setup_confidence": 1.0,
    },
}
