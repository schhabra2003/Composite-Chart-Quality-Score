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
# 1. Top Stocks (8 columns)
# ---------------------------------------------------------------------------

TOP_STOCKS_COL_WIDTHS = [0.09, 0.20, 0.08, 0.14, 0.11, 0.18, 0.08, 0.12]
TOP_STOCKS_HEADERS = ["Ticker", "Theme", "CCQS", "Tier", "State", "Setup", "RS", "Δ Today"]
TOP_STOCKS_ALIGNS = ["left", "left", "right", "left", "left", "left", "right", "right"]


def top_stocks_table(df: pd.DataFrame, n: int = 50) -> go.Figure:
    """Ticker, Theme, CCQS, Tier, State, Setup, RS, Δ Today."""
    if df.empty:
        return render_table(
            TOP_STOCKS_HEADERS,
            [["—"]] * 8,
            [_whites(1)] * 8,
            TOP_STOCKS_COL_WIDTHS,
            aligns=TOP_STOCKS_ALIGNS,
        )

    d = df.head(n).copy()
    tickers = [str(t) for t in d.index]
    themes = d["basket"].astype(str).tolist()
    ccqs_vals = d["ccqs"].astype(float).tolist()
    tiers = d["leadership_tier"].astype(str).tolist()
    states = d["primary_state"].astype(str).tolist()
    setups = d["setup_label"].astype(str).tolist()
    rs = d["rs_rating_spy"].tolist()
    change_vals = d["ccqs_change"].astype(float).tolist()

    n_rows = len(d)
    fill_cols = [
        _whites(n_rows),                            # Ticker
        _whites(n_rows),                            # Theme
        [color_ccqs(v) for v in ccqs_vals],         # CCQS
        [color_tier(t) for t in tiers],             # Tier
        [color_state(s) for s in states],           # State
        _whites(n_rows),                            # Setup
        _whites(n_rows),                            # RS
        [color_ret(v) for v in change_vals],        # Δ Today
    ]
    return render_table(
        headers=TOP_STOCKS_HEADERS,
        values=[
            tickers,
            themes,
            [_fmt_num(v, 1) for v in ccqs_vals],
            tiers,
            states,
            setups,
            [_fmt_int(v) for v in rs],
            [_fmt_signed(v, 2) for v in change_vals],
        ],
        fill_colors=fill_cols,
        col_widths=TOP_STOCKS_COL_WIDTHS,
        aligns=TOP_STOCKS_ALIGNS,
    )


# ---------------------------------------------------------------------------
# 2. Themes (7 columns)
# ---------------------------------------------------------------------------

THEMES_HEADERS = [
    "Theme", "Theme CCQS", "Theme Class", "Momentum",
    "Members", "% > 50DMA", "% Grade A+", "Top Member",
]
THEMES_COL_WIDTHS = [0.20, 0.10, 0.13, 0.13, 0.07, 0.08, 0.08, 0.21]
THEMES_ALIGNS = ["left", "right", "left", "left", "right", "right", "right", "left"]


def themes_table(df: pd.DataFrame) -> go.Figure:
    """Theme, Theme CCQS, Theme Class, Momentum, Members, % > 50DMA, % Grade A+, Top Member."""
    if df.empty:
        return render_table(
            THEMES_HEADERS,
            [["—"]] * 8,
            [_whites(1)] * 8,
            THEMES_COL_WIDTHS,
            aligns=THEMES_ALIGNS,
        )

    d = df.copy()
    baskets = d["basket_name"].astype(str).tolist()
    ccqs_vals = d["theme_ccqs"].astype(float).tolist()
    classes = d["theme_class"].astype(str).tolist()
    momentum = d["momentum_class"].astype(str).tolist()
    n_vals = d["n_constituents"].astype(int).tolist()
    pct_50_vals = d["pct_above_50dma"].astype(float).tolist()
    pct_a_vals = d["pct_grade_a_plus"].astype(float).tolist()
    top_members = d["top_member"].astype(str).tolist()

    n_rows = len(d)
    fill_cols = [
        _whites(n_rows),                                       # Theme
        [color_ccqs(v) for v in ccqs_vals],                    # Theme CCQS
        [color_theme_class(c) for c in classes],               # Theme Class
        [color_momentum(m) for m in momentum],                 # Momentum
        _whites(n_rows),                                       # Members
        _whites(n_rows),                                       # % > 50DMA
        _whites(n_rows),                                       # % Grade A+
        _whites(n_rows),                                       # Top Member
    ]
    return render_table(
        headers=THEMES_HEADERS,
        values=[
            baskets,
            [_fmt_num(v, 1) for v in ccqs_vals],
            classes,
            momentum,
            [_fmt_int(v) for v in n_vals],
            [_fmt_pct(v, 0) for v in pct_50_vals],
            [_fmt_pct(v, 0) for v in pct_a_vals],
            top_members,
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
    tiers = d["leadership_tier"].astype(str).tolist()
    ccqs_vals = d["ccqs"].astype(float).tolist()
    n_rows = len(d)
    fill_cols = [
        _whites(n_rows),
        [color_tier(t) for t in tiers],
        [color_ccqs(v) for v in ccqs_vals],
    ]
    return render_table(
        headers=["Ticker", "New Tier", "CCQS"],
        values=[tickers, tiers, [_fmt_num(v, 1) for v in ccqs_vals]],
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
    prev_states = d["prev_state"].astype(str).tolist()
    changes = d["ccqs_change"].astype(float).tolist()
    n_rows = len(d)
    fill_cols = [
        _whites(n_rows),
        [color_state(s) for s in prev_states],
        [color_ret(v) for v in changes],
    ]
    return render_table(
        headers=["Ticker", "From State", "Δ CCQS"],
        values=[tickers, prev_states, [_fmt_signed(v, 2) for v in changes]],
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
    """Ticker, Theme, CCQS, Tier, State, Setup, RS, Δ Today — same shape as
    top_stocks_table. Current ticker row highlighted in pale gold."""
    if df.empty:
        return render_table(
            TOP_STOCKS_HEADERS,
            [["—"]] * 8,
            [_whites(1)] * 8,
            TOP_STOCKS_COL_WIDTHS,
            aligns=TOP_STOCKS_ALIGNS,
        )
    d = df.copy()
    tickers = [str(t) for t in d.index]
    themes = d["basket"].astype(str).tolist()
    ccqs_vals = d["ccqs"].astype(float).tolist()
    tiers = d["leadership_tier"].astype(str).tolist()
    states = d["primary_state"].astype(str).tolist()
    setups = d["setup_label"].astype(str).tolist()
    rs = d["rs_rating_spy"].tolist()
    change_vals = d["ccqs_change"].astype(float).tolist()

    is_current = [t == current_ticker for t in tickers]

    def _hl(default_color: str, current: bool) -> str:
        return PALE_GOLD if current else default_color

    fill_cols = [
        [_hl(WHITE, c) for c in is_current],                                                # Ticker
        [_hl(WHITE, c) for c in is_current],                                                # Theme
        [_hl(color_ccqs(v), c) for c, v in zip(is_current, ccqs_vals)],                     # CCQS
        [_hl(color_tier(t), c) for c, t in zip(is_current, tiers)],                         # Tier
        [_hl(color_state(s), c) for c, s in zip(is_current, states)],                       # State
        [_hl(WHITE, c) for c in is_current],                                                # Setup
        [_hl(WHITE, c) for c in is_current],                                                # RS
        [_hl(color_ret(v), c) for c, v in zip(is_current, change_vals)],                    # Δ Today
    ]
    return render_table(
        headers=TOP_STOCKS_HEADERS,
        values=[
            tickers,
            themes,
            [_fmt_num(v, 1) for v in ccqs_vals],
            tiers,
            states,
            setups,
            [_fmt_int(v) for v in rs],
            [_fmt_signed(v, 2) for v in change_vals],
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
