"""Plotly go.Table builders. The ONLY table primitive used in the app.

Cells encode data through `fill_color`; nothing else carries meaning.
All visual constants imported from app.utils.design_system.
"""
from __future__ import annotations

from typing import Sequence

import pandas as pd
import plotly.graph_objects as go

from app.utils.colors import (
    color_ccqs,
    color_momentum,
    color_ret,
    color_significance,
    color_state,
    color_theme_class,
    color_tier,
    color_z_score,
)
from compute.display_labels import display_state, display_tier  # Phase 26
from app.utils.design_system import (
    CHART_BACKGROUND,
    TABLE_CELL_BORDER,
    TABLE_CELL_FONT_SIZE,
    TABLE_FONT_COLOR,
    TABLE_FONT_FAMILY,
    TABLE_HEADER_BG,
    TABLE_HEADER_BORDER,
    TABLE_HEADER_FONT_SIZE,
    TABLE_HEADER_HEIGHT,
    TABLE_MAX_HEIGHT,
    TABLE_ROW_HEIGHT,
)

WHITE = CHART_BACKGROUND
PALE_GOLD = "rgb(255,248,220)"   # peers-table current-row highlight


# ---------------------------------------------------------------------------
# Universal renderer
# ---------------------------------------------------------------------------

def render_table(
    headers: Sequence[str],
    values: Sequence[Sequence],
    fill_colors: Sequence[Sequence[str]],
    col_widths: Sequence[int],
    aligns: Sequence[str] | None = None,
    height: int | None = None,
) -> go.Figure:
    """Render a Plotly go.Table with the analytical aesthetic.

    Args:
        headers: column titles
        values: list-of-columns (Plotly orientation)
        fill_colors: list-of-columns of background colors, same shape as values
        col_widths: relative column widths
        aligns: per-column horizontal alignment (default 'left' for first col, 'right' rest)
        height: total figure height (default scales with row count via design_system)
    """
    n_cols = len(headers)
    if aligns is None:
        aligns = ["left"] + ["right"] * (n_cols - 1)

    n_rows = len(values[0]) if values and len(values) else 0
    if height is None:
        height = min(
            TABLE_MAX_HEIGHT,
            TABLE_HEADER_HEIGHT + 8 + TABLE_ROW_HEIGHT * max(n_rows, 1),
        )

    fig = go.Figure(data=[go.Table(
        columnwidth=list(col_widths),
        header=dict(
            values=[f"<b>{h}</b>" for h in headers],
            fill_color=TABLE_HEADER_BG,
            line=dict(color=TABLE_HEADER_BORDER, width=1),
            font=dict(
                color=TABLE_FONT_COLOR,
                size=TABLE_HEADER_FONT_SIZE,
                family=TABLE_FONT_FAMILY,
            ),
            align=aligns,
            height=TABLE_HEADER_HEIGHT,
        ),
        cells=dict(
            values=list(values),
            fill_color=list(fill_colors),
            line=dict(color=TABLE_CELL_BORDER, width=1),
            font=dict(
                color=TABLE_FONT_COLOR,
                size=TABLE_CELL_FONT_SIZE,
                family=TABLE_FONT_FAMILY,
            ),
            align=aligns,
            height=TABLE_ROW_HEIGHT,
        ),
    )])
    fig.update_layout(
        margin=dict(l=0, r=0, t=4, b=4),
        height=height,
        paper_bgcolor=WHITE,
        plot_bgcolor=WHITE,
    )
    return fig


# ---------------------------------------------------------------------------
# Internal formatters
# ---------------------------------------------------------------------------

def _fmt_signed(v, digits: int = 2) -> str:
    if pd.isna(v):
        return "—"
    return f"{float(v):+.{digits}f}"


def _fmt_num(v, digits: int = 2) -> str:
    if pd.isna(v):
        return "—"
    return f"{float(v):,.{digits}f}"


def _fmt_int(v) -> str:
    if pd.isna(v):
        return "—"
    return f"{int(v):,}"


def _fmt_pct(v, digits: int = 1) -> str:
    if pd.isna(v):
        return "—"
    return f"{float(v):.{digits}f}%"


def _fmt_signed_pct(v, digits: int = 1) -> str:
    if pd.isna(v):
        return "—"
    return f"{float(v):+.{digits}f}%"


def _whites(n: int) -> list[str]:
    return [WHITE] * n


# ---------------------------------------------------------------------------
# 1. Top Stocks (9 columns) — Phase 18: replaced single RS + Δ Today with
# three Δ CCQS columns (1-day / 5-day / 21-day).
# ---------------------------------------------------------------------------

TOP_STOCKS_COL_WIDTHS = [0.10, 0.22, 0.08, 0.14, 0.11, 0.17, 0.06, 0.06, 0.06]
TOP_STOCKS_HEADERS = [
    "Ticker", "Theme", "CCQS", "Leadership Tier", "State", "Setup",
    "Δ 1d", "Δ 5d", "Δ 21d",
]
TOP_STOCKS_ALIGNS = [
    "left", "left", "right", "left", "left", "left", "right", "right", "right",
]


def top_stocks_table(df: pd.DataFrame, n: int = 50) -> go.Figure:
    """Ticker, Theme, CCQS, Leadership Tier, State, Setup, Δ 1d, Δ 5d, Δ 21d."""
    if df.empty:
        return render_table(
            TOP_STOCKS_HEADERS,
            [["—"]] * len(TOP_STOCKS_HEADERS),
            [_whites(1)] * len(TOP_STOCKS_HEADERS),
            TOP_STOCKS_COL_WIDTHS,
            aligns=TOP_STOCKS_ALIGNS,
        )

    d = df.head(n).copy()
    tickers = [str(t) for t in d.index]
    themes = d["basket"].astype(str).tolist()
    ccqs_vals = d["ccqs"].astype(float).tolist()
    tiers = d["leadership_tier"].astype(str).tolist()           # internal — colors key on these
    states = d["primary_state"].astype(str).tolist()            # internal — colors key on these
    setups = d["setup_label"].astype(str).tolist()
    # Phase 26 — translate to display strings at the render boundary only.
    # Colors above are computed from the internal labels (color_tier / color_state).
    tiers_disp = [display_tier(t) for t in tiers]
    states_disp = [display_state(s) for s in states]
    # Δ CCQS at three trading-day horizons. ccqs_change_5d / 21d are added
    # in load_dashboard_data (Phase 18); ccqs_change kept for back-compat
    # with peers / sandbox paths.
    chg_1d = d.get("ccqs_change_1d", d.get("ccqs_change", pd.Series(float("nan"), index=d.index))).astype(float).tolist()
    chg_5d = d.get("ccqs_change_5d", pd.Series(float("nan"), index=d.index)).astype(float).tolist()
    chg_21d = d.get("ccqs_change_21d", pd.Series(float("nan"), index=d.index)).astype(float).tolist()

    n_rows = len(d)
    fill_cols = [
        _whites(n_rows),                            # Ticker
        _whites(n_rows),                            # Theme
        [color_ccqs(v) for v in ccqs_vals],         # CCQS
        [color_tier(t) for t in tiers],             # Leadership Tier (color from internal)
        [color_state(s) for s in states],           # State (color from internal)
        _whites(n_rows),                            # Setup
        [color_ret(v) for v in chg_1d],             # Δ 1d
        [color_ret(v) for v in chg_5d],             # Δ 5d
        [color_ret(v) for v in chg_21d],            # Δ 21d
    ]
    return render_table(
        headers=TOP_STOCKS_HEADERS,
        values=[
            tickers,
            themes,
            [_fmt_num(v, 1) for v in ccqs_vals],
            tiers_disp,                              # Phase 26 display string
            states_disp,                             # Phase 26 display string
            setups,
            [_fmt_signed(v, 2) for v in chg_1d],
            [_fmt_signed(v, 2) for v in chg_5d],
            [_fmt_signed(v, 2) for v in chg_21d],
        ],
        fill_colors=fill_cols,
        col_widths=TOP_STOCKS_COL_WIDTHS,
        aligns=TOP_STOCKS_ALIGNS,
    )


# ---------------------------------------------------------------------------
# 2. Themes (6 columns) — Phase 18:
#   • Dropped "Members" count column (cardinality metadata, not insight)
#   • Dropped "% Grade A+" column (overlaps with % > 50-day MA breadth)
#   • Added "Constituents" column listing all basket tickers (sorted by CCQS
#     desc) so users can cross-check on charting platforms / brokerages
# ---------------------------------------------------------------------------

THEMES_HEADERS = [
    "Theme", "Theme CCQS", "Theme Class", "Momentum",
    "% > 50d MA", "Top Member", "Constituents",
]
# Widened Theme Class (fits NARROW_LEADERSHIP, 17 chars) and Momentum
# (fits MODERATE_ACCELERATING, 21 chars) without truncation; tightened
# % > 50d MA header (data is "100%" / "88%" / "71%", short).
THEMES_COL_WIDTHS = [0.17, 0.07, 0.13, 0.16, 0.07, 0.07, 0.33]
THEMES_ALIGNS = ["left", "right", "left", "left", "right", "left", "left"]


def themes_table(df: pd.DataFrame) -> go.Figure:
    """Theme, Theme CCQS, Theme Class, Momentum, % > 50-day MA, Top Member,
    Constituents."""
    if df.empty:
        return render_table(
            THEMES_HEADERS,
            [["—"]] * len(THEMES_HEADERS),
            [_whites(1)] * len(THEMES_HEADERS),
            THEMES_COL_WIDTHS,
            aligns=THEMES_ALIGNS,
        )

    d = df.copy()
    baskets = d["basket_name"].astype(str).tolist()
    ccqs_vals = d["theme_ccqs"].astype(float).tolist()
    classes = d["theme_class"].astype(str).tolist()
    momentum = d["momentum_class"].astype(str).tolist()
    pct_50_vals = d["pct_above_50dma"].astype(float).tolist()
    top_members = d["top_member"].astype(str).tolist()
    members = d.get(
        "members", pd.Series(["—"] * len(d), index=d.index)
    ).astype(str).tolist()

    n_rows = len(d)
    fill_cols = [
        _whites(n_rows),                                       # Theme
        [color_ccqs(v) for v in ccqs_vals],                    # Theme CCQS
        [color_theme_class(c) for c in classes],               # Theme Class
        [color_momentum(m) for m in momentum],                 # Momentum
        _whites(n_rows),                                       # % > 50-day MA
        _whites(n_rows),                                       # Top Member
        _whites(n_rows),                                       # Constituents
    ]
    return render_table(
        headers=THEMES_HEADERS,
        values=[
            baskets,
            [_fmt_num(v, 1) for v in ccqs_vals],
            classes,
            momentum,
            [_fmt_pct(v, 0) for v in pct_50_vals],
            top_members,
            members,
        ],
        fill_colors=fill_cols,
        col_widths=THEMES_COL_WIDTHS,
        aligns=THEMES_ALIGNS,
    )


# ---------------------------------------------------------------------------
# 3-5. What Changed Today — three small tables
# ---------------------------------------------------------------------------

def emerging_leaders_table(df: pd.DataFrame) -> go.Figure:
    """Ticker, New Tier, CCQS."""
    if df.empty:
        return render_table(
            ["Ticker", "New Tier", "CCQS"],
            [["—"], ["—"], ["—"]],
            [_whites(1)] * 3,
            [70, 150, 70],
        )
    d = df.copy()
    tickers = [str(t) for t in d.index]
    tiers = d["leadership_tier"].astype(str).tolist()             # internal
    tiers_disp = [display_tier(t) for t in tiers]                  # Phase 26 display
    ccqs_vals = d["ccqs"].astype(float).tolist()
    n_rows = len(d)
    fill_cols = [
        _whites(n_rows),
        [color_tier(t) for t in tiers],
        [color_ccqs(v) for v in ccqs_vals],
    ]
    return render_table(
        headers=["Ticker", "New Tier", "CCQS"],
        values=[tickers, tiers_disp, [_fmt_num(v, 1) for v in ccqs_vals]],
        fill_colors=fill_cols,
        col_widths=[70, 150, 70],
        aligns=["left", "left", "right"],
    )


def newly_broken_table(df: pd.DataFrame) -> go.Figure:
    """Ticker, From State, Δ CCQS."""
    if df.empty:
        return render_table(
            ["Ticker", "From State", "Δ CCQS"],
            [["—"], ["—"], ["—"]],
            [_whites(1)] * 3,
            [70, 110, 80],
        )
    d = df.copy()
    tickers = [str(t) for t in d.index]
    prev_states = d["prev_state"].astype(str).tolist()             # internal
    prev_states_disp = [display_state(s) for s in prev_states]      # Phase 26 display
    changes = d["ccqs_change"].astype(float).tolist()
    n_rows = len(d)
    fill_cols = [
        _whites(n_rows),
        [color_state(s) for s in prev_states],
        [color_ret(v) for v in changes],
    ]
    return render_table(
        headers=["Ticker", "From State", "Δ CCQS"],
        values=[tickers, prev_states_disp, [_fmt_signed(v, 2) for v in changes]],
        fill_colors=fill_cols,
        col_widths=[70, 110, 80],
        aligns=["left", "left", "right"],
    )


def grade_jumps_table(df: pd.DataFrame) -> go.Figure:
    """Ticker, Move, Δ CCQS."""
    if df.empty:
        return render_table(
            ["Ticker", "Move", "Δ CCQS"],
            [["—"], ["—"], ["—"]],
            [_whites(1)] * 3,
            [70, 100, 80],
        )
    d = df.copy()
    tickers = [str(t) for t in d.index]
    moves = d["grade_move"].astype(str).tolist()
    changes = d["ccqs_change"].astype(float).tolist()
    n_rows = len(d)
    fill_cols = [
        _whites(n_rows),
        _whites(n_rows),
        [color_ret(v) for v in changes],
    ]
    return render_table(
        headers=["Ticker", "Move", "Δ CCQS"],
        values=[tickers, moves, [_fmt_signed(v, 2) for v in changes]],
        fill_colors=fill_cols,
        col_widths=[70, 100, 80],
        aligns=["left", "center", "right"],
    )


# ---------------------------------------------------------------------------
# Stock detail tables
# ---------------------------------------------------------------------------

def component_table(df: pd.DataFrame) -> go.Figure:
    """Component, Z-Score, Weight, Contribution — sorted by |contribution|."""
    if df.empty:
        return render_table(
            ["Component", "Z-Score", "Weight", "Contribution"],
            [["—"], ["—"], ["—"], ["—"]],
            [_whites(1)] * 4,
            [180, 80, 80, 100],
        )
    d = df.copy()
    comps = d["component"].astype(str).tolist()
    zs = d["z_score"].astype(float).tolist()
    weights = d["weight"].astype(float).tolist()
    contribs = d["contribution"].astype(float).tolist()
    n_rows = len(d)
    fill_cols = [
        _whites(n_rows),
        [color_z_score(z) for z in zs],
        _whites(n_rows),
        [color_z_score(c) for c in contribs],
    ]
    return render_table(
        headers=["Component", "Z-Score", "Weight", "Contribution"],
        values=[
            comps,
            [_fmt_signed(z, 2) for z in zs],
            [_fmt_num(w, 2) for w in weights],
            [_fmt_signed(c, 3) for c in contribs],
        ],
        fill_colors=fill_cols,
        col_widths=[180, 80, 80, 100],
        aligns=["left", "right", "right", "right"],
    )


def key_metrics_table(df: pd.DataFrame) -> go.Figure:
    """Metric, Value — 8 rows of pre-formatted metrics."""
    if df.empty:
        return render_table(
            ["Metric", "Value"],
            [["—"], ["—"]],
            [_whites(1)] * 2,
            [200, 120],
        )
    d = df.copy()
    metrics = d["metric"].astype(str).tolist()
    values = d["value"].astype(str).tolist()
    n_rows = len(d)
    return render_table(
        headers=["Metric", "Value"],
        values=[metrics, values],
        fill_colors=[_whites(n_rows), _whites(n_rows)],
        col_widths=[200, 120],
        aligns=["left", "right"],
    )


def peers_table(df: pd.DataFrame, current_ticker: str) -> go.Figure:
    """Ticker, Theme, CCQS, Leadership Tier, State, Setup, Δ 1d, Δ 5d, Δ 21d —
    same shape as top_stocks_table. Current ticker row highlighted."""
    if df.empty:
        return render_table(
            TOP_STOCKS_HEADERS,
            [["—"]] * len(TOP_STOCKS_HEADERS),
            [_whites(1)] * len(TOP_STOCKS_HEADERS),
            TOP_STOCKS_COL_WIDTHS,
            aligns=TOP_STOCKS_ALIGNS,
        )
    d = df.copy()
    tickers = [str(t) for t in d.index]
    themes = d["basket"].astype(str).tolist()
    ccqs_vals = d["ccqs"].astype(float).tolist()
    tiers = d["leadership_tier"].astype(str).tolist()              # internal
    states = d["primary_state"].astype(str).tolist()               # internal
    setups = d["setup_label"].astype(str).tolist()
    # Phase 26 — translate to display strings at the render boundary only.
    tiers_disp = [display_tier(t) for t in tiers]
    states_disp = [display_state(s) for s in states]
    chg_1d = d.get("ccqs_change_1d", d.get("ccqs_change", pd.Series(float("nan"), index=d.index))).astype(float).tolist()
    chg_5d = d.get("ccqs_change_5d", pd.Series(float("nan"), index=d.index)).astype(float).tolist()
    chg_21d = d.get("ccqs_change_21d", pd.Series(float("nan"), index=d.index)).astype(float).tolist()

    is_current = [t == current_ticker for t in tickers]

    def _hl(default_color: str, current: bool) -> str:
        return PALE_GOLD if current else default_color

    fill_cols = [
        [_hl(WHITE, c) for c in is_current],                                                # Ticker
        [_hl(WHITE, c) for c in is_current],                                                # Theme
        [_hl(color_ccqs(v), c) for c, v in zip(is_current, ccqs_vals)],                     # CCQS
        [_hl(color_tier(t), c) for c, t in zip(is_current, tiers)],                         # Leadership Tier (color from internal)
        [_hl(color_state(s), c) for c, s in zip(is_current, states)],                       # State (color from internal)
        [_hl(WHITE, c) for c in is_current],                                                # Setup
        [_hl(color_ret(v), c) for c, v in zip(is_current, chg_1d)],                         # Δ 1d
        [_hl(color_ret(v), c) for c, v in zip(is_current, chg_5d)],                         # Δ 5d
        [_hl(color_ret(v), c) for c, v in zip(is_current, chg_21d)],                        # Δ 21d
    ]
    return render_table(
        headers=TOP_STOCKS_HEADERS,
        values=[
            tickers,
            themes,
            [_fmt_num(v, 1) for v in ccqs_vals],
            tiers_disp,                              # Phase 26 display string
            states_disp,                             # Phase 26 display string
            setups,
            [_fmt_signed(v, 2) for v in chg_1d],
            [_fmt_signed(v, 2) for v in chg_5d],
            [_fmt_signed(v, 2) for v in chg_21d],
        ],
        fill_colors=fill_cols,
        col_widths=TOP_STOCKS_COL_WIDTHS,
        aligns=TOP_STOCKS_ALIGNS,
    )


# ---------------------------------------------------------------------------
# System Health — OOS IC
# ---------------------------------------------------------------------------

def oos_ic_table(df: pd.DataFrame) -> go.Figure:
    """Horizon, OOS IC, t-stat, Hit Rate."""
    if df.empty:
        return render_table(
            ["Horizon", "OOS IC", "t-stat", "Hit Rate"],
            [["—"], ["—"], ["—"], ["—"]],
            [_whites(1)] * 4,
            [80, 90, 80, 90],
        )
    d = df.copy()
    horizons = d["horizon"].astype(str).tolist()
    ics = d["oos_ic"].astype(float).tolist()
    ts = d["t_stat"].astype(float).tolist()
    hits = d["hit_rate"].astype(float).tolist()
    n_rows = len(d)
    fill_cols = [
        _whites(n_rows),
        [color_z_score(v * 10) for v in ics],
        [color_significance(t) for t in ts],
        _whites(n_rows),
    ]
    return render_table(
        headers=["Horizon", "OOS IC", "t-stat", "Hit Rate"],
        values=[
            horizons,
            [_fmt_signed(v, 3) for v in ics],
            [_fmt_signed(t, 2) for t in ts],
            [_fmt_pct(v * 100 if abs(v) <= 1 else v, 1) for v in hits],
        ],
        fill_colors=fill_cols,
        col_widths=[80, 90, 80, 90],
        aligns=["center", "right", "right", "right"],
    )
