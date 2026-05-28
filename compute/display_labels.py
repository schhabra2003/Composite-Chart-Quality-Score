"""Phase 26 — Display-layer label translation (state + leadership tier).

Single source of truth for converting internal classifier labels (the
ALL_CAPS strings written to `data/cache/dashboard/{state,leadership}.parquet`)
into the user-facing display strings rendered on the Streamlit dashboard
and in any user-facing artifact.

Architecture principle (Phase 26 design):
  - Internal labels (TRENDING, EXHAUSTION, STRONG_PERFORMER, ...) are
    the contract between the classifier (`compute/state.py`,
    `compute/leadership.py`) and the methodology layer
    (STATE_WEIGHTS lookup in `compute/ccqs.py`, regime gates, tier
    composition logic). These MUST remain unchanged.
  - Display strings (Trending, Parabolic, Steady, ...) are a render-time
    translation applied at the dashboard / report rendering boundary.
  - Parquet files store internal labels. The TV reference parity test
    compares internal labels and is therefore unaffected.

Five renames + one consolidation (per Phase 26 spec):

  State (3 of 6 change, 3 keep)
    TRENDING       → Trending
    PULLBACK       → Pullback
    CONSOLIDATING  → Consolidating
    EXHAUSTION     → Parabolic       (descriptive, not predictive)
    DETERIORATING  → Breaking Down   (resolves state/tier collision)
    INDETERMINATE  → No Edge         (honest about residual meaning)

  Leadership Tier (3 of 10 change + NaN consolidation, 6 kept as Title Case)
    ELITE_LEADER         → Elite Leader
    STRONG_LEADER        → Strong Leader
    ESTABLISHED_LEADER   → Established Leader
    EMERGING_LEADER      → Emerging Leader
    STRONG_PERFORMER     → Steady           ("Strong Performer" overpromised)
    NEUTRAL              → Neutral
    WEAK_PERFORMER       → Weak Performer
    DETERIORATING        → Fading Leader    (resolves state/tier collision)
    WEAK_LAGGARD         → Weak Laggard
    UNCLASSIFIED         → No RS Signal
    NaN                  → No RS Signal     (consolidation — same display)

No methodology change. CCQS scores, components, regime, setup labels,
state confidences, and tier composition logic are unaffected — the
internal labels they key on are unchanged. Only the user-facing
display strings on the dashboard change.
"""
from __future__ import annotations

import pandas as pd


STATE_DISPLAY_LABELS: dict[str, str] = {
    "TRENDING":      "Trending",
    "PULLBACK":      "Pullback",
    "CONSOLIDATING": "Consolidating",
    "EXHAUSTION":    "Parabolic",
    "DETERIORATING": "Breaking Down",
    "INDETERMINATE": "No Edge",
}


TIER_DISPLAY_LABELS: dict[str, str] = {
    "ELITE_LEADER":       "Elite Leader",
    "STRONG_LEADER":      "Strong Leader",
    "ESTABLISHED_LEADER": "Established Leader",
    "EMERGING_LEADER":    "Emerging Leader",
    "STRONG_PERFORMER":   "Steady",
    "NEUTRAL":            "Neutral",
    "WEAK_PERFORMER":     "Weak Performer",
    "DETERIORATING":      "Fading Leader",
    "WEAK_LAGGARD":       "Weak Laggard",
    "UNCLASSIFIED":       "No RS Signal",
}


# Reverse maps for "display → internal" lookups (used by sidebar filters
# that present display labels to the user but filter the dataframe on
# the internal column values).
STATE_INTERNAL_FROM_DISPLAY: dict[str, str] = {
    v: k for k, v in STATE_DISPLAY_LABELS.items()
}
TIER_INTERNAL_FROM_DISPLAY: dict[str, str] = {
    v: k for k, v in TIER_DISPLAY_LABELS.items()
}


# Display string for "no leadership signal" — used for both the
# UNCLASSIFIED internal label and NaN (insufficient RS history).
NO_RS_SIGNAL_DISPLAY = "No RS Signal"


def display_state(state_value) -> str:
    """Translate one internal state label → display string.

    NaN / None / empty → "". Unknown values pass through untouched
    (defensive: surfaces unexpected labels rather than masking them).
    """
    if state_value is None or (isinstance(state_value, float) and pd.isna(state_value)):
        return ""
    s = str(state_value)
    if s in ("nan", "NaN", "None", ""):
        return ""
    return STATE_DISPLAY_LABELS.get(s, s)


def display_tier(tier_value) -> str:
    """Translate one internal tier label → display string.

    NaN (insufficient RS history) → "No RS Signal" (consolidation with
    UNCLASSIFIED). Unknown values pass through untouched.
    """
    if tier_value is None or (isinstance(tier_value, float) and pd.isna(tier_value)):
        return NO_RS_SIGNAL_DISPLAY
    t = str(tier_value)
    if t in ("nan", "NaN", "None", ""):
        return NO_RS_SIGNAL_DISPLAY
    return TIER_DISPLAY_LABELS.get(t, t)


def translate_state_series(series: pd.Series) -> pd.Series:
    """Vectorized state translation. Preserves index."""
    return series.map(display_state)


def translate_tier_series(series: pd.Series) -> pd.Series:
    """Vectorized tier translation. Preserves index. NaN → "No RS Signal"."""
    return series.map(display_tier)
