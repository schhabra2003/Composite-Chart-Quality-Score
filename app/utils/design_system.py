"""Standardized design system for CCQS dashboard.

ALL visual values import from this module. No hardcoded values elsewhere.

Sections:
  - Page layout
  - Brand colors (ADFM)
  - Chart colors / palette
  - Chart styling defaults
  - Table styling defaults
  - Component / UI styling
  - CUSTOM_CSS (single source of truth for the dashboard)
  - Utility builders for Plotly tables and chart axes
"""
from __future__ import annotations


# ===========================================================================
# PAGE LAYOUT
# ===========================================================================
PAGE_MAX_WIDTH = 1700   # px
PADDING_TOP = 1.2       # rem
PADDING_BOTTOM = 2      # rem


# ===========================================================================
# COLORS — ADFM Brand
# ===========================================================================
ADFM_NAVY = "#0A1F44"
ADFM_GOLD = "#C9A867"
ADFM_BLUE = "#4c78a8"   # primary chart blue (matches PASTEL[0])


# ===========================================================================
# COLORS — Charts
# ===========================================================================
BENCHMARK_COLOR = "#888"     # gray for SPY dashed lines
PASTEL_GREEN = "#52b788"
PASTEL_RED = "#e85d5d"
PASTEL_GREY = "#8b949e"

# Multi-line pastel palette (kept aligned with legacy app/utils/colors.PASTEL).
PASTEL = [
    "#4c78a8", "#f58518", "#54a24b", "#e45756", "#72b7b2",
    "#b279a2", "#ff9da6", "#9d755d", "#bab0ac", "#59a14f",
    "#edc948", "#af7aa1", "#ff9da7", "#76b7b2", "#8cd17d",
    "#b6992d", "#499894", "#d37295", "#fabfd2", "#79706e",
]


# ===========================================================================
# CHART STYLING
# ===========================================================================
CHART_BACKGROUND = "white"
CHART_TITLE_SIZE = 14
CHART_TITLE_WEIGHT = 600
CHART_LINE_WIDTH = 2
CHART_BENCHMARK_DASH = "dash"
CHART_MARGINS = dict(l=10, r=10, t=35, b=10)
CHART_HEIGHT_SMALL = 240        # compact charts
CHART_HEIGHT_STANDARD = 280     # default
CHART_HEIGHT_LARGE = 340        # multi-line / cumulative

# Default chart layout (used by most charts)
CHART_LAYOUT_DEFAULTS = dict(
    plot_bgcolor=CHART_BACKGROUND,
    paper_bgcolor=CHART_BACKGROUND,
    margin=CHART_MARGINS,
    height=CHART_HEIGHT_STANDARD,
    hovermode="x unified",
    showlegend=False,
)

CHART_LAYOUT_MULTILINE = dict(
    plot_bgcolor=CHART_BACKGROUND,
    paper_bgcolor=CHART_BACKGROUND,
    margin=CHART_MARGINS,
    height=CHART_HEIGHT_LARGE,
    hovermode="x unified",
    showlegend=True,
)


# ===========================================================================
# TABLE STYLING
# ===========================================================================
TABLE_HEADER_HEIGHT = 32
TABLE_ROW_HEIGHT = 26
TABLE_HEADER_FONT_SIZE = 13
TABLE_CELL_FONT_SIZE = 12
TABLE_HEADER_BORDER = "rgb(230,230,230)"
TABLE_CELL_BORDER = "rgb(240,240,240)"
TABLE_HEADER_BG = "white"
TABLE_FONT_FAMILY = "sans-serif"
TABLE_FONT_COLOR = "black"
TABLE_ALIGN = "left"
TABLE_MAX_HEIGHT = 920          # max table height before scroll


# ===========================================================================
# COMPONENT / UI STYLING
# ===========================================================================
EXPANDER_BORDER = "rgb(230,230,230)"


# ===========================================================================
# CUSTOM CSS (single source of truth for the dashboard)
# ===========================================================================
CUSTOM_CSS = """
<style>
    /* Page layout */
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2rem;
        max-width: 1700px;
    }

    /* Typography */
    h1, h2, h3 {
        font-weight: 600;
        letter-spacing: 0.15px;
    }

    /* Section spacing */
    .stMarkdown h2 {
        margin-top: 24px;
        margin-bottom: 12px;
    }
    .stMarkdown h3 {
        margin-top: 16px;
        margin-bottom: 8px;
    }

    /* Plotly chart consistency */
    .stPlotlyChart { background: #ffffff; }
    .stPlotlyChart > div { margin-bottom: 8px; }
    .js-plotly-plot .table .cell { font-size: 12px; }

    /* Sidebar */
    .sidebar-content { padding-top: 0.5rem; }

    /* Hide Streamlit branding */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    .stDeployButton { visibility: hidden; }

    /* Selectbox consistency */
    .stSelectbox > div > div { border-radius: 4px; }

    /* Multiselect consistency */
    .stMultiSelect > div > div { border-radius: 4px; }

    /* Section rule */
    .section-rule {
        border: 0;
        border-top: 1px solid rgb(232, 234, 237);
        margin: 1rem 0 0.75rem 0;
    }

    /* Meta caption */
    .meta {
        font-size: 0.8rem;
        color: rgb(120, 124, 132);
        font-family: -apple-system, system-ui, sans-serif;
    }

    /* Footer */
    .footer {
        margin-top: 2.5rem;
        padding-top: 1rem;
        border-top: 1px solid rgb(232, 234, 237);
        font-size: 0.78rem;
        color: rgb(140, 144, 152);
        text-align: left;
    }
</style>
"""


# ===========================================================================
# UTILITY BUILDERS — Plotly tables
# ===========================================================================

def get_table_layout(n_rows: int, height_override: int | None = None) -> dict:
    """Return standard Plotly figure-layout dict for tables."""
    height = height_override or min(
        TABLE_MAX_HEIGHT,
        64 + TABLE_ROW_HEIGHT * max(3, n_rows),
    )
    return dict(
        margin=dict(l=0, r=0, t=6, b=0),
        height=height,
    )


def get_table_header_config(headers) -> dict:
    """Return standard `header=dict(...)` config for go.Table."""
    return dict(
        values=headers,
        fill_color=TABLE_HEADER_BG,
        line_color=TABLE_HEADER_BORDER,
        font=dict(
            color=TABLE_FONT_COLOR,
            size=TABLE_HEADER_FONT_SIZE,
            family=TABLE_FONT_FAMILY,
        ),
        align=TABLE_ALIGN,
        height=TABLE_HEADER_HEIGHT,
    )


def get_table_cells_config(values, fill_colors, formats=None) -> dict:
    """Return standard `cells=dict(...)` config for go.Table."""
    cells = dict(
        values=values,
        fill_color=fill_colors,
        line_color=TABLE_CELL_BORDER,
        font=dict(
            color=TABLE_FONT_COLOR,
            size=TABLE_CELL_FONT_SIZE,
            family=TABLE_FONT_FAMILY,
        ),
        align=TABLE_ALIGN,
        height=TABLE_ROW_HEIGHT,
    )
    if formats is not None:
        cells["format"] = formats
    return cells


def get_chart_axis_config(showgrid: bool = False, showline: bool = True, range=None) -> dict:
    """Return standard axis config for charts."""
    config = dict(
        showgrid=showgrid,
        showline=showline,
        linecolor="rgb(230,230,230)",
        zeroline=True,
        zerolinecolor="rgb(230,230,230)",
    )
    if range is not None:
        config["range"] = range
    return config
