"""CCQS — single-page analytical dashboard.

Five sections, sidebar filters, footer. No decoration; data carries every signal.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from app.utils.charts import ccqs_trajectory_chart
from app.utils.design_system import CUSTOM_CSS
from app.utils.data_loader import (
    get_emerging_leaders_today,
    get_grade_jumps_today,
    get_newly_broken_today,
    load_components_for_ticker,
    load_dashboard_data,
    load_grade_thresholds_history,
    load_key_metrics_for_ticker,
    load_oos_metrics,
    load_regime_context,
    load_themes_data,
    load_ticker_history,
    reliability_flags,
)
from app.utils.data_loader_sandbox import (
    load_sandbox_comparison_stocks,
    load_sandbox_dashboard_data,
    load_sandbox_diagnostics,
    load_sandbox_only_top_stocks,
    load_sandbox_themes_data,
    load_sandbox_top_by_basket,
    load_sandbox_validation_status,
)
from app.utils.tables import (
    component_table,
    emerging_leaders_table,
    grade_jumps_table,
    key_metrics_table,
    newly_broken_table,
    oos_ic_table,
    peers_table,
    themes_table,
    top_stocks_table,
)

# ---------------------------------------------------------------------------
# Page config — once per session
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="CCQS",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
df, snapshot_date = load_dashboard_data()
if df.empty:
    st.error("No CCQS data found. Run the pipeline to populate data/cache/.")
    st.stop()

# Regime context for Priority 3d display-layer warnings (no methodology change).
regime_ctx = load_regime_context()


# ---------------------------------------------------------------------------
# Sidebar filters (Leadership Tier + State only)
# ---------------------------------------------------------------------------
TIER_ORDER = [
    "ELITE_LEADER", "STRONG_LEADER", "EMERGING_LEADER", "ESTABLISHED_LEADER",
    "STRONG_PERFORMER", "NEUTRAL", "WEAK_PERFORMER", "DETERIORATING", "WEAK_LAGGARD",
]
STATE_ORDER = ["TRENDING", "PULLBACK", "CONSOLIDATING", "EXHAUSTION", "DETERIORATING", "INDETERMINATE"]

tiers_present = [t for t in TIER_ORDER if t in df["leadership_tier"].astype(str).unique()]
states_present = [s for s in STATE_ORDER if s in df["primary_state"].astype(str).unique()]

with st.sidebar:
    st.markdown("## Filters")
    selected_tiers = st.multiselect(
        "Leadership Tier",
        options=tiers_present,
        default=[],
        help="Restrict universe by leadership tier.",
    )
    selected_states = st.multiselect(
        "State",
        options=states_present,
        default=[],
        help="Restrict universe by primary state.",
    )

filtered = df.copy()
if selected_tiers:
    filtered = filtered[filtered["leadership_tier"].astype(str).isin(selected_tiers)]
if selected_states:
    filtered = filtered[filtered["primary_state"].astype(str).isin(selected_states)]


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown("# Composite Chart Quality Score")
st.markdown(
    f"<div class='meta'>{snapshot_date} · {len(df):,} names scored · "
    f"{len(filtered):,} after filters</div>",
    unsafe_allow_html=True,
)

# Priority 3d: top-of-page banner when SPY 20d realized vol is in the HIGH
# tercile. Honest disclosure — CCQS has documented negative IC at 60d/126d
# in this regime (Priority 2b). No methodology change; display-layer only.
_mv = regime_ctx.get("market_vol", {}) if regime_ctx else {}
if _mv.get("current_regime") == "HIGH":
    st.warning(
        "**Market volatility regime: HIGH.** SPY 20d realized vol "
        f"is {_mv.get('spy_vol_20d_latest', '?')} (≥ tercile threshold "
        f"{_mv.get('tercile_hi', '?')}). CCQS has documented IC of "
        "−0.014 at 60d and −0.025 at 126d in this regime (Priority 2b). "
        "Use the composite with reduced confidence today; consider "
        "shorter horizons or wait for the regime to normalize.",
        icon="⚠️",
    )


# ---------------------------------------------------------------------------
# Tabs: Production / Sandbox
# ---------------------------------------------------------------------------
# Sandbox tab is hidden from production dashboard but the code, loader, and
# data/cache/sandbox/ artefacts are preserved as a regression harness.
# Flip to True to re-enable the tab without re-running the sandbox pipeline.
SHOW_SANDBOX = False

if SHOW_SANDBOX:
    tab_production, tab_sandbox = st.tabs(["Production", "Sandbox (SP500 Expansion)"])
else:
    tab_production = st.container()


with tab_production:
    # -----------------------------------------------------------------------
    # Section 1 — Top Stocks
    # -----------------------------------------------------------------------
    st.markdown("<hr class='section-rule'/>", unsafe_allow_html=True)
    st.markdown("## Top Stocks")

    c1, c2 = st.columns([1, 5])
    with c1:
        n_top = st.selectbox("Rows", options=[25, 50, 100, 200], index=1, label_visibility="collapsed")

    top_df = filtered.sort_values("ccqs", ascending=False)
    st.plotly_chart(
        top_stocks_table(top_df, n=int(n_top)),
        use_container_width=True,
        config={"displayModeBar": False},
    )

    # -----------------------------------------------------------------------
    # Section 2 — Themes
    # -----------------------------------------------------------------------
    st.markdown("<hr class='section-rule'/>", unsafe_allow_html=True)
    st.markdown("## Themes")
    themes_df = load_themes_data()
    st.plotly_chart(
        themes_table(themes_df),
        use_container_width=True,
        config={"displayModeBar": False},
    )

    # -----------------------------------------------------------------------
    # Section 3 — What Changed Today
    # -----------------------------------------------------------------------
    st.markdown("<hr class='section-rule'/>", unsafe_allow_html=True)
    st.markdown("## What Changed Today")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown("### New Emerging Leaders")
        st.plotly_chart(
            emerging_leaders_table(get_emerging_leaders_today().head(15)),
            use_container_width=True,
            config={"displayModeBar": False},
        )
    with col_b:
        st.markdown("### Newly Deteriorating")
        st.plotly_chart(
            newly_broken_table(get_newly_broken_today().head(15)),
            use_container_width=True,
            config={"displayModeBar": False},
        )
    with col_c:
        st.markdown("### Grade Jumps")
        st.plotly_chart(
            grade_jumps_table(get_grade_jumps_today().head(15)),
            use_container_width=True,
            config={"displayModeBar": False},
        )

    # -----------------------------------------------------------------------
    # Section 4 — Stock Detail
    # -----------------------------------------------------------------------
    st.markdown("<hr class='section-rule'/>", unsafe_allow_html=True)
    st.markdown("## Stock Detail")

    tickers_sorted = sorted(filtered.index.astype(str).tolist())
    if not tickers_sorted:
        tickers_sorted = sorted(df.index.astype(str).tolist())

    default_idx = tickers_sorted.index("NVDA") if "NVDA" in tickers_sorted else 0
    sel = st.selectbox("Ticker", options=tickers_sorted, index=default_idx)

    if sel in df.index:
        row = df.loc[sel]
        header_bits = [
            f"<b>{sel}</b>",
            f"CCQS {row['ccqs']:.1f}",
            f"Grade {row['grade']}",
            f"{row['leadership_tier']}",
            f"{row['primary_state']}",
            f"{row['basket']}",
        ]
        st.markdown(
            "<div class='meta' style='font-size:0.9rem;color:rgb(60,64,72)'>"
            + "  ·  ".join(header_bits)
            + "</div>",
            unsafe_allow_html=True,
        )

        # Priority 3d: reliability flags chips. Honest disclosure of regimes
        # where CCQS has documented weaker signal (Priority 2b findings).
        # Display-layer only — CCQS values themselves are unchanged.
        flags = reliability_flags(
            ticker=str(sel),
            basket=str(row["basket"]) if pd.notna(row.get("basket")) else "",
            primary_state=str(row.get("primary_state", "")),
            regime_context=regime_ctx,
        )
        if flags:
            chips = []
            for f in flags:
                color = "#A87A00" if f["severity"] == "warn" else "#3D6A8C"
                bg = "#FFF4D6" if f["severity"] == "warn" else "#E7F0F8"
                chips.append(
                    f"<span title='{f['detail']}' "
                    f"style='display:inline-block;padding:2px 8px;margin:4px 6px 0 0;"
                    f"border:1px solid {color};background:{bg};color:{color};"
                    f"border-radius:10px;font-size:0.78rem;'>"
                    f"{f['label']}</span>"
                )
            st.markdown(
                "<div style='margin-top:8px;'>"
                "<span style='font-size:0.78rem;color:rgb(90,95,102);"
                "margin-right:6px;'>Reliability:</span>"
                + "".join(chips) + "</div>",
                unsafe_allow_html=True,
            )

        st.markdown("<br/>", unsafe_allow_html=True)
        left, right = st.columns([3, 2])
        with left:
            st.markdown("### Component Contributions")
            st.plotly_chart(
                component_table(load_components_for_ticker(sel)),
                use_container_width=True,
                config={"displayModeBar": False},
            )
        with right:
            st.markdown("### Key Metrics")
            st.plotly_chart(
                key_metrics_table(load_key_metrics_for_ticker(sel)),
                use_container_width=True,
                config={"displayModeBar": False},
            )

        st.markdown("### CCQS Trajectory")
        period_options = ["1W", "1M", "3M", "6M", "1Y", "3Y", "5Y", "INCEPTION"]
        period_sel = st.selectbox(
            "Period",
            options=period_options,
            index=period_options.index("6M"),
            label_visibility="collapsed",
            key=f"period_{sel}",
        )
        st.plotly_chart(
            ccqs_trajectory_chart(
                load_ticker_history(sel, period=period_sel),
                grade_thresholds=load_grade_thresholds_history(period=period_sel),
            ),
            use_container_width=True,
            config={"displayModeBar": False},
        )

        st.markdown("### Basket Peers")
        basket = row.get("basket")
        if isinstance(basket, str) and basket != "—":
            peers = df[df["basket"].astype(str) == basket].sort_values("ccqs", ascending=False).head(10)
        else:
            peers = df.head(0)
        st.plotly_chart(
            peers_table(peers, current_ticker=sel),
            use_container_width=True,
            config={"displayModeBar": False},
        )

    # -----------------------------------------------------------------------
    # Section 5 — System Health (expander)
    # -----------------------------------------------------------------------
    st.markdown("<hr class='section-rule'/>", unsafe_allow_html=True)
    with st.expander("System Health & Methodology", expanded=False):
        st.markdown("### Out-of-Sample IC · Composite CCQS")
        st.plotly_chart(
            oos_ic_table(load_oos_metrics()),
            use_container_width=True,
            config={"displayModeBar": False},
        )

        st.markdown("### Methodology")
        st.markdown(
            """
**CCQS** is a per-ticker composite of seven contributing standardized components
(post Phase 7): relative strength, RS leadership, RS-line behaviour, trend slope,
structure, multi-timeframe coherence, and extension. Two additional components
— `s_climax` (removed in Phase 6) and `s_demand` (zeroed in Phase 7 after the
Priority 2 bootstrap analysis showed it averaged −0.009 OOS IC) — are kept in
the schema as zero-weight diagnostics. `s_momentum` carries 1% in every state.
Each component is z-scored cross-sectionally per date, then combined with
state-conditional weights and a confidence-blended Bayesian average across the
six states.

The resulting score is per-date z-renormalized, mapped to 0–100 via the normal
CDF, then per-date winsorized at p1/p99. Grades S/A/B/C/D come from per-date
quantile cuts (top 8% → S, next 12% → A, etc.).

**Out-of-sample IC** is the Spearman rank correlation between today's CCQS and
forward returns at each horizon, evaluated on data the model never saw. A t-stat
above 2.0 indicates the signal is statistically distinguishable from noise.

**Component contributions** in stock detail are z × weight under the ticker's
current state. The sum (after rescale) approximates the CCQS itself; large
positive contributions are what's driving the score.

See **SPEC.md** for the full methodology spec, including the Phase 7 Priority 3a
validation, the Priority 2 bootstrap analysis of every weight cell, and the
Priority 3c finding on confidence-blending and per-state weight customization.
            """
        )

        st.markdown("### Where CCQS Works Best")
        st.markdown(
            """
Empirically validated regimes (Priority 2b, full-history OOS IC analysis):

- **Smaller dollar-volume stocks** — Q1 by 20d $-volume shows 60d IC = +0.048,
  126d IC = +0.061. Signal works strongest where the market is less efficient.
- **Moderate-to-high realized vol names** — Q3–Q5 by 60d realized vol show
  the largest IC magnitudes at 60d and 126d.
- **Low-to-mid market volatility regimes** — SPY 20d vol in the bottom or
  middle tercile: 60d IC = +0.040, 126d IC = +0.045.
- **Cyclical / recovery sectors** — top baskets by 60d IC include Hotels &
  Casinos (+0.21), Liquid Cooling (+0.18), Auto Affordability (+0.14),
  Oilfield Services (+0.14), Heavy Machinery (+0.10), Large-Cap Pharma (+0.10).
- **CONSOLIDATING state** — strongest single state, significant IC at all
  four horizons (5d, 20d, 60d, 126d).
- **Longer horizons (60d, 126d)** — 126d unconditional t = 7.4 in the per-date
  framework. Phase 7 walk-forward t = 2.0 at 126d.
            """
        )

        st.markdown("### Known Limitations")
        st.markdown(
            """
Documented regimes where CCQS shows reduced or negative predictive power
(Priority 2b conditional IC + Priority 3 simplification findings):

- **Mega-caps (top dollar-volume quintile)** — 60d IC = −0.017, 126d IC = −0.007.
  The composite has a known small-cap / inefficiency-premium bias.
- **High market-vol crises** — SPY 20d vol in the top tercile shows
  60d IC = −0.014, 126d IC = −0.025. Signal failure during stress events.
- **Defensive sectors** — Household & Personal Care, Gold Royalty, Integrated
  Energy Majors, Gaming Publishers, Railroads, Beverages, Diagnostics,
  Industrial Automation, Offshore Drilling, LNG Shipping all show
  significantly negative basket-level 60d IC. The composite carries a clear
  cyclical / non-defensive bias.
- **Speculative-euphoria regimes (e.g. 2021 meme/SPAC year)** — 2021 had
  negative IC at every horizon. The composite favours quality/momentum which
  underperforms in liquidity-driven low-quality rallies.
- **EXHAUSTION state at 20d** — uniquely flat (IC ≈ 0, t = −0.3). The composite
  cannot predict 20d returns for EXHAUSTION-state stocks; 5d and 126d still
  carry signal in this state.
- **COVID-2020 long horizons** — Phase 7 lost ~0.005 of 126d IC in 2020
  specifically, because `s_demand` had captured COVID-specific liquidity-shock
  signal that the carrier-only composite misses.

See SPEC.md "Phase 7" and "Priority 3 — Simplification investigation summary"
sections for the full bootstrap CIs, per-bucket IC numbers, and the
confidence-blending architectural caveat behind why Priority 3b/3c were not
implemented.
            """
        )


# ---------------------------------------------------------------------------
# Sandbox tab — parallel pipeline on SP500-expanded universe
# Hidden behind SHOW_SANDBOX flag. Imports/loader/cache remain intact so the
# regression harness keeps working from CLI; only the UI surface is gated.
# ---------------------------------------------------------------------------
if SHOW_SANDBOX:
    with tab_sandbox:
        sb_df, sb_snapshot = load_sandbox_dashboard_data()
        sb_diag = load_sandbox_diagnostics()
        sb_validation = load_sandbox_validation_status()

        if sb_df.empty:
            st.warning(
                "No sandbox data found. Run the sandbox pipeline to populate "
                "data/cache/sandbox/:  \n"
                "1. `python -m compute.sandbox.fetch_sp500`  \n"
                "2. `python -m compute.sandbox.pipeline_sandbox`  \n"
                "3. `python -m compute.sandbox.validate_sandbox`"
            )
        else:
            # ---- Header --------------------------------------------------------
            pm = sb_diag.get("pipeline_meta", {})
            ms = sb_diag.get("missing_equities_summary", {})
            qs = sb_diag.get("quality_status", {})
            n_total = pm.get("n_tickers_total", 0)
            n_prod = pm.get("n_tickers_production", 0)
            n_sb_only = pm.get("n_tickers_sandbox_only", 0)
            st.markdown(
                f"<div class='meta'>{sb_snapshot} · {n_total:,} names scored "
                f"({n_prod} production + {n_sb_only} SP500-only)</div>",
                unsafe_allow_html=True,
            )

            # ---- Sub-section A: Pipeline / Universe Summary --------------------
            st.markdown("<hr class='section-rule'/>", unsafe_allow_html=True)
            st.markdown("## Sandbox Build Summary")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.markdown("**Universe Expansion**")
                st.markdown(
                    f"- SP500 total: **{ms.get('sp500_total', 0)}**  \n"
                    f"- REITs excluded: **{ms.get('reits_excluded', 0)}**  \n"
                    f"- SP500 non-REIT: **{ms.get('sp500_after_reit_filter', 0)}**  \n"
                    f"- In production already: **{ms.get('in_both', 0)}**  \n"
                    f"- Missing equities: **{ms.get('missing_equities_count', 0)}**"
                )
            with col2:
                st.markdown("**Sandbox-only Quality**")
                st.markdown(
                    f"- Quality PASS: **{qs.get('sandbox_only_pass', 0)}**  \n"
                    f"- Quality WARNING: **{qs.get('sandbox_only_warning', 0)}**  \n"
                    f"- Quality FAIL: **{qs.get('sandbox_only_fail', 0)}**"
                )
            with col3:
                st.markdown("**Validation**")
                if sb_validation:
                    checks = sb_validation.get("checks", {})
                    overall = "PASS" if sb_validation.get("all_pass") else "FAIL"
                    st.markdown(f"- Overall: **{overall}**")
                    for name, r in checks.items():
                        status = "PASS" if r.get("pass") else "FAIL"
                        st.markdown(f"  - `{name}`: {status}")
                else:
                    st.markdown("- _validation report not present_")

            # ---- Sub-section B: Top 50 Sandbox-Only Stocks ---------------------
            st.markdown("<hr class='section-rule'/>", unsafe_allow_html=True)
            st.markdown("## Top Sandbox-Only Stocks")
            st.markdown(
                "<div class='meta'>Stocks present only because of the SP500 expansion "
                "— not in the production 879-name universe.</div>",
                unsafe_allow_html=True,
            )
            sb_only_top = load_sandbox_only_top_stocks(n=50)
            if sb_only_top.empty:
                st.info("No sandbox-only tickers in the latest snapshot.")
            else:
                st.plotly_chart(
                    top_stocks_table(sb_only_top, n=50),
                    use_container_width=True,
                    config={"displayModeBar": False},
                )

            # ---- Sub-section C: Production vs Sandbox (methodology stability) --
            st.markdown("<hr class='section-rule'/>", unsafe_allow_html=True)
            st.markdown("## Methodology Stability — Production vs Sandbox")
            st.markdown(
                "<div class='meta'>Top 20 production names by CCQS, scored under both "
                "the production and sandbox universes. Δ should be small (universe "
                "expansion shifts cross-sectional z's only slightly).</div>",
                unsafe_allow_html=True,
            )
            cmp_df = load_sandbox_comparison_stocks(anchors=None)
            if cmp_df.empty:
                st.info("No comparison data available.")
            else:
                mean_abs = float(cmp_df["abs_delta"].mean())
                max_abs = float(cmp_df["abs_delta"].max())
                st.markdown(
                    f"**Mean |Δ| = {mean_abs:.2f}   ·   Max |Δ| = {max_abs:.2f}**"
                )
                st.dataframe(
                    cmp_df.assign(
                        ccqs_prod=cmp_df["ccqs_prod"].round(2),
                        ccqs_sandbox=cmp_df["ccqs_sandbox"].round(2),
                        delta=cmp_df["delta"].round(2),
                        abs_delta=cmp_df["abs_delta"].round(2),
                    ),
                    use_container_width=True,
                )

            # ---- Sub-section D: Sandbox Themes ---------------------------------
            st.markdown("<hr class='section-rule'/>", unsafe_allow_html=True)
            st.markdown("## Themes (Production + SP500 GICS Baskets)")
            sb_themes = load_sandbox_themes_data()
            if sb_themes.empty:
                st.info("No theme aggregates available.")
            else:
                st.plotly_chart(
                    themes_table(sb_themes),
                    use_container_width=True,
                    config={"displayModeBar": False},
                )

            # ---- Sub-section E: Sector-specific visibility ---------------------
            st.markdown("<hr class='section-rule'/>", unsafe_allow_html=True)
            st.markdown("## Sector-Specific Visibility (SP500 GICS Baskets)")
            st.markdown(
                "<div class='meta'>Top 10 names per SP500 GICS basket — sectors where "
                "production coverage was thin (utilities, materials, staples) gain "
                "the most.</div>",
                unsafe_allow_html=True,
            )
            sb_basket_focus = [
                "SP500_UTILITIES",
                "SP500_MATERIALS",
                "SP500_CONSUMER_STAPLES",
            ]
            sec_cols = st.columns(len(sb_basket_focus))
            for col, b in zip(sec_cols, sb_basket_focus):
                with col:
                    st.markdown(f"**{b}**")
                    top_b = load_sandbox_top_by_basket(b, n=10)
                    if top_b.empty:
                        st.markdown("_no data_")
                    else:
                        st.plotly_chart(
                            top_stocks_table(top_b, n=10),
                            use_container_width=True,
                            config={"displayModeBar": False},
                        )


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown(
    "<div class='footer'>© 2026 AD Fund Management LP</div>",
    unsafe_allow_html=True,
)
