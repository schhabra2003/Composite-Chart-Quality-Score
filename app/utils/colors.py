"""Color encoding functions. Pastel palette only; color encodes data, never decorates."""
from __future__ import annotations

import pandas as pd


PASTEL = [
    "#4c78a8", "#f58518", "#54a24b", "#e45756", "#72b7b2",
    "#b279a2", "#ff9da6", "#9d755d", "#bab0ac", "#59a14f",
    "#edc948", "#af7aa1", "#ff9da7", "#76b7b2", "#8cd17d",
    "#b6992d", "#499894", "#d37295", "#fabfd2", "#79706e",
]
PASTEL_GREEN = "#52b788"
PASTEL_RED = "#e85d5d"
PASTEL_GREY = "#8b949e"


def color_ret(x):
    """% return columns. Pastel green-red gradient capped at ±20%."""
    if pd.isna(x):
        return "white"
    if x >= 0:
        s = min(abs(x) / 20.0, 1.0)
        r = int(240 + (82 - 240) * s)
        g = int(255 + (183 - 255) * s)
        b = int(245 + (136 - 245) * s)
    else:
        s = min(abs(x) / 20.0, 1.0)
        r = int(255 + (232 - 255) * s)
        g = int(245 + (93 - 245) * s)
        b = int(245 + (93 - 245) * s)
    return f"rgb({r},{g},{b})"


def color_ccqs(x):
    """CCQS 0-100. Blue gradient: light low, deep high."""
    if pd.isna(x):
        return "white"
    s = min(x / 100.0, 1.0)
    r = int(248 - 60 * s)
    g = int(250 - 20 * s)
    b = int(252)
    return f"rgb({r},{g},{b})"


def color_tier(t):
    if not isinstance(t, str):
        return "white"
    return {
        "ELITE_LEADER":       "rgb(255,237,170)",
        "STRONG_LEADER":      "rgb(190,220,255)",
        "EMERGING_LEADER":    "rgb(190,235,190)",
        "ESTABLISHED_LEADER": "rgb(215,225,250)",
        "STRONG_PERFORMER":   "rgb(220,232,255)",
        "NEUTRAL":            "rgb(240,240,240)",
        "WEAK_PERFORMER":     "rgb(255,228,228)",
        "DETERIORATING":      "rgb(255,220,200)",
        "WEAK_LAGGARD":       "rgb(255,210,210)",
    }.get(t, "white")


def color_state(s):
    if not isinstance(s, str):
        return "white"
    return {
        "TRENDING":  "rgb(204,238,204)",
        "PULLBACK":  "rgb(230,236,245)",
        "COILING":   "rgb(255,237,170)",
        "CLIMACTIC": "rgb(255,210,210)",
        "BROKEN":    "rgb(255,200,200)",
        "MIXED":     "rgb(240,240,240)",
    }.get(s, "white")


def color_theme_class(c):
    if not isinstance(c, str):
        return "white"
    return {
        "ELITE_THEME":       "rgb(255,237,170)",
        "STRONG_THEME":      "rgb(190,220,255)",
        "EMERGING_THEME":    "rgb(190,235,190)",
        "NARROW_LEADERSHIP": "rgb(215,225,250)",
        "STABLE":            "rgb(240,240,240)",
        "WEAKENING":         "rgb(255,220,200)",
        "BROKEN_THEME":      "rgb(255,210,210)",
        "MIXED":             "rgb(245,245,245)",
    }.get(c, "white")


def color_momentum(c):
    """Theme momentum class. Pastel palette mapped by accel→decel sentiment."""
    if not isinstance(c, str):
        return "white"
    return {
        "STRONG_ACCELERATING":   "rgb(190,235,190)",
        "MODERATE_ACCELERATING": "rgb(215,240,215)",
        "STABLE":                "rgb(240,240,240)",
        "DECELERATING":          "rgb(255,220,200)",
        "WEAKENING":             "rgb(255,210,210)",
    }.get(c, "white")


def color_z_score(z):
    """Z-scores. Symmetric green-red around 0."""
    if pd.isna(z):
        return "white"
    if z >= 0:
        s = min(z / 2.0, 1.0)
        return f"rgb({int(240 - 50*s)},{int(255 - 20*s)},{int(245 - 50*s)})"
    s = min(abs(z) / 2.0, 1.0)
    return f"rgb(255,{int(245 - 35*s)},{int(245 - 35*s)})"


def color_significance(t_stat):
    """t-stat coloring. Green if |t|>2, yellow if borderline."""
    if pd.isna(t_stat):
        return "white"
    abs_t = abs(t_stat)
    if abs_t >= 2.0:
        return "rgb(204,238,204)"
    if abs_t >= 1.5:
        return "rgb(255,237,170)"
    return "rgb(240,240,240)"


def color_pass_fail(status):
    if status == "PASS" or status is True:
        return "rgb(204,238,204)"
    if status == "FAIL" or status is False:
        return "rgb(255,210,210)"
    return "white"
