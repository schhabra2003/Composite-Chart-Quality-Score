"""Phase 26 — Display-label translation tests.

Validates the contract for the display-layer rename:

  1. Internal labels in `data/cache/dashboard/{state,leadership}.parquet`
     remain unchanged (classifier output bit-identical to pre-Phase 26).
  2. STATE_WEIGHTS lookup still resolves for every internal state label.
  3. The display-translation functions map every internal label and
     handle NaN per the consolidation rule (tier NaN → "No RS Signal").
  4. Coverage distributions of display labels equal those of internal
     labels (detection is unchanged).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from compute.ccqs import STATE_WEIGHTS
from compute.display_labels import (
    NO_RS_SIGNAL_DISPLAY,
    STATE_DISPLAY_LABELS,
    STATE_INTERNAL_FROM_DISPLAY,
    TIER_DISPLAY_LABELS,
    TIER_INTERNAL_FROM_DISPLAY,
    display_state,
    display_tier,
    translate_state_series,
    translate_tier_series,
)

CACHE = Path("data/cache/dashboard")

INTERNAL_STATES = [
    "TRENDING", "PULLBACK", "CONSOLIDATING",
    "EXHAUSTION", "DETERIORATING", "INDETERMINATE",
]
INTERNAL_TIERS = [
    "ELITE_LEADER", "STRONG_LEADER", "EMERGING_LEADER", "ESTABLISHED_LEADER",
    "STRONG_PERFORMER", "NEUTRAL", "WEAK_PERFORMER", "DETERIORATING",
    "WEAK_LAGGARD", "UNCLASSIFIED",
]


# ---------------------------------------------------------------------------
# 1. Display-mapping correctness
# ---------------------------------------------------------------------------

def test_state_map_covers_all_internal():
    assert set(STATE_DISPLAY_LABELS) == set(INTERNAL_STATES)


def test_tier_map_covers_all_internal():
    assert set(TIER_DISPLAY_LABELS) == set(INTERNAL_TIERS)


def test_specific_renames():
    """The 3+3 renames from the Phase 26 spec."""
    assert STATE_DISPLAY_LABELS["EXHAUSTION"] == "Parabolic"
    assert STATE_DISPLAY_LABELS["DETERIORATING"] == "Breaking Down"
    assert STATE_DISPLAY_LABELS["INDETERMINATE"] == "No Edge"
    assert TIER_DISPLAY_LABELS["STRONG_PERFORMER"] == "Steady"
    assert TIER_DISPLAY_LABELS["DETERIORATING"] == "Fading Leader"
    assert TIER_DISPLAY_LABELS["UNCLASSIFIED"] == "No RS Signal"


def test_no_collision_between_state_and_tier_displays():
    """Phase 26 resolves the DETERIORATING collision."""
    state_disp = set(STATE_DISPLAY_LABELS.values())
    tier_disp = set(TIER_DISPLAY_LABELS.values())
    overlap = state_disp & tier_disp
    assert overlap == set(), f"display strings collide between state and tier: {overlap}"


def test_kept_labels_title_cased():
    """The 3 state + 6 tier labels that were kept use Title Case display."""
    assert STATE_DISPLAY_LABELS["TRENDING"] == "Trending"
    assert STATE_DISPLAY_LABELS["PULLBACK"] == "Pullback"
    assert STATE_DISPLAY_LABELS["CONSOLIDATING"] == "Consolidating"
    for internal in ("ELITE_LEADER", "STRONG_LEADER", "ESTABLISHED_LEADER",
                     "EMERGING_LEADER", "NEUTRAL", "WEAK_PERFORMER", "WEAK_LAGGARD"):
        # Generic check: display string is the internal label title-cased
        # (with underscores → spaces), to confirm "kept" semantics.
        expected = internal.replace("_", " ").title()
        assert TIER_DISPLAY_LABELS[internal] == expected, (
            f"{internal!r} should render Title Case, got {TIER_DISPLAY_LABELS[internal]!r}"
        )


def test_nan_tier_consolidates_to_no_rs_signal():
    assert display_tier(np.nan) == NO_RS_SIGNAL_DISPLAY
    assert display_tier(None) == NO_RS_SIGNAL_DISPLAY
    assert display_tier("UNCLASSIFIED") == NO_RS_SIGNAL_DISPLAY


def test_nan_state_returns_blank():
    """State NaN displays as empty string (residual catch-all, no chip)."""
    assert display_state(np.nan) == ""
    assert display_state(None) == ""


def test_reverse_maps_are_inverses():
    for internal, display in STATE_DISPLAY_LABELS.items():
        assert STATE_INTERNAL_FROM_DISPLAY[display] == internal
    for internal, display in TIER_DISPLAY_LABELS.items():
        assert TIER_INTERNAL_FROM_DISPLAY[display] == internal


# ---------------------------------------------------------------------------
# 2. Methodology lookup preservation — STATE_WEIGHTS must still resolve
# ---------------------------------------------------------------------------

def test_state_weights_resolves_for_every_internal_state():
    """STATE_WEIGHTS keys MUST remain the internal labels post-Phase 26."""
    for state in INTERNAL_STATES:
        assert state in STATE_WEIGHTS, (
            f"STATE_WEIGHTS lost key {state!r} — Phase 26 must not "
            f"rename methodology lookup keys."
        )


# ---------------------------------------------------------------------------
# 3. Parquet still stores internal labels (Pattern A invariant)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def latest_state() -> pd.DataFrame:
    df = pd.read_parquet(CACHE / "state.parquet")
    latest = df.index.get_level_values("date").max()
    return df.xs(latest, level="date")


@pytest.fixture(scope="module")
def latest_tier() -> pd.DataFrame:
    df = pd.read_parquet(CACHE / "leadership.parquet")
    latest = df.index.get_level_values("date").max()
    return df.xs(latest, level="date")


def test_state_parquet_stores_internal_labels(latest_state):
    """The parquet column MUST hold ALL_CAPS internal values, not display strings."""
    present = set(latest_state["primary_state"].astype(str).unique())
    invalid = present - set(INTERNAL_STATES)
    assert not invalid, f"non-internal values in state.parquet: {invalid}"


def test_tier_parquet_stores_internal_labels(latest_tier):
    """The parquet column MUST hold ALL_CAPS internal values (NaN allowed)."""
    present = set(latest_tier["leadership_tier"].astype(str).unique()) - {"nan", "None"}
    invalid = present - set(INTERNAL_TIERS)
    assert not invalid, f"non-internal values in leadership.parquet: {invalid}"


# ---------------------------------------------------------------------------
# 4. Coverage invariance — display distribution equals internal distribution
# ---------------------------------------------------------------------------

def test_state_coverage_invariant_under_translation(latest_state):
    """Counts per display label must equal counts per internal label."""
    internal_counts = latest_state["primary_state"].astype(str).value_counts()
    translated = translate_state_series(latest_state["primary_state"].astype(str))
    display_counts = translated.value_counts()
    for internal, n in internal_counts.items():
        display = STATE_DISPLAY_LABELS[internal]
        assert display_counts.get(display, 0) == n, (
            f"state {internal} (n={n}) does not map 1:1 to display "
            f"{display!r} (n={display_counts.get(display, 0)})"
        )


def test_tier_coverage_invariant_under_translation_with_nan_consolidation(latest_tier):
    """Display distribution = internal distribution; NaN folds into 'No RS Signal'."""
    internal = latest_tier["leadership_tier"].astype(object)
    translated = translate_tier_series(internal)
    # Sum of UNCLASSIFIED + NaN internal counts should equal "No RS Signal" display count.
    n_unclassified = int((internal == "UNCLASSIFIED").sum())
    n_nan = int(internal.isna().sum())
    n_no_rs_signal_display = int((translated == NO_RS_SIGNAL_DISPLAY).sum())
    assert n_no_rs_signal_display == n_unclassified + n_nan, (
        f"NaN consolidation broke: NaN={n_nan} + UNCLASSIFIED={n_unclassified} "
        f"!= display 'No RS Signal'={n_no_rs_signal_display}"
    )
    # All non-NaN, non-UNCLASSIFIED tiers preserve their counts exactly.
    for tier in INTERNAL_TIERS:
        if tier == "UNCLASSIFIED":
            continue
        n_internal = int((internal == tier).sum())
        display = TIER_DISPLAY_LABELS[tier]
        n_display = int((translated == display).sum())
        assert n_display == n_internal, (
            f"tier {tier} (n={n_internal}) does not map 1:1 to display "
            f"{display!r} (n={n_display})"
        )
