# CCQS V1 — User Guide

**How to interpret the output.** Last updated 2026-05-26 (Path C complete, methodology baseline Phase 11E.2).

This guide complements `SPEC.md`. SPEC is the authoritative methodology document; this guide is the user-facing interpretation manual.

---

## TL;DR

CCQS V1 is **NOT** a single continuous "buy/sell" score. It is a **categorical screening + within-category ranking tool**. Use it in two steps:

1. **First, filter by classification** (leadership tier, state, setup) — this is the primary forward-return signal (97.3% of cross-sectional R²).
2. **Then rank within the filtered set by CCQS** — but only in high-quality regimes. In low-quality regimes (WEAK_LAGGARD, DETERIORATING tier), CCQS ranking **inverts** (mean reversion dominates).

The dashboard's reliability chips (green / amber) tell you which regime the current stock is in.

---

## A. What CCQS V1 actually is

CCQS V1 produces three outputs for every (stock, date):

1. **CCQS score** (0–100) — a continuous quality / momentum composite.
2. **Three classification layers**:
   - **State** (6 values): cycle position — TRENDING, PULLBACK, CONSOLIDATING, EXHAUSTION, DETERIORATING, INDETERMINATE.
   - **Setup** (27 values): specific technical pattern detected.
   - **Tier** (10 values): RS-quality classification — ELITE_LEADER, STRONG_LEADER, EMERGING_LEADER, ESTABLISHED_LEADER, STRONG_PERFORMER, NEUTRAL, WEAK_PERFORMER, DETERIORATING, WEAK_LAGGARD, UNCLASSIFIED.
3. **Grade** (S / A / B / C / D) — per-date quantile bucket of CCQS.

**The classifications carry 97.3% of the system's cross-sectional R² at 60d forward returns. CCQS itself carries 2.7%.**

The CCQS score is the within-category ranking key; the classifications are the screening filter.

---

## B. How to use the output (recommended workflow)

1. **Decide your strategy** — quality investing, mean reversion, momentum continuation, etc.
2. **Filter by tier** that matches your strategy:
   - Quality investing → tier in {ELITE_LEADER, STRONG_LEADER, ESTABLISHED_LEADER}
   - Mean reversion → tier in {WEAK_LAGGARD, DETERIORATING}
   - Pattern-driven → no tier filter, use setup filter
3. **Filter by state** if relevant (e.g., TRENDING for continuation, EXHAUSTION for parabolic-bounce, CONSOLIDATING for breakout-watch).
4. **Filter by setup** for a specific pattern (e.g., "Volume-Confirmed Exhaustion" for parabolic-with-volume-climax).
5. **Within the filtered set, rank by CCQS** to surface the top-of-cohort candidates — but only if the dashboard shows the **green "High-quality regime — CCQS reliable" chip**. If it shows the **amber "Low-quality regime — CCQS may invert" chip**, consider ranking ascending instead (lowest CCQS first) or use CCQS only for screening, not ranking.

---

## C. Regime-aware CCQS interpretation

Phase 11D empirically established that CCQS works in some regimes and inverts in others.

### High-quality regimes (CCQS works as expected) — GREEN chip

Top-CCQS-decile minus Bottom-CCQS-decile spread at 60d:

| Tier | Q10 − Q1 spread | Interpretation |
| ---- | ---------------- | -------------- |
| ELITE_LEADER | (small n) | Top tier — trust CCQS |
| STRONG_LEADER | +3.22% | CCQS works |
| ESTABLISHED_LEADER | +5.26% | CCQS works strongly |

In these tiers, the dashboard shows a green chip: "High-quality regime — CCQS reliable". Higher CCQS predicts higher forward returns.

### Middle regimes (CCQS minimal value) — NO chip

| Tier | Q10 − Q1 spread |
| ---- | ---------------- |
| STRONG_PERFORMER | +3.04% (modest) |
| NEUTRAL | −0.48% (flat) |
| WEAK_PERFORMER | +0.56% |

CCQS has small or negligible ranking power in these tiers. No chip is shown.

### Low-quality regimes (CCQS inverts) — AMBER chip

| Tier | Q10 − Q1 spread | Interpretation |
| ---- | ---------------- | -------------- |
| EMERGING_LEADER | −0.82% | Slightly inverted |
| DETERIORATING (tier) | −1.93% | Slightly inverted |
| **WEAK_LAGGARD** | **−9.24%** | Strongly inverted — mean reversion dominates |

In WEAK_LAGGARD and DETERIORATING tiers, the dashboard shows an amber chip: "Low-quality regime — CCQS may invert". The LOWEST CCQS decile actually outperforms the highest by up to 9.24pp at 60d. Mean reversion of extremes dominates the ranking signal.

If you want to do a mean-reversion screen, this is exactly the cohort to look at — but rank ASCENDING by CCQS (lowest first), not descending.

---

## D. Understanding the classification layers

### D.1 State machine (6 values, Phase 11A validated)

States describe the stock's CURRENT CYCLE POSITION. They do NOT predict forward direction.

| State | Definition | 60d mean return | t vs universe |
| ----- | ---------- | --------------- | ------------- |
| EXHAUSTION | Parabolic / late-stage | **+9.32%** | +20.8 (above) |
| INDETERMINATE | Transitional / no clear regime | +6.33% | +22.4 (above) |
| DETERIORATING | Structurally damaged | +5.68% | +11.7 (above) |
| Universe | — | +5.20% | — |
| TRENDING | Clean uptrend in progress | +4.23% | −22.7 (**BELOW**) |
| PULLBACK | Buyable pullback in uptrend | +4.13% | −26.7 (**BELOW**) |
| CONSOLIDATING | Pre-breakout consolidation | +2.70% | −30.6 (**BELOW**) |

**Surprising but empirically true:** TRENDING and PULLBACK stocks UNDERPERFORM the universe mean. The "obvious quality" market has already priced them in. EXHAUSTION stocks OUTPERFORM (momentum continuation). The state machine is a CONTEXT classifier, NOT a buy/sell signal.

State persistence is reasonable (72.3% local stability — same state as both yesterday and tomorrow). DETERIORATING is the stickiest state (mean 12.9-day run); PULLBACK is the noisiest active state (mean 3.6-day run).

### D.2 Setup classifier (27 values, Phase 11B validated)

Setups describe a SPECIFIC TECHNICAL PATTERN. First-match-wins along a priority cascade.

**Top-edge setups** (significantly above universe at 60d):

| Setup | n | μ 60d | Δ vs uni |
| ----- | - | ----- | -------- |
| Volume-Confirmed Exhaustion | 478 | +16.70% | +11.50% |
| Exhaustion (Generic) | (n>1000) | +12.74% | +7.54% |
| Capitulation Selling | 2,870+ | +11.26% | +6.06% |
| Elite Leader Continuation | (rare) | +11.20% | +6.00% |
| Sustained Weakness | 87,960 | +10.19% | +4.99% |
| Distribution Pattern | 95,536 | +9.62% | +4.42% |
| Deteriorating w/ Bullish Divergence | 57,534 | +9.20% | +4.00% |
| Trending Leadership | 40,491 | +7.89% | +2.69% |
| Trend Continuation | 44,005 | +7.46% | +2.26% |
| BB Squeeze with RS | 7,750 | +7.19% | +1.99% |
| Pullback to 21EMA | 25,002 | +6.08% | +0.88% |
| Pullback to 50MA | 14,010 | +5.97% | +0.77% |

**Underperforming setups** (the "premium label, no alpha" pattern):

| Setup | n | μ 60d | t vs uni |
| ----- | - | ----- | -------- |
| Extended Exhaustion | 18,141 | +4.81% | −2.91 |
| Premium Pullback | 10,245 | +4.62% | −2.72 |
| Failed Breakout | 25,973 | +4.54% | −5.02 |
| Theme Leader Pullback | 58,974 | +4.47% | −7.29 |
| VCP Setup | 4,270 | +3.91% | −4.60 |

**Lesson:** Setups branded as "Premium / Quality / Leader / VCP" UNDERPERFORM universe. The market has already priced in the obvious-quality signal. Setups branded as "Weakness / Distribution / Exhaustion" OUTPERFORM because that's where mean reversion lives.

### D.3 Leadership tier (10 values, Phase 11C validated, Phase 11.C.1 patched)

Tiers describe CURRENT RS-QUALITY POSITION. The hierarchy is NOT monotonic in forward returns.

| Tier | Definition | μ 60d | Population |
| ---- | ---------- | ----- | ---------- |
| ELITE_LEADER | s_lead ≥ 90 + rs_spy ≥ 95 + 4 confirms | **+15.24%** | 0.18% |
| STRONG_LEADER | s_lead ≥ 80 + rs_spy ≥ 75 + mtf ≥ 2 | +6.32% | 1.15% |
| EMERGING_LEADER | rs_spy 60-85 + slope ≥ 10 + mtf ≥ 2 + qqq ok | +4.68% (UNDER universe) | 5.86% |
| ESTABLISHED_LEADER | rs_spy ≥ 75 + RS Line new high | +6.61% | 1.51% |
| STRONG_PERFORMER | rs_spy ≥ 60 | +7.04% | 24.29% |
| NEUTRAL | rs_spy 45-60 | +5.90% | 12.59% |
| WEAK_PERFORMER | rs_spy 25-45 + slope ≥ −5 | +4.41% (UNDER universe) | 8.05% |
| DETERIORATING | rs_spy < 40 + slope < −5 | +4.82% (UNDER universe) | 17.50% |
| WEAK_LAGGARD | rs_spy < 25 + slope < 0 | +7.02% | 2.95% |
| UNCLASSIFIED | Doesn't fit any specific tier (Phase 11.C.1) | varies | 8.63% |

**Critical takeaway:** Only ELITE_LEADER has a truly distinctive forward-return edge. All other 8 tiers cluster within ±2.5pp of universe. The tier label tells you what KIND of leadership profile the stock has TODAY — not what will happen next.

---

## E. Specific guidance by use case

### E.1 Quality investing

Filter:
- `leadership_tier ∈ {ELITE_LEADER}` (or include STRONG_LEADER, ESTABLISHED_LEADER for breadth)
- `primary_state ∈ {TRENDING, EXHAUSTION}` (continuation regimes)
- Rank by CCQS descending — trust the green-chip regime

Watch out for: ELITE_LEADER in EXHAUSTION state has the HIGHEST joint forward return (+22% at 60d) — but these stocks are parabolic with high vol. Position sizing matters.

### E.2 Mean reversion

Filter:
- `leadership_tier ∈ {WEAK_LAGGARD, DETERIORATING}`
- `primary_state ∈ {INDETERMINATE, DETERIORATING}` (state-level mean reversion is strongest in these)
- Look at setups like `Distribution Pattern`, `Sustained Weakness`, `Deteriorating w/ Bullish Divergence`
- Rank by CCQS **ASCENDING** (lowest first — that's where the strongest mean reversion lives in WEAK_LAGGARD)
- Heed the amber chip — CCQS ranking inverts here

Top-of-the-list 3D cells from Phase 11D (highest empirical 60d mean returns):
- INDETERMINATE × Deteriorating w/ Bullish Divergence × UNCLASSIFIED: +43.5%
- INDETERMINATE × Distribution Pattern × UNCLASSIFIED: +37.5%
- INDETERMINATE × Sustained Weakness × UNCLASSIFIED: +36.7%

These are real and statistically significant (t > 20 in most).

### E.3 Momentum continuation

Filter:
- `setup ∈ {Trend Continuation, Trending Leadership, Pullback to 21EMA, Pullback to 50MA}`
- `leadership_tier ∈ {STRONG_LEADER, ESTABLISHED_LEADER, STRONG_PERFORMER}`
- Rank by CCQS descending

### E.4 Volatility / exhaustion regime

Filter:
- `primary_state == EXHAUSTION`
- `setup ∈ {Volume-Confirmed Exhaustion, Exhaustion w/ Bearish Divergence}`
- CCQS ranking works here (+5.87% Q10−Q1 spread); top-decile EXHAUSTION stocks continue their parabolic move on average

### E.5 Pattern screening (specific setups)

Use the setup filter directly. The top empirical-edge setups (≥ +6% at 60d) are:
- Volume-Confirmed Exhaustion
- Exhaustion (Generic)
- Capitulation Selling
- Elite Leader Continuation
- Sustained Weakness
- Distribution Pattern
- Deteriorating w/ Bullish Divergence
- Trending Leadership
- Exhaustion w/ Bearish Divergence
- Trend Continuation
- BB Squeeze with RS
- Pullback to 21EMA
- Pullback to 50MA

---

## F. Known limitations and caveats

| Caveat | Mechanism | Mitigation |
| ------ | --------- | ---------- |
| Mega-cap underperformance | CCQS 60d IC = −0.017 in top dollar-volume quintile (Priority 2b) | "Mega-cap" reliability chip surfaces this |
| High market vol regime | CCQS 60d IC = −0.014 in HIGH-vol regimes (Priority 2b) | "High market vol" banner + chip |
| Defensive baskets | CCQS has negative IC on 10 defensive baskets (Priority 2b) | "Defensive sector" chip |
| EXHAUSTION 20d signal ≈ 0 | Mean reversion at 20d in EXHAUSTION (Priority 2b) | "EXHAUSTION 20d caveat" chip |
| WEAK_LAGGARD CCQS inversion | Mean reversion dominates ranking (Phase 11D) | "Low-quality regime — CCQS may invert" chip |
| DETERIORATING tier CCQS inversion | Same | Same chip |
| NaN-tier stocks (insufficient RS history) | Cannot be tiered; systematic underperformers | Currently visible in dashboard; could be filtered |
| 2020 COVID long horizons | Phase 7 lost ~0.005 of 126d IC in 2020 (documented) | None — historical caveat |
| Short-horizon use (5d / 20d) | Functional but lower-quality | Use for entry timing, not primary signal |

---

## G. Quick reference: dashboard chip interpretation

| Chip | Color | Trigger | Meaning |
| ---- | ----- | ------- | ------- |
| Mega-cap | amber | dollar-volume Q5 | CCQS has documented weak signal in this cohort (Priority 2b) |
| Defensive sector | amber | basket in 10 defensive baskets | CCQS has documented negative IC on these baskets |
| High market vol regime | amber | SPY 20d realized vol ≥ tercile threshold | CCQS turns negative at 60d/126d in this regime |
| EXHAUSTION 20d caveat | blue/info | state == EXHAUSTION | 20d signal is statistically zero; 5d/60d/126d still carry signal |
| **High-quality regime — CCQS reliable** | **green** | tier in {ELITE/STRONG/ESTABLISHED_LEADER} | Phase 11D: Q10−Q1 spread +3–5pp; CCQS ranking trustworthy |
| **Low-quality regime — CCQS may invert** | **amber** | tier in {WEAK_LAGGARD, DETERIORATING} | Phase 11D: Q10−Q1 spread up to −9.24pp; consider mean-reversion framing |

---

## H. What CCQS V1 is NOT

- **NOT a universal continuous score that always predicts forward returns.** It is regime-dependent.
- **NOT a monotonic ranking system across all regimes.** In low-quality tiers it inverts.
- **NOT a standalone buy/sell signal.** It is a within-category ranking key; the categories carry the primary signal.
- **NOT a substitute for fundamental analysis or risk management.** It is a technical signal screening tool only.
- **NOT calibrated for very short horizons.** 5d/20d horizons work but the system is optimized for 60d/126d institutional-quality signal.

---

## I. Further reading

- **`SPEC.md`** — Authoritative methodology document. Contains the full Phase 11 audit trail (11A/11B/11C/11D/11E), all empirical numbers, validation framework, and architectural findings.
- **`CHANGELOG.md`** — Phase-by-phase commit history with status (shipped / rejected / deferred) and key empirical evidence.
- **`README.md`** — Project layout and run instructions.

---

**Path C complete (2026-05-26). Methodology baseline: Phase 11E.2.** Future changes require new empirical evidence per Methodology Lock §3.
