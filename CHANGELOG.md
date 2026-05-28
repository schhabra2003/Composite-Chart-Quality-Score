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

### Phase 13 — Russell 2000 expansion feasibility (2026-05-26) ✓ INVESTIGATION ONLY

User context shift: discretionary L/S manager requested universe
expansion for idea-flow breadth, especially short candidates.
Investigation found 95% yfinance coverage on stratified 188-name R2K
sample, feature distributions within ~10% of S&P 500 medians, and
**1.37-1.49× richer left tail** (deeper drawdowns at 60-126d). Recommendation:
proceed with expansion. Approved for Phase 14.1.

See `SPEC.md` §Phase 13. Full report: `/tmp/PHASE_13_REPORT.md`.

### Phase 14.1 — Universe expansion experiment (2026-05-26) ✗ REVERTED in Phase 14R

Implemented full universe expansion (884 → 1,837 tickers; +953
net-new Russell 1000 + S&P SmallCap 600 names with GICS auto-sector
basket assignment). Pipeline ran end-to-end with 11/11 sanity checks.

**Conditional IC analysis exposed methodology specialization need:**

| Horizon | Original 884 (within new pipeline) | New 953 R1K/SP600 |
|---------|----------------------------------|-------------------|
| 5d | +0.0114 (t=+2.35) ✓ | +0.0011 (t=+0.26) |
| 20d | +0.0087 (t=+1.97) ✓ | **−0.0068 (t=−1.77)** |
| 60d | +0.0133 (t=+3.46) ✓ | **−0.0054 (t=−1.58)** |
| 126d | +0.0292 (t=+9.10) ✓ | +0.0082 (t=+2.80) |

Methodology produces near-zero or NEGATIVE signal on the new small-cap
names while remaining intact for the original universe. Forcing a
single methodology onto two structurally different universes compromises
both.

**Decision (Approach C):** REVERT Phase 14.1. Build separate Small Cap
CCQS tool (Phase 15) with empirically recalibrated methodology.

See `SPEC.md` §Phase 14.1.

### Phase 14R — Reversion to Path C state (2026-05-26) ✓ SHIPPED

Immediate reversion. CCQS restored to bit-identical Phase 12 / Path C
validated state. Universe back to 884 / 851 quality-gated; 9 categories;
22 MB dashboard cache; 140/140 TV parity; 11/11 sanity checks; IC
matches Phase 11 baseline exactly (5d 0.0115; 60d 0.0137; 126d 0.0296).

Files reverted:
- `data/universe.py` — removed Small Mid Cap (Auto-Sectored) category
- `tests/reference/tv_snapshots.py` — restored AMZN pin to Phase 11 baseline

See `SPEC.md` §Phase 14R.

### Phase 14R.H — DST-aware cron fix (2026-05-26) ✓ SHIPPED

CI workflow `.github/workflows/pipeline.yml` updated so the scheduled
pipeline fires at exactly **4:30 PM ET year-round (M-F)**, regardless of
DST. Previously a single cron (`30 21 * * 1-5` UTC) was correct only
during EST (winter); during EDT (summer, current) it fired at 5:30 PM
ET, one hour late.

Implementation: two cron entries (`30 20` for EDT + `30 21` for EST)
plus a TZ-aware `guard` job that checks `TZ=America/New_York date +%H`.
The heavy `refresh` job has `needs: guard` and only runs when the
guard signals `should_run=true` (ET hour == 16). The wrong-DST cron
firing exits in ~10 seconds via the guard. Manual `workflow_dispatch`
bypasses the guard.

Net effect: exactly one full pipeline execution per weekday at
4:30 PM ET, year-round. No DST drift.

### Phase 14R.K — Workflow push race-condition fix (2026-05-26) ✓ SHIPPED

The Phase 14R.H DST-aware workflow ran successfully end-to-end in run #3
(all compute steps green: fetch OHLCV 1m29s → data quality 5s → features
1m20s → standardization 2m3s → pipeline 12m43s → dashboard build 3s)
BUT the final `git push HEAD:main` step failed with:

  ! [rejected] HEAD -> main (fetch first)
  error: failed to push some refs

Root cause: a developer push to main during the workflow's ~17-minute
run shifted HEAD on remote main. The workflow's commit was based on the
remote main at workflow START; by push time, remote main had moved.

Fix: wrap the push in a 3-attempt retry loop with `git fetch origin main`
+ `git pull --rebase origin main` before each push. This absorbs
concurrent commits cleanly. If a developer pushes 3 times during one
workflow run (extremely unlikely), the workflow fails — but that's a
graceful upper bound.

This was the failure mode that caused run #3 to be reported as failed
even though every actual computation step (fetch + compute + tests +
cache build) was completely successful. Pipeline output for 2026-05-26
was correct; only the metadata-update step was rejected.

### Phase 14R.J — Hard-gate test suite for pipeline reliability (2026-05-26) ✓ SHIPPED

Comprehensive test suite added to gate the daily CI pipeline. If ANY
test fails, the dashboard cache is NOT committed back to main — the
prior good cache stays live. This is the "no issues whatsoever" promise.

**New tests** (48 tests total, all passing locally):

1. **`tests/test_universe_coverage.py`** (7 tests) — yfinance fetched all
   universe tickers correctly:
   - Benchmarks SPY/QQQ present
   - ≥ 95% of declared universe in cache
   - OHLCV latest date within 7 days
   - No silent failures (every missing ticker explicitly in failed_tickers.json)
   - Data quality firewall ≥ 90% PASS+WARNING
   - Benchmarks PASS firewall

2. **`tests/test_cache_freshness.py`** (29 tests) — dashboard caches
   present, non-empty, current:
   - All 8 parquet files + 4 JSON files exist
   - All parquets non-empty
   - CCQS latest date within 7 days
   - 11 components present in dashboard `components.parquet`
   - Cache size within expected 15-40 MB band
   - Regime context current
   - All 11 sanity checks pass

3. **`tests/test_pipeline_integrity.py`** (12 tests) — pipeline outputs
   internally consistent and sane:
   - 11 sanity checks pass
   - CCQS values in [0, 100]
   - CCQS distribution non-degenerate
   - Grade distribution covers all 5 grades
   - 11 components present, no all-NaN columns
   - State/tier/setup distributions non-degenerate
   - STATE_WEIGHTS sum to 1.0 per state
   - Confidence-blending mechanism intact
   - All output parquets share latest date

4. **`tests/reference/test_tv_parity.py`** (existing) — 10 canary tickers
   numerically pinned (140 field checks).

**CI workflow integration:** All four suites run as HARD gates (no
`continue-on-error`) BEFORE the dashboard-cache commit step. If any
fail, the workflow fails, no cache is pushed to main, and the prior
good cache remains live. Legacy `test_phase2_spot_check` and
`test_phase3_validation` continue as soft gates AFTER the commit
(aligned to earlier baselines).

**Net effect:** Daily CCQS pipeline is now guarded against:
- Silent data-fetch failures (universe coverage test)
- Stale or missing caches (freshness test)
- Pipeline integrity failures (sanity, distributions, ranges)
- Numerical regressions against the 10 TV canaries

User direction satisfied: "every day from Monday-Friday without any
fail" with explicit test coverage of "all stocks data fetches properly
and computation happens with no issues whatsoever."

### Phase 15 — Small Cap CCQS (CCQS-SC) development [PLANNED]

Separate Small Cap CCQS tool with independent empirical methodology.
12 sub-phases (15.1-15.12) covering universe definition, data
infrastructure, feature engineering, state classifier, setup classifier,
tier classifier, component weights, comprehensive validation, dashboard
integration, documentation, deployment. Path C rigor throughout.

Begins after Phase 14R is user-confirmed clean.

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

---

## Phase 16-17 — CCQS empirical re-validation + regime-aware deployment

**Status (2026-05-27):** Phase 17 deployed.

After Phase 15.1.D revealed 90% walk-forward failure on small caps, Phase 16
applied the same Sub-Investigation D rigor to LC under the user direction:

> "Apply Sub-Investigation D-level rigor to CCQS validation. Empirically
> verify what CCQS actually does well and what might be illusion. No
> assumptions preserved."

### Phase 16 — Comprehensive CCQS re-validation (16.A-16.I)

Nine sub-investigations on 874-ticker LC universe (4.77 GB feature matrix,
463 features × 2360 dates including all 11 production CCQS components):

- **16.A**: Forward return characterization. LC has stronger mean/hit/skew
  than SC. Universal patterns: HIGH market vol → 4× returns; low-vol anomaly.
- **16.B**: Same 343 base + 84 XS + 25 sector-relative + 11 CCQS components
  feature matrix as Phase 15.1.C, extended history (2017-01+).
- **16.C**: Per-date Spearman IC ranking. **Best CCQS component
  (`s_residual_momentum`) ranks 71/463; `s_momentum` ranks 426/463.** Raw
  `mom_ret_126d` (rank 15) more predictive than ALL CCQS components.
- **16.D**: Axis-stratified regressions on pre-screened 155 features.
  CCQS axis adds +1.4% incremental per-date R² — not redundant.
- **16.E**: Conditional IC across 4 regime axes × 4 horizons. Top 9
  sign-flippers are ALL CCQS components (62% average flip rate).
- **16.F (CRITICAL TEST)**: Walk-forward OOS validation, 88 windows.
  **0/11 CCQS components survived. Only 1/61 features total survived.**
- **16.G**: Time-varying analysis. CCQS components have IC +0.03 in
  STRONG_BULL but −0.08 in STRONG_BEAR — **CCQS is a bull-market signal,
  not all-weather.** 5 useful Tier-1 components, 6 weak/noise Tier-2.
- **16.H**: Production STATE_WEIGHTS vs empirical optimal. Production
  TRENDING weights only 27.5% off empirical optimum. **Production already
  drops worst components to near-zero** (`s_extension` 0%, `s_demand` 0%,
  `s_momentum` 0.3%).
- **16.I**: Honest synthesis — three path-forward options.

### Phase 17 — Regime-aware deployment (17.0-17.9)

User selected the most empirically-grounded improvement:

- **17.0**: Tested 42 candidate regime indicators (trend/vol/drawdown/breadth/
  composite). **`dd_lt_15pct` selected** — SPY drawdown from 252-day high <15%.
  - t-statistic 8.74, p < 0.0001
  - IC differential at 63d: +0.093 (in-regime +0.027 vs off-regime −0.066)
  - On 90% of trading days; real-time computable from SPY price only
- **17.1-17.2**: Built v2 candidates (5 Tier-1 components, renormalized
  weights, empirical bull weights). v2 vs v1 score correlation 0.989;
  top-50 daily overlap 86%.
- **17.4**: Walk-forward validation. **Critical finding**: v2 vs v1 IC
  difference is ~0.001 (immaterial). **Regime filter (`dd_lt_15pct=1`)
  is the actual empirical innovation** — turns 0/12 walk-forward survivors
  → 3/12 (1/12 strictly robust at 126d in-regime).
- **17.5**: Decision gate. Selected Option 2: deploy regime indicator only;
  keep v1 STATE_WEIGHTS (already empirically near-optimal).

### Phase 17.6-17.9 — Regime indicator deployment

`compute/build_dashboard_cache.py::_design_space_regime()` writes new
`ccqs_design_space` key into `data/cache/dashboard/regime_context.json`:

```json
"ccqs_design_space": {
  "indicator": "dd_lt_15pct",
  "spy_dd_from_high": -0.0002,
  "spy_above_200ma": true,
  "in_regime": true,
  "regime_state": "GREEN",
  "regime_label": "Design space — high confidence",
  "empirical_basis": {
    "ic_differential_63d": 0.093,
    "t_statistic": 8.74,
    "p_value_lt": 0.0001
  }
}
```

Three-state classification:
- **GREEN**: `dd_lt_15pct=TRUE AND SPY > 200d MA` — design space, high confidence
- **YELLOW**: `dd_lt_15pct=TRUE AND SPY ≤ 200d MA` — in regime, trend uncertain
- **RED**: `dd_lt_15pct=FALSE` — out of design space; apply discretion

`app/streamlit_app.py` renders prominent regime chip immediately below the
title; RED state also adds explicit `st.error` banner with empirical citation.

**No changes to STATE_WEIGHTS, components.parquet, ccqs.parquet, or TV
references — methodology preserved; regime awareness added as display layer.**

**Net effect**: production CCQS now ships with empirically-validated
design-space awareness. Users see at a glance whether the day's
environment is within the validated working regime.

---

## Phase 18 — UI / UX cleanup pass (2026-05-27)

User-driven dashboard cleanup. Thirteen targeted changes, zero methodology
impact: STATE_WEIGHTS, CCQS computation, and TradingView reference parity
are all preserved bit-identically (140 / 140 fields, 11 / 11 sanity checks).

### Vocabulary

- **18.1** — Dropped the "-LC" suffix everywhere. The system only operates
  on the large-cap universe, so "CCQS-LC" added confusion rather than
  precision. Affected: regime chip copy, `SPEC.md` §16-17, `USER_GUIDE.md`
  §J, `CHANGELOG.md`, internal Phase 17 docstrings.
- **18.10** — Expanded acronyms in every user-facing surface. Component
  display names: `RS` → "Relative Strength", `RSL` → "Relative Strength
  Line", `MTF` → "Multi-Timeframe Alignment". Key-metrics labels: `ADX-14`
  → "Average Directional Index (14)", `RSI-14` → "Relative Strength
  Index (14)", `% from 50 DMA` → "% from 50-day Moving Average", and so
  on. Methodology paragraph rewritten without acronyms.

### Top Stocks table

- **18.2** — Removed the standalone "RS" column. `rs_rating_spy` is already
  one of the strongest inputs to CCQS via `s_rs` and `s_rs_leadership`;
  showing it as a separate column duplicated signal already encoded in
  the rank.
- **18.3** — Replaced the single "Δ Today" column with three Δ CCQS
  columns at 1-day / 5-day / 21-day trading-day horizons. Δ values are
  computed at runtime from the slim dashboard cache (no schema change to
  any parquet); the 5d / 21d offsets step through the sorted unique date
  index in `ccqs.parquet`, so lookbacks are trading-day-accurate
  regardless of market holidays.
- Renamed the "Tier" column header to "Leadership Tier" for clarity.

### Themes table

- **18.4** — Removed the "Members" (constituent count) column. Cardinality
  is metadata, not insight.
- **18.6** — Removed the "% Grade A+" column. It overlapped with the
  `% > 50-day Moving Average` breadth measure; kept the latter as the
  cleaner price-action signal independent of the CCQS score itself.
- **18.5** — Verified the breadth math: `pct_above_50dma` =
  `g["pct_above_sma_50"].mean() × 100` in `compute/aggregation.py:243`,
  where `pct_above_sma_50` is a 0/1 per-ticker binary in
  `features.parquet`. Computation is correct.
- **18.13** — Added a "Constituents" column that lists every basket
  member, sorted by current CCQS descending, comma-joined. Users can
  cross-reference on charting platforms / brokerages without leaving
  the dashboard.

### What Changed Today

- **18.7** — Replaced the threshold-gated lists with magnitude-ranked
  top-10 lists. Section headers renamed:
  - "New Emerging Leaders" → **"Strongest Risers"** (top 10 by 1-day Δ CCQS)
  - "Newly Deteriorating" → **"Largest Decliners"** (bottom 10 by 1-day Δ CCQS)
  - "Grade Jumps" → **"Grade Changes"** (top 10 by |Δ CCQS|; grade-letter
    changers preferred, padded with the next largest absolute movers when
    fewer than 10 changed grade letters on the day)

### Stock detail

- **18.8** — Rebuilt the header to a two-tier layout: a large-weight ticker
  symbol, then a row of labeled key-value chips (Score, Leadership Tier,
  State, Theme). Replaces the previous flat middle-dot pipe.
- **18.9** — Removed the reliability chips block entirely. CCQS is a
  technical scoring system, not a predictive model; per-stock "reliability"
  framing was misleading (e.g., labelling mega-caps as a *warning* when
  they are simply a different quintile).

### Market-context caution

- **18.12** — Replaced the always-on three-state regime chip with a
  context-only caution. No banner in GREEN regime (the silent majority
  case). YELLOW shows an `st.info` caution noting the broad market is
  below its 200-day moving average. RED shows an `st.warning` noting the
  broad market is in a meaningful drawdown. Copy is professional and
  measured; CCQS rankings are always described as a screening aid, not
  a directional signal.

### Data correctness

- **18.11** — Confirmed SNDK is already correctly assigned to the
  "Memory and Storage" basket (`data/universe.py` lines 33, 1223, 2090,
  2254). No change needed; the user's "SDNK" was a typo for SNDK
  (SanDisk's NASDAQ ticker).

### Files touched

```
app/streamlit_app.py
app/utils/tables.py
app/utils/data_loader.py
compute/build_dashboard_cache.py
SPEC.md
USER_GUIDE.md
CHANGELOG.md
data/cache/dashboard/regime_context.json   # text refresh from build script
```

### Net effect

The dashboard reads like a focused technical screen: top stocks by CCQS
with three change-horizon columns, themes by basket with breadth and
constituent listing, three magnitude-ranked change boards, and a clean
stock detail with labeled chips. Caution banners only when the broad
market context warrants them. No chip noise on normal days.

---

## Phase 20 — Basket name cleanup (2026-05-27)

Seven basket renames to fix redundancy, jargon, and misleading "and" connectors. No methodology change, no ticker membership change, no TradingView parity impact.

### Renames applied

| Old | New | Reason |
|---|---|---|
| Battery Storage and BESS | **Battery Energy Storage** | Redundant — "BESS" expands to "Battery Energy Storage System". |
| RF and Wireless Connectivity | **Wireless Connectivity Chips** | RF *is* wireless connectivity; "Chips" clarifies these are silicon (QCOM, SWKS) not carriers. |
| Trucking and LTL | **Freight Trucking** | LTL is a subset of trucking, not a peer. |
| Restaurants and QSR | **Quick Service Restaurants** | All members are QSR/fast food (MCD, YUM, etc.); peer basket "Casual Dining" already covers the sit-down names. |
| Cannabis and MSOs | **Cannabis Multi-State Operators** | Expands the acronym; consistent with Phase 18's acronym-cleanup pattern. |
| Volatility and Market Plumbing | **Market Infrastructure and Exchanges** | "Plumbing" is industry slang; "Infrastructure and Exchanges" is the standard term for CBOE/CME/ICE/NDAQ/etc. |
| CRO and Clinical Services | **Contract Research and Clinical Services** | Expands the acronym. CRO = Contract Research Organization. |

### Files touched

`data/universe.py` (CATEGORIES, BASKET_PRIORITY, PRIMARY_BASKETS, PRIMARY_BASKET_CONSTITUENTS — 94 occurrences); `SPEC.md`; `USER_GUIDE.md`; `CHANGELOG.md`. Pipeline aggregation re-run; dashboard cache rebuilt.

### Validation

- 25/25 metric integrity tests PASS
- 140/140 TradingView reference fields PASS (methodology unchanged)
- 147 baskets in `theme_aggregates.parquet` (unchanged count)
- 6 of 7 renamed baskets show in the dashboard's Themes table with new names; 7th ("Market Infrastructure and Exchanges") is a tag overlay whose constituents all dedup into higher-priority primary baskets (Exchanges and Market Data, Brokers and Trading Platforms, etc.), so it surfaces only when used as a tag — rename takes effect there.


---

## Phase 21 — SNDK basket coverage (2026-05-27)

SNDK (SanDisk, post-WDC spinoff Feb 2025) was in only 1 basket (Memory and
Storage) while peers MU/WDC/STX are in 3 baskets each. Added SNDK to three
additional baskets where its peers live and where the business fits.

### Additions

| Basket | Reason |
|---|---|
| **Servers and AI Hardware** | Same coverage as WDC, STX. SanDisk SSDs go into the same server platforms. |
| **Enterprise Storage and Data Infrastructure** | Same coverage as WDC, STX. SanDisk is a pure-play enterprise flash vendor. |
| **AI Hardware Supply Chain** | Same coverage as MU. NAND flash is a critical part of the AI hardware supply chain (training/inference workloads need fast storage tiers). |

### Skipped (intentional)

- **HBM and Advanced Memory** — SanDisk is NAND flash, not HBM (High Bandwidth Memory). HBM is a DRAM product made by Micron, Samsung, SK Hynix. Adding SNDK here would be a misclassification.

### Status note

SNDK still has NaN CCQS for ~4-5 more trading days while the
`residual_momentum_252d` rolling window fills in (SNDK started trading
2025-02-18, so it needs through ~early June 2026 to accumulate the full
252-day window). The basket assignments take effect immediately once
scoring begins.

### Validation

- 25/25 metric integrity tests PASS
- 140/140 TradingView reference fields PASS
- SNDK now in 4 baskets (Memory and Storage primary + 3 tag overlays):
  Servers and AI Hardware, Enterprise Storage and Data Infrastructure,
  AI Hardware Supply Chain. Confirmed via PRIMARY_BASKETS + TAGS dict.


---

## Phase 23 — Add 9 major recent IPOs (2026-05-28)

Universe expanded from 883 → 892 tickers. All additions are well-known
recent listings that belong in already-defined baskets.

### Tickers added

| Ticker | Company | Listed | Primary basket | Tag overlays |
|---|---|---|---|---|
| **CRWV** | CoreWeave | Mar 2025 | AI Cloud Challengers and Neocloud | AI Hardware Supply Chain, AI Data Center Capex |
| **ALAB** | Astera Labs | Mar 2024 | AI ASICs and Custom Silicon | AI Hardware Supply Chain |
| **RDDT** | Reddit | Mar 2024 | Consumer Internet | Digital Advertising Platforms |
| **TEM** | Tempus AI | Jun 2024 | Healthcare AI and Automation | Diagnostics and Life Science Tools |
| **CRCL** | Circle Internet Group | Jun 2025 | Stablecoin and Tokenization Proxies | — |
| **PSKY** | Paramount Skydance | Aug 2025 | Streaming and Audio | — |
| **BIRK** | Birkenstock | Oct 2023 | Apparel and Footwear | Luxury Goods |
| **KGS** | Kodiak Gas Services | Jun 2023 | Midstream Pipelines | — |
| **CAVA** | Cava Group | Jun 2023 | Casual Dining | — |

### Methodology note — long warmup

Per the Phase 16 feature-cascade structure, residual-momentum-252d
requires ~504 valid trading days (252 of rs_rating_spy warmup + 252 of
residual slope window). Most of these names won't score immediately:

- BIRK, CAVA, KGS (listed 2023): should score soon (close to 504-day mark)
- RDDT, ALAB (Mar 2024): ~14 months listed → ~290 days short of the 504 threshold
- TEM (Jun 2024): ~11 months listed → ~340 days short
- CRWV (Mar 2025): ~14 months listed → ~290 days short
- CRCL, PSKY (Jun-Aug 2025): just listed; ~250-280 days short

All will surface in the dashboard automatically as their windows fill.
The basket assignments are in place now so the pipeline picks up OHLCV
on the next daily run and tickers appear in basket constituent lists.

### Validation

- 25/25 metric integrity tests PASS
- 140/140 TradingView reference fields PASS (methodology unchanged)
- Universe count: 892 unique tickers across 275 baskets

