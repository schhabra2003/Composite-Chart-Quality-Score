# CCQS V1 — Changelog

Phase-by-phase implementation history. Companion to `SPEC.md` (authoritative methodology document) and `USER_GUIDE.md` (user-facing interpretation manual).

**Path C overall status:** COMPLETE as of 2026-05-26 (commit `e3a9ada` + Phase 12 closeout documentation).

Status legend:
- ✓ SHIPPED — implementation deployed to production
- ✗ REJECTED — investigated, did not meet criteria
- ↻ DEFERRED — documented for future consideration

---

## Path C — Phase-by-phase summary

### Phase 5.2 — NaN-CCQS root-cause fix + universe cleanup (2026-05-23) ✓ SHIPPED

Initial commit `ed4bf42`. Root-caused why CCQS was NaN for many tickers; cleaned up universe to ensure all ticked-as-scoreable rows produce a finite score. See `SPEC.md` §Phase 5.2.

### Phase 5.3 — Selective SP100 promotion (2026-05-23) ✓ SHIPPED

`ed4bf42`. Promoted high-quality SP100 names back into scoring universe after Phase 5.2 cleanup. See `SPEC.md` §Phase 5.3.

### Phase 5.5 — Naming standardization (2026-05-24) ✓ SHIPPED

Commit `01a887a`. Comprehensive vocabulary audit for institutional presentation. Renamed setups/states for clarity; ensured terminology was internally consistent. See `SPEC.md` §Phase 5.5.

### Phase 5.6 — Coil follow-up (2026-05-24) ✓ SHIPPED

Commits `ad51fdc`, `3442846`. Renamed remaining "Coil" setup labels for vocabulary consistency. See `SPEC.md` §Phase 5.6.

### Phase 5.7 — Climax / Broken sub-setup rename (2026-05-25) ✓ SHIPPED

Commit `871eb75`. Renamed climax/broken sub-setups to align with state-vocabulary parity. See `SPEC.md` §Phase 5.7.

### Phase 5.8 — Setup label accuracy audit (2026-05-25) ✓ SHIPPED

Commit `c8ff584` (combined with Phase 6). Audited 29 setup labels against actual detection logic; renamed where labels overclaimed. See `SPEC.md` §Phase 5.8.

### Phase 6 — Foundation fixes (2026-05-25) ✓ SHIPPED

Commit `c8ff584`. Two foundational changes:
- Per-date winsorization in `compute/ccqs.py` (1st/99th percentile clipping per date)
- `s_climax` removal (carried zero weight since X.2.1; component dimension 10 → 9)

See `SPEC.md` §Phase 6 + §Known caveats.

### Priority 2 — Empirical validation of current methodology (2026-05-25) ✓ DOCUMENTED

Documentation work in commit `c8ff584`. Three sub-tasks:
- **2a**: Bootstrap CIs on STATE_WEIGHTS (54 cells × 4 horizons; ~7.5M paired t-tests)
- **2b**: Conditional IC analysis across regimes (mega-cap, defensive sector, market vol, EXHAUSTION, 2020 COVID)
- **2c**: Synthesis into SPEC

Key finding: 6/24 s_demand cells carried significant NEGATIVE OOS IC — motivated Phase 7.

See `SPEC.md` §Priority 2.

### Phase 7 — Priority 3a: `s_demand` removal + carrier redistribution (2026-05-25) ✓ SHIPPED

Commit `619ba4e`. Zeroed `s_demand` weight in STATE_WEIGHTS; redistributed 10-15% per state to the four positive-OOS carriers (s_rs, s_rs_leadership, s_structure, s_mtf).

**Empirical evidence:** Walk-forward 126d t-stat 1.82 → 2.02 (clears institutional 2.0 threshold).

See `SPEC.md` §Phase 7.

### Priority 3b/3c — Simplification investigations (2026-05-25) ✗ REJECTED

Investigated 4-carrier-only composite (3b) and state-aware hybrid (3c). Both regressed EXHAUSTION-state IC catastrophically:
- 3b: EXHAUSTION 60d/126d down −48%/−27%
- 3c: EXHAUSTION fragility persists due to cross-state Bayesian averaging

**Architectural finding:** Confidence-blending toward INDETERMINATE means EXHAUSTION-state stocks pull 45% of their CCQS from the INDETERMINATE weight column. Further per-state simplification requires relaxing confidence-blending — a material redesign.

See `SPEC.md` §Priority 3.

### Priority 3d — Conditional performance warnings, display layer only (2026-05-25) ✓ SHIPPED

Commit `37646b0`. Added reliability flags surfacing Priority 2b findings as dashboard chips (Mega-cap, Defensive sector, High market vol regime, EXHAUSTION 20d caveat). Display-layer only — CCQS values unchanged.

See `SPEC.md` §Priority 3d.

### Phase 8a — Residual momentum addition (2026-05-26) ✓ SHIPPED

Commit `5bc8eb5`. Added `s_residual_momentum` as the 10th component at ~5% per state. Beta-adjusted idiosyncratic momentum: rolling 252d OLS beta vs SPY, daily residuals summed over 126d.

**Empirical evidence:**
- Standalone IC at 126d-fwd: +0.0466 (t=14.4)
- Orthogonal-to-s_rs IC at 126d: +0.0246 (t=+8.63)
- Walk-forward paired t at 60d: 2.05; at 126d: 2.72
- 23 of 24 (state × horizon) cells improve

Empirical basis: Blitz–Huij–Martens (2011), Robeco production usage.

See `SPEC.md` §Phase 8a.

### Phase 8a.1 — Short-horizon recovery investigation (2026-05-26) ✗ REJECTED

Hypothesis: a new `s_short_term_reversal` component could recover the 5d/20d t-stat erosion from Phase 8a without giving back 60d/126d gains.

**Decision criteria scorecard (4 fails, 2 passes):**
- Walk-forward paired t at any horizon: not significant
- EXHAUSTION regressed catastrophically (5d −0.013, 20d −0.017, 60d −0.002, 126d −0.012)

The Priority-3c architectural fragility re-emerged. No code changes.

See `SPEC.md` §Phase 8a.1.

### Phase 8b — Vol-adjustment standardization investigation (2026-05-26) ✗ REJECTED

Four configurations tested with stricter criteria than Phase 8a (CI-includes-zero counts as failure; walk-forward paired t > +1.96 required at 60d or 126d):
- Config B (Sharpe residual momentum): no-op
- Config C (Sharpe rank for momentum_21d): no-op
- Config D (raw 126d return rank): **−1.01 walk-forward paired t at 126d; EXHAUSTION 126d -0.0201**
- Config E (B+C+D combined): inherits D's regressions

Zero configurations pass all five strict criteria. No code changes.

See `SPEC.md` §Phase 8b.

### Phase 10 — Volume-pattern addition (Config W1, 2026-05-26) ✓ SHIPPED

Commit `0c61191`. Added `s_volume` (bundled `low_rel_vol_10d` + `volume_buzz_50`) as 11th component at 3% per state. Existing 10 components scaled by 0.97.

**Empirical evidence (first config in 3 investigations to clear strict criteria):**
- 5d per-date IC delta CI strict > 0 at [+0.000012, +0.000686]
- 5d walk-forward paired t = **+2.01** (clears +1.96 threshold)
- 5d t-stat 2.33 → 2.41; 20d 1.95 → **2.04** (crosses institutional 2.0)
- 60d/126d preserved (NS)
- EXHAUSTION-state IC **+0.006 to +0.016** across every horizon
- Regime-stable (HIGH/MED/LOW all positive at 5d/20d)

**Architectural insight:** Refutes Phase 8b "empirical optimum" conclusion. New orthogonal information additions succeed where weight redistributions fail. EXHAUSTION fragility was a constraint on RS-family redistribution, NOT on the architecture itself.

**Bundled feature requirement (W6 lesson):** Investigation showed `low_rel_vol_10d` alone HURTS CCQS at every horizon (paired t −1.20 to −1.95). Only blended with `volume_buzz_50` is the composite net-positive. Cannot unbundle.

See `SPEC.md` §Phase 10.

### Phase 11A — State Classification Validation (2026-05-26) ✓ DOCUMENTED

Combined with Phase 11.B.1 commit `4951a0c` for documentation. No code changes — investigation only.

**Key findings:**
- 6 states empirically validated; every state statistically distinguishable from every other at every horizon
- **State machine is a CONTEXT classifier, NOT a buy/sell signal.** TRENDING stocks UNDERPERFORM universe (−1.0% at 60d); EXHAUSTION stocks OUTPERFORM (+4.1%)
- State persistence: 72.3% local stability (appropriate)
- All transitions physically sensible; no impossible cells
- Confidence-blending mechanism working as designed
- Threshold sensitivity: most params mid-slope; PULLBACK `mu_rsi_14 = 45.0` most sensitive (deferred for tuning)

See `SPEC.md` §Phase 11A.

### Phase 11.B.1 — Dead setup removal (2026-05-26) ✓ SHIPPED

Commit `4951a0c`. Removed `"Consolidation Within Strong Theme"` from SETUP_LABELS and cascade. Never fired (n=0 in 1.53M rows) — required `theme_strong` flag that was hardcoded False.

SETUP_LABELS: 29 → 28. No CCQS change (setup labels don't feed CCQS).

See `SPEC.md` §Phase 11B + §Phase 11.B.1 patch.

### Phase 11B — Setup Classification Validation (2026-05-26) ✓ DOCUMENTED

Commit `4951a0c` (combined with 11.B.1). No code changes — investigation only.

**Key findings:**
- "**Premium label, no alpha**" pattern: VCP Setup, Emerging Leader, Premium Pullback, Theme Leader Pullback all UNDERPERFORM universe at 60d
- "Weakness-branded" setups (Capitulation Selling, Distribution Pattern, Sustained Weakness, Volume-Confirmed Exhaustion) OUTPERFORM by 4–12pp
- 34 of 325 pairwise comparisons are statistically equivalent (p > 0.05)
- VCP Setup ≡ Emerging Leader (p=0.94) — flagged for Phase 11E.1 merger
- Priority cascade empirically validated (cascade-assigned rows outperform masked for high-priority setups)

See `SPEC.md` §Phase 11B.

### Phase 11C — Leadership Tier Validation (2026-05-26) ✓ DOCUMENTED

Combined with Phase 11.C.1 commit `b2fe003` for documentation. No code changes — investigation only.

**Key findings:**
- Only ELITE_LEADER has a truly distinctive forward edge (+15.24% at 60d, 3× universe)
- All other 8 tiers cluster within ±2.5pp of universe
- Non-monotonic ordering: 4 of 8 adjacent tier pairs have "lower" tier OUTPERFORMING "higher"
- EMERGING_LEADER UNDERPERFORMS universe (premium-label pattern again)
- WEAK_LAGGARD outperforms most upper tiers (mean reversion)
- Tier × State interaction is high-value (ELITE × INDETERMINATE = +18.10%)

**Anomaly discovered:** NEUTRAL has rs_p10=10.97 vs formal definition [45, 60). Default-init bug.

See `SPEC.md` §Phase 11C.

### Phase 11.C.1 — NEUTRAL fall-through fix (2026-05-26) ✓ SHIPPED

Commit `b2fe003`. Added explicit `UNCLASSIFIED` 10th tier. Default initialization in `compute/leadership.py` changed from `"NEUTRAL"` to `"UNCLASSIFIED"`.

**Bug fixed:** ~132,050 rows (8.6% of universe = 42.7% of NEUTRAL pre-patch) had been mis-labeled as NEUTRAL because they fell through the cascade. Three patterns:
1. rs_spy < 25 AND rs_slope ≥ 0 (80,675 rows)
2. rs_spy ∈ [40, 45) AND rs_slope < −5 (28,119 rows)
3. rs_spy < 45 AND rs_slope is NaN (23,256 rows)

**Population shift:** NEUTRAL 21.83% → 12.59%; UNCLASSIFIED 0 → 8.63%. No CCQS impact (leadership tier doesn't feed CCQS).

See `SPEC.md` §Phase 11C / §Phase 11.C.1 patch.

### Phase 11D — Cross-Layer Synthesis (2026-05-26) ✓ DOCUMENTED

Commit `e3a9ada`. No code changes — synthesis investigation.

**Three first-order findings:**
1. **CCQS is regime-dependent** — works in top tiers (Q10−Q1 spread +5.26% in ESTABLISHED_LEADER), inverts in bottom tiers (WEAK_LAGGARD −9.24%)
2. **Categorical labels carry 97.3% of cross-sectional R²** — CCQS as continuous variable adds 2.7%. Setup is the highest-info layer (60.6%).
3. **State × Setup are 77% redundant (Cramér's V = 0.77)** — by design, structural not bug

**System reframing:** "CCQS V1 is a categorical screening + within-category ranking tool."

See `SPEC.md` §Phase 11D + §Path C — Comprehensive Overview.

### Phase 11E.1 — Emerging Leader setup merger (2026-05-26) ✓ SHIPPED

Commit `e3a9ada`. Removed `"Emerging Leader"` from SETUP_LABELS and cascade. Statistically equivalent to VCP Setup (p=0.94 per Phase 11B); both underperformed universe at p < 0.001.

SETUP_LABELS: 28 → 27. The 8,999 rows previously labeled "Emerging Leader" absorbed by lower-priority setups (typically Trending Leadership for rs_spy ≥ 80 stocks). VCP Setup retained.

Cascade renumbering: #13-22 → #12-21; catch-alls #23-28 → #22-27.

See `SPEC.md` §Phase 11D §Phase 11E.1 patch.

### Phase 11E.2 — Dashboard CCQS regime chip (2026-05-26) ✓ SHIPPED

Commit `e3a9ada`. Added per-ticker reliability chip in `app/utils/data_loader.py`:
- **Green chip** "High-quality regime — CCQS reliable" for tier ∈ {ELITE_LEADER, STRONG_LEADER, ESTABLISHED_LEADER}
- **Amber chip** "Low-quality regime — CCQS may invert" for tier ∈ {WEAK_LAGGARD, DETERIORATING}
- No chip for middle tiers (no strong regime claim)

`reliability_flags()` signature extended to accept `leadership_tier`. New "ok" severity color (green) added to `app/streamlit_app.py`.

See `SPEC.md` §Phase 11D §Phase 11E.2 patch.

### Phase 12 — Path C closeout documentation (2026-05-26) ✓ THIS COMMIT

Comprehensive closeout work:
1. Live site verification via Chrome MCP (verified Phase 11E.2 chips on STM/AWK/ABT, NVDA/AAL, 11 components, no "Emerging Leader" setup)
2. SPEC.md comprehensive review + Path C — Comprehensive Overview section
3. USER_GUIDE.md created (user-facing interpretation manual)
4. CHANGELOG.md created (this file)
5. TV reference refresh + parity test (140/140 pass)
6. Final commit + push

**Methodology baseline frozen at Phase 11E.2.** Path C complete.

See `SPEC.md` §Path C — Comprehensive Overview.

---

## Forward expectations (post-Path C)

Per `SPEC.md` Methodology Lock §3, future methodology changes require:
- Forward-looking signal degradation (current OOS IC drops materially), OR
- Independent research findings (new academic work, new data sources), OR
- Clear computational bugs

Patterns observed in dashboard historical displays do NOT constitute valid motivation for methodology changes. This prevents hindsight bias.

## Deferred backlog (post-Path C)

See `SPEC.md` §Path C deferred backlog section for the full list. Highlights:
- STRONG_LEADER + ESTABLISHED_LEADER tier merger (statistically near-identical)
- EMERGING_LEADER tier rename or collapse
- Extended Exhaustion → Late-Stage Trending rename
- Threshold tuning: Distribution Pattern `dist_days_min`, PULLBACK `mu_rsi_14`
- Premium Pullback criteria review
- Dashboard preset filters (high-quality, mean-reversion)
- NaN-tier filter / warning chip
