# CCQS V1 — Composite Chart Quality Score Specification

**Version:** 1.0 (Locked) — Priority 3 closeout (Phase 7 weights + Priority 3d display warnings) + Phase 5.5–5.8 + Phase 6 foundation fixes + Priority 2 empirical validation (2026-05-25)
**Date:** May 2026
**Author:** Shreyaansh Chhabra (ADFM)
**Purpose:** Pure technical, momentum & strength screening tool for L/S discretionary equity analysis.

---

## Methodology Lock

As of Phase X.3 / Phase 5.2 (May 2026), the CCQS methodology is locked. The following principles apply:

1. Historical CCQS values represent today's methodology applied to historical data.
2. Universe and basket assignments are current; survivorship bias is not removed.
3. Methodology modifications require motivation independent of historical pattern observation:
   - Forward-looking signal degradation (current OOS IC drops materially)
   - Independent research findings (new academic work, new data sources)
   - Clear computational bugs
4. Patterns observed in dashboard historical displays do NOT constitute valid motivation for methodology changes. This prevents hindsight bias and curve-fitting.
5. OOS IC baseline (Phase X.3) is preserved as published:
   - 1d: t=4.16, IC=0.0173, hit rate 68.2%
   - 126d: t=2.59, IC=0.0412, hit rate 69.2%
   - 252d: t=2.05, IC=0.0360, hit rate 63.6%
6. Extended-window OOS IC (post-backfill) computed as secondary validation, labeled as such, NOT used as replacement baseline.

This lock applies to all future development. Any proposed methodology change must reference this section and provide motivation that does not derive from historical chart observation.

---

### Historical CCQS Coverage (2026-05-23 backfill)

CCQS computed for all stocks from **2020-01-01 onward** (252-day warmup
excludes pre-2020 dates from valid scores). The 7-year OHLCV window
(`LOOKBACK_DAYS = 7 * 365 + 60` in [`compute/loader.py`](compute/loader.py))
supports a continuous 2020–2026 trajectory for the dashboard stock-detail
display.

**Backfill validation** (`compute/validation/historical_backfill_validation.py`,
[`data/cache/historical_backfill_validation.json`](data/cache/historical_backfill_validation.json)):

| Metric | Value |
|--------|-------|
| OHLCV date range | 2019-03-27 → 2026-05-22 |
| Unique dates | 1,800 |
| Scored tickers | 858 |
| Valid CCQS rows | 1,220,611 / 1,544,400 |
| Pre-2020 valid rows | **0** (252d warmup enforced) |
| Out-of-bounds CCQS | **0** |
| Warmup violations | **0** |

Sample large caps (NVDA / MSFT / COST / JPM / NVO) each have **1,488 valid
rows** from 2020-06-22 onward. Recent IPOs handled cleanly — PLTR valid from
2021-12-27, SNOW from 2021-12-10, CRWD from 2020-09-04.

**Extended-window OOS IC (secondary validation only).** Re-running
`compute.validation.oos_evaluation` over the full 7-year window (73 rolling
test periods) produces these diagnostic IC values:

| Horizon | Extended-window IC | Extended t-stat | Extended hit rate |
|---------|---------------------|-----------------|-------------------|
| 1d   | +0.0146 | **+4.11** | 66.7% |
| 5d   | +0.0105 |   +1.28   | 60.9% |
| 20d  | +0.0107 |   +0.72   | 52.2% |
| 60d  | +0.0091 |   +0.61   | 55.2% |
| 126d | +0.0245 |   +1.85   | 59.4% |
| 252d | +0.0131 |   +1.05   | 56.9% |

**This is secondary validation, NOT a replacement baseline.** Primary
baseline is the Phase X.3 5-year window (48 windows) as published:

| Horizon | **Phase X.3 baseline IC** | **Phase X.3 t-stat** | **Phase X.3 hit rate** |
|---------|---------------------------|----------------------|-------------------------|
| 1d   | +0.0173 | **+4.16** | 68.2% |
| 126d | +0.0412 | **+2.59** | 69.2% |
| 252d | +0.0360 | **+2.05** | 63.6% |

**Interpretation.** The 1d signal holds nearly identically across windows
(+4.11 ext vs +4.16 published). The 126d and 252d horizons weaken on the
extended window — t-stats drop below the 2.0 significance threshold. This
reflects regime sensitivity (the extended window includes the 2020 COVID
shock + recovery, which the 5-year window omits), not a methodology defect.
Per the Methodology Lock above, this observation does NOT motivate
re-weighting or feature changes: the lock requires forward-looking signal
degradation on NEW data (not historical regime extension) before
methodology revision is considered.

The Phase X.3 baseline IC values (1d t=+4.16, 126d t=+2.59, 252d t=+2.05)
remain the **published official baseline**. Extended-window IC is recorded
here for completeness and labeled as such wherever it surfaces in the
dashboard.

---

### Phase 5.2 — NaN-CCQS root-cause fix + universe cleanup (2026-05-23)

**Trigger.** Level 3 validation FAILed at gate E: 101 stocks had NaN CCQS at
the most recent snapshot. Root cause: BASKET_PRIORITY dedup creates small
primary-basket constituent lists (<3 members) for ~94 stocks; the
`_within_basket_z` helper in `compute/features.py` skips computation for
<3 member baskets, producing NaN; that NaN propagates through `s_rs` (15%
weight on `within_basket_z_21d`) and `s_rs_leadership` confluence (6.75%
weight on `within_basket_z_63d`) into a NaN composite CCQS.

**Fix 1 — `.fillna(0.0)` on the three NaN-propagating terms in
`compute/components.py`:**

- `_compute_s_rs`: `within_basket_z_21d` (line 117)
- `_compute_s_rs_leadership` accel block: `rs_rating_slope_120d` (line 141)
- `_compute_s_rs_leadership` confluence block: `within_basket_z_63d` (line 157)

Rationale: a NaN within-basket z indicates "basket too small for a meaningful
ranking" — semantically equivalent to "this stock is at the basket median,"
which is z = 0. Filling with 0 is the unbiased, zero-information choice.

**Fix 2 — Universe cleanup.** Three tickers cannot be scored cleanly even
with the fillna fix:

- `CTRA` — post-merger (Cabot/Cimarex 2021), insufficient continuous history
- `TRUL.CN` — Canadian listing, sparse OHLCV
- `EUROB.AT` — Greek ATHEX listing, data limitations

Removed entirely from `data/universe.py` (PRIMARY_BASKETS,
PRIMARY_BASKET_CONSTITUENTS, MANUAL_OVERRIDES, TAGS, top-level CATEGORIES).
Side effect: the **Greece Reclassification** basket now has a single
constituent (`GREK`), which is below the 3-member health threshold but
intentionally retained.

**Fix 3 — Benchmark carve-out (SPY/QQQ).** Benchmarks were never in the
universe-level baskets but were being included in the scored feature panel
because `data_quality.py` returned them as PASS. Now:

- `BENCHMARKS` in `data/universe.py` is a `set` (`{"SPY", "QQQ"}`)
- `compute/features.py` excludes `BENCHMARKS` from `compute_features()`'s
  scored universe (still uses them as inputs for RS-vs-SPY computations)
- `compute/pipeline.py` carves out SPY/QQQ OHLCV into a dedicated
  `data/cache/benchmarks.parquet` (2,552 rows, 8 cols) for chart overlays

**Fix 4 — Strip exception lists.** The validator previously imported a
`KNOWN_BENCHMARKS` set and an `INSUFFICIENT_HISTORY_EXCEPTIONS` set. With the
universe now clean, every scored ticker must produce a valid CCQS — those
sets are removed from `compute/validation/level3_validation.py` (checks E, G,
J). No hardcoded exceptions remain in the validator.

**Post-fix Level 3 validation result (2026-05-22 snapshot):**

| Metric | Value |
|--------|-------|
| Scored universe | **858 stocks** |
| Total checks | 20,956 |
| Pass | 20,900 |
| Failures | **0** |
| Borderlines (all WARN) | 56 |
| External (yfinance) | 50/50 matched, 0 discrepancies |
| Verdict | REVIEW (no failures; 56 statistical-edge borderlines) |
| Elapsed | 2.9s |

Borderline categories: 49 `G_low_rs_strong_tier` (RS<20 stocks not in WEAK
tier — by-design borderline), 5 `D_s_climax_extreme_z` (|z|>5 outliers in
semiconductor / cybersec names), 1 `C_pct_ma_50_bounds` (FCEL, low-priced),
1 `C_pct_ma_200_bounds` (SNDK, recent IPO).

**OOS IC re-baseline (accepted as new official baseline).** The previous IC
table was computed with a 12%-coverage bug (NaN-CCQS stocks dropped from
the cross-section). Honest post-fix values:

| Horizon | t-stat | Mean OOS IC | Hit rate | Δ t vs prior |
|---------|--------|-------------|----------|---------------|
| 1d   | **+4.16** | +0.0173 | 68.2% | +0.30 (improved) |
| 5d   | +1.65 | +0.0168 | 61.4% | +0.22 |
| 20d  | +1.26 | +0.0225 | 56.8% | +0.26 |
| 60d  | +0.94 | +0.0166 | 59.5% | -0.03 |
| 126d | **+2.59** | +0.0412 | 69.2% | -0.31 (still significant) |
| 252d | **+2.05** | +0.0360 | 63.6% | +0.04 |

All three production horizons (1d, 126d, 252d) remain t > 2.0. The 126d drop
is acceptable — the prior +2.90 reading was artificially elevated by
selective NaN-dropping. New values stand as the canonical post-fix baseline.

---

### Phase 5.3 — Selective SP100 promotion (2026-05-23)

**Trigger.** Sandbox SP100 coverage-gap analysis (`compute/sandbox/sp100_analysis.py`)
identified twelve SP100 names absent from the production universe. The 870-ticker
sandbox run (production-passing 858 + 12 SP100-missing) produced OOS IC deltas of
+0.3% to ±2.0% across all six horizons versus the production-extended baseline,
demonstrating methodology stability under the SP100 subset addition. Twelve names
were evaluated; five are promoted, seven are explicitly excluded for the reasons
below.

**Five promotions.** Added to existing thematic baskets — no new baskets created,
no broad GICS sector baskets introduced.

| Ticker | Basket | CCQS (2026-05-22) | Grade | State | Rationale |
|--------|--------|-------------------|-------|-------|-----------|
| AAPL | Hyperscalers | 91.02 | A | TRENDING | Iconic mega-cap technology; clean fit with existing AMZN/GOOGL/META/MSFT/ORCL |
| BNY | Money Center Banks | 94.92 | S | TRENDING | Custody bank, prior ticker BK rebranded to BNY in 2024 |
| HON | Industrial Automation | 64.79 | B | TRENDING | Industrial conglomerate — best existing fit alongside ROK/ETN/EMR/AME/PH |
| SBUX | Restaurants and QSR | 66.56 | B | PULLBACK | Largest US restaurant chain; clean fit with MCD/YUM/QSR/CMG/DPZ |
| TGT | Grocery and Clubs | 85.17 | A | PULLBACK | Big-box mass-merchandiser — best existing fit with WMT/COST/KR/BJ/ACI |

Universe size: **863 passing tickers** (was 858 → +5). Declared universe: **884**
(was 879 → +5).

**Seven explicit non-promotions.** Excluded for the following reasons:

| Ticker | Reason |
|--------|--------|
| GOOG | Class-C share of GOOGL (already in Hyperscalers) — would double-count Alphabet exposure |
| BRK-B | Conglomerate insurance holding with no clean thematic fit; ticker hyphen handling complicates fetch |
| MMM | Diversified conglomerate; no single clean basket; would require new basket creation |
| T | Telecom carrier; no Telecom basket in production universe; would require new basket |
| TMUS | Telecom carrier; same — no Telecom basket exists |
| CHTR | Cable / broadband carrier; no Telecom/Cable basket exists |
| VZ | Telecom carrier; no Telecom basket exists |

The decision to add 5 (not 12) keeps thematic baskets coherent and avoids creating
single-member or two-member Telecom / Conglomerate baskets which would be below
the 3-member health threshold.

**Pipeline re-run.** End-to-end refresh on the 884-declared / 863-scored universe:

| Stage | Time |
|-------|-----:|
| features | 63.8s |
| z_scores | 56.0s |
| components | 4.7s |
| state | 0.5s |
| leadership | 0.2s |
| ccqs | 1.9s |
| setups | 0.6s |
| aggregation | 162.3s |
| reliability stack | 33.0s |
| snapshot | 0.8s |
| **Total** | **~325s** |

**Validation.** All eleven reliability sanity checks pass on the new snapshot
(`data/cache/sanity_checks.json`): `ccqs_in_0_100`, `state_probs_sum_to_1`,
`state_p_adj_sum_to_1`, `no_inf_components`, `grade_s_pct_in_2_15`,
`leadership_tier_values_valid`, `setup_confidence_in_0_1`, `index_alignment`,
`theme_ccqs_coverage`, `features_fresh_within_5d`, `universe_coverage`.

CCQS distribution post-promotion: mean 50.14, median 50.81, p1 2.51, p99 97.74.
Grade S share 6.37%, Grade A share 9.49%, S+A = 15.86% (within the 2–15% spec
target for S alone and well within the 30% S+A sanity ceiling).

**Sentinel drift.** Top-50 rank stability is **49/50 = 98%** (WDC drops out as BNY
enters at S-grade). Sentinel re-rank magnitudes on 14 incumbent names:

| Ticker | Pre | Post | Δ | | Ticker | Pre | Post | Δ |
|--------|-----|------|---|-|--------|-----|------|---|
| NVDA | 78.75 | 78.55 | -0.21 | | MCD | 9.37 | 9.12 | -0.25 |
| MSFT | 29.67 | 29.08 | -0.59 | | COST | 73.47 | 72.85 | -0.63 |
| GOOGL | 91.95 | 91.68 | -0.27 | | WMT | 50.48 | 49.46 | -1.02 |
| META | 16.49 | 16.04 | -0.45 | | JPM | 43.81 | 41.78 | -2.03 |
| AMZN | 88.64 | 88.35 | -0.29 | | BAC | 46.80 | 44.55 | -2.26 |
| AVGO | 81.18 | 80.96 | -0.22 | | WFC | 21.72 | 21.79 | +0.06 |
| ORCL | 65.06 | 64.51 | -0.55 | | TSLA | 73.92 | 73.68 | -0.24 |

Max |Δ| = 2.26 (BAC). The drift exceeds the ±0.5 informal target on 6/14
sentinels but is **mathematically expected** under cross-sectional percentile
ranking when high-quality names enter the cohort: BNY at S-grade (94.92) crowds
the Money Center Banks ranks (JPM/BAC drop ~2 points), and AAPL/TGT entering the
top decile compresses the percentile space for incumbents in their baskets. The
delta is not a methodology drift signal — it is the deterministic re-ranking
consequence of universe expansion. Methodology stability is confirmed by the
98% top-50 overlap and clean sanity-check pass.

**IC tracker headline (post-promotion, 863-stock universe, full 7-year window):**

| Horizon | IC mean | IC-tracker t-stat | hit rate |
|---------|---------|-------------------|---------:|
| 1d | +0.0153 | +2.87 | 56.2% |
| 5d | +0.0121 | +2.57 | 54.4% |
| 20d | +0.0118 | +2.78 | 55.1% |
| 60d | +0.0108 | +2.90 | 53.3% |
| 126d | +0.0233 | +7.41 | 59.3% |

**Important:** IC-tracker t-stats are computed by
[compute/reliability/ic_tracker.py](compute/reliability/ic_tracker.py) which pools
daily ICs across all dates in the history (`SE = std / √n_dates`, n=1362 at
126d). This is **apples-to-oranges with the Phase X.3 OOS-evaluation t-stats**
(window-averaged, `SE = std / √n_windows`, n=48 at 126d in the 5-year window).
Daily ICs at 126d overlap by 125/126 days and are not independent — pooling them
inflates t-stats by a factor of ~√(n_dates/n_windows) ≈ 4×. The IC-tracker
output is a monitoring headline for decay detection, not a statistical
significance test, and must not be cited as evidence of methodology improvement.

The Phase X.3 OOS-evaluation baseline (1d t=4.16, 126d t=2.59, 252d t=2.05)
remains the **published official baseline** per the Methodology Lock §6. The
post-Phase-5.3 IC-tracker values above are recorded as supplementary monitoring
only.

**Sandbox infrastructure preserved.** `compute/sandbox/` and `data/cache/sandbox/`
remain intact for future coverage-gap experiments. The next candidate evaluation
should re-run `compute/sandbox/sp100_analysis.py` (or an analogous script) on the
new prospect set before any further promotion.

**Dashboard sandbox tab hidden.** The Streamlit dashboard
([app/streamlit_app.py](app/streamlit_app.py)) gates the sandbox tab behind a
`SHOW_SANDBOX = False` module-level flag (default off in production). The
sandbox loader (`app/utils/data_loader_sandbox.py`), the sandbox compute stack
(`compute/sandbox/`), and the sandbox cache (`data/cache/sandbox/`) are all
unchanged — the gate only governs UI surface visibility. Flip `SHOW_SANDBOX = True`
to re-enable the tab without re-running any pipeline.

---

### Phase 5.5 — Naming standardization (2026-05-24)

**Trigger.** Presentation polish for institutional review. The state-classifier
vocabulary inherited from internal development used informal terms
(`COILING`, `CLIMACTIC`, `BROKEN`, `MIXED`) and the setup taxonomy mixed
colloquial labels ("Healthy Trend", "Weak Setup", "Mixed / Indeterminate")
with technical ones ("VCP Setup", "BB Squeeze with RS"). The renaming
standardizes on neutral finance vocabulary suitable for external audiences.
**Methodology is unchanged.**

**State value renames** (4 of 6 states; `TRENDING` and `PULLBACK` unchanged):

| Old | New |
|-----|-----|
| `COILING` | `CONSOLIDATING` |
| `CLIMACTIC` | `EXHAUSTION` |
| `BROKEN` | `DETERIORATING` |
| `MIXED` | `INDETERMINATE` |

Probability and state-adjusted columns (`p_*`, `p_adj_*`) renamed in lockstep
inside `state.parquet`. `STATE_WEIGHTS` lookup keys renamed in
[compute/ccqs.py](compute/ccqs.py) accordingly. Bayesian-averaging math is
identical because the dict keys move together with the lookups.

**Setup label renames** (18 of 29 labels; entries 11-12 added in Phase 5.6, entries 13-18 added in Phase 5.7):

| Old | New |
|-----|-----|
| Healthy Trend | Sustained Uptrend |
| Healthy Pullback | Routine Pullback |
| Healthy Consolidation | Constructive Consolidation |
| Strong Continuation | Trend Continuation |
| Weak Setup | Low-Confidence Pattern |
| Range-Bound Coil | Range Consolidation |
| Mixed / Indeterminate | Indeterminate Pattern |
| Late Stage | Late-Cycle Pattern |
| Broken Downtrend | Trend Failure |
| Broken Distribution | Distribution Pattern |
| Coil Within Strong Theme | Consolidation Within Strong Theme |
| Strong Coil Pre-Breakout | Tight Consolidation Pre-Breakout |
| Climax Parabolic | Parabolic Blow-Off |
| Climax Bearish Divergence | Exhaustion w/ Bearish Divergence |
| Climax Volume Confirmed | Volume-Confirmed Exhaustion |
| Climax Extended | Extended Exhaustion |
| Broken Capitulation | Capitulation Selling |
| Broken Bullish Divergence | Deteriorating w/ Bullish Divergence |

**Aggregation column renames** (`theme_aggregates.parquet`):

| Old | New |
|-----|-----|
| `pct_climactic` | `pct_exhaustion` |
| `pct_broken` | `pct_deteriorating` |

**Preserved (intentionally NOT renamed):**

- `leadership_tier` value `DETERIORATING` — leadership namespace. The
  state-classifier `DETERIORATING` and the leadership-tier `DETERIORATING`
  are stored in distinct columns of distinct parquet files; no downstream
  calculation joins them by name.
- `theme_class` values `MIXED`, `BROKEN_THEME`, `WEAKENING`, `STABLE`,
  `ELITE_THEME`, `STRONG_THEME`, `EMERGING_THEME`, `NARROW_LEADERSHIP` —
  theme-aggregate namespace, computed in §11 from breadth and `theme_ccqs`.
- "Distribution" in basket names ("Switchgear and Electrical Distribution",
  "Industrial Distribution"), the "Distribution Days (25d)" metric, and the
  `distribution_days_25` feature column — these reference share-distribution
  patterns (Wyckoff-style), not the renamed deteriorating state.
- Feature flag `climax_volume_flag` — methodology/feature namespace, used
  by state classification and the setup classifier. The component score
  `s_climax` referenced in the original Phase 5.5 preservation list was
  subsequently **removed entirely in Phase 6** (2026-05-25); the
  dashboard's component decomposition view now reports 9 components.

**Methodology preservation (verified bit-identically).** Phase 5.5 is a
relabeling only. The state-classification log-likelihoods, the Bayesian
averaging math, the setup-priority cascade, and the cross-sectional
standardization are unchanged. The migration renames Python identifiers,
parquet columns and string values, and JSON keys; no arithmetic is touched.

Comparison of fresh pipeline outputs (post-rename code + data) vs. the
pre-rename backup at `.migration_backup_phase_5_5/cache_backup/`:

| Field | Max \|diff\| | Notes |
|-------|-------------:|-------|
| `ccqs` | 0.00e+00 | 1,553,400 rows, bit-identical |
| `ccqs_raw` | 0.00e+00 | bit-identical |
| `ccqs_z` | 0.00e+00 | bit-identical |
| `grade` | 0 mismatches | full equality |
| each `p_*` (after key rename) | 0.00e+00 | probability vectors identical |
| each `p_adj_*` (after key rename) | 0.00e+00 | adjusted probabilities identical |
| `primary_state` (after rename) | 0/1,553,400 mismatches | classification identical |

The **Phase X.3 OOS IC baseline** (1d t=4.16, 126d t=2.59, 252d t=2.05)
is preserved unchanged per Methodology Lock §6 — naming has no effect on IC.

**Files affected.**

| Category | Count | Detail |
|----------|------:|--------|
| Python source | 13 | state classifier, CCQS weights, setup classifier, aggregation, anomaly detection, sanity checks, regularized weighting, level3 validation, data loader, color theme, Streamlit app, manual-overrides yaml comments |
| Tests | 2 | Phase 3 validation list + TV-snapshot canary pinned values |
| Cache parquet | 17 | live cache (4), dashboard slim (3), 2026-05-22 snapshot (4), sandbox (4), sp100 (2) |
| JSON sidecars | 6 | `anomalies.json` (×3), `pipeline_meta.json` (×3 — selective: `state_distribution` + `top_10_setups` only; `theme_class_distribution` preserved) |

**Migration tooling.** A one-shot data migration script is preserved at
[`scripts/phase_5_5_data_migration.py`](scripts/phase_5_5_data_migration.py)
for audit trail. It reads each parquet, applies column / value renames in
place (snappy compression preserved), and patches the JSON sidecars
selectively. Re-running it on already-migrated data is a no-op.

**Validation.** Post-migration end-to-end pipeline run completes in 209.6s.
All 11 reliability sanity checks pass (`data/cache/sanity_checks.json`).
State distribution after rename:

| State | Share |
|-------|------:|
| TRENDING | 16.87% |
| PULLBACK | 19.53% |
| CONSOLIDATING | 5.21% |
| EXHAUSTION | 2.20% |
| DETERIORATING | 28.07% |
| INDETERMINATE | 28.11% |

CCQS distribution: mean 50.14, median 50.81, S-grade share 6.37% (within
the 2–15% spec band). Top-10 setup distribution uses the new vocabulary
(post-Phase-5.8: "Indeterminate Pattern" 20.16%, "Range Consolidation"
12.17%, "Deteriorating (Generic)" 11.61%, "Routine Pullback" 9.54%,
"Trending (Generic)" 8.26%, ...).

---

### Phase 5.6 — Coil follow-up (2026-05-24)

Phase 5.5 renamed the `COILING` state to `CONSOLIDATING` and the
`Range-Bound Coil` setup to `Range Consolidation`, but two
Consolidating-state setups still carried the old "Coil" vocabulary
(`Coil Within Strong Theme`, `Strong Coil Pre-Breakout`). This
follow-up commit drops those references so the setup naming aligns
fully with the state vocabulary. (The `Climax *` and `Broken *`
sub-setups were initially preserved here but subsequently renamed in
Phase 5.7 — see below.)

| Old | New |
|-----|-----|
| Coil Within Strong Theme | Consolidation Within Strong Theme |
| Strong Coil Pre-Breakout | Tight Consolidation Pre-Breakout |

`scripts/phase_5_5_data_migration.py` was extended with the two
additional `SETUP_RENAMES` entries and re-run; the script is
idempotent, so it only touched the new labels and left the rest of the
caches untouched. Validation: 11/11 sanity checks pass; CCQS
bit-identical vs the 2026-05-22 snapshot (max|diff| = 0.00e+00, 0/863
grade mismatches); no residual `Coil` labels in any setups parquet.

---

### Phase 5.7 — Climax / Broken sub-setup rename (2026-05-24)

Phase 5.5 renamed the `CLIMACTIC` state to `EXHAUSTION` and `BROKEN` to
`DETERIORATING`, but the six Exhaustion / Deteriorating sub-setup
labels (`Climax Parabolic`, `Climax Bearish Divergence`,
`Climax Volume Confirmed`, `Climax Extended`, `Broken Capitulation`,
`Broken Bullish Divergence`) were initially preserved as chart-pattern
terms of art. On reviewing the deployed dashboard the labels read
inconsistently next to the renamed states, so the same naming-parity
argument that drove Phase 5.6 applies here. The new labels were
verified against the underlying detection logic (`atr_x_50`,
`bearish_divergence_20d`, `climax_volume_flag`, etc.) before adoption.

| Old | New |
|-----|-----|
| Climax Parabolic | Parabolic Blow-Off |
| Climax Bearish Divergence | Exhaustion w/ Bearish Divergence |
| Climax Volume Confirmed | Volume-Confirmed Exhaustion |
| Climax Extended | Extended Exhaustion |
| Broken Capitulation | Capitulation Selling |
| Broken Bullish Divergence | Deteriorating w/ Bullish Divergence |

The methodology-layer identifiers `s_climax` (component score) and
`climax_volume_flag` (feature column) are intentionally preserved —
they refer to the technical detection feature, not the user-facing
setup label, and renaming would require touching the components and
features compute paths with no presentation benefit.

The reference TradingView snapshot for NVDA in
[tests/reference/tv_snapshots.py](tests/reference/tv_snapshots.py)
was updated in lockstep so the bit-identical reference test stays
green. Validation: 11/11 sanity checks pass; CCQS bit-identical vs the
2026-05-22 snapshot; no residual `Climax *` or `Broken Capitulation` /
`Broken Bullish Divergence` labels in any setups parquet.

---

### Phase 5.8 — Setup label accuracy audit (2026-05-25)

Tier A of the Priority 1 foundation work. The audit re-examined each of
the 29 setup labels against the actual detection logic in
[compute/setup_classifier.py](compute/setup_classifier.py) and renamed
any that overclaimed relative to what the math measures. Two categories
of mismatch were corrected:

**Specific patterns** (4 renames). The label promised a property the
math doesn't verify:

| Old | New | Why |
|-----|-----|-----|
| Parabolic Blow-Off | Extreme Extension | Trigger is `atr_x_50 ≥ 6.5` only — no climactic-volume or parabolic-shape gate, so "Blow-Off" overclaimed |
| Trend Failure | Sustained Weakness | Trigger is `pct_ma_50 < -8` — a static position threshold, not a trend-transition event |
| Tier S Pullback | Premium Pullback | The 6-feature gate matches "high-quality pullback" but never checks CCQS grade — "Tier S" conflated grade vocabulary with setup detection |
| Emerging Leader (Multibagger Setup) | Emerging Leader | The pattern is mid-RS + accelerating + multi-timeframe + volume; "(Multibagger Setup)" was forward-looking marketing |

**State catch-alls** (4 renames). Each catch-all fires when the primary
state matches but no specific pattern triggered, so labels that implied
duration / bias / cycle position / confidence overclaimed:

| State | Old | New |
|-------|-----|-----|
| TRENDING | Sustained Uptrend | Trending (Generic) |
| CONSOLIDATING | Constructive Consolidation | Consolidating (Generic) |
| EXHAUSTION | Late-Cycle Pattern | Exhaustion (Generic) |
| DETERIORATING | Low-Confidence Pattern | Deteriorating (Generic) |

The remaining 21 labels were verified accurate and unchanged: Exhaustion
w/ Bearish Divergence, Volume-Confirmed Exhaustion, Extended Exhaustion,
Capitulation Selling, Deteriorating w/ Bullish Divergence, Distribution
Pattern, Elite Leader Continuation, Elite Leader Pullback, Theme Leader
Pullback, Trend Continuation, Trending Leadership, Pullback to 21EMA,
Pullback to 50MA, Consolidation Within Strong Theme, Tight Consolidation
Pre-Breakout, VCP Setup, BB Squeeze with RS, Range Consolidation, Failed
Breakout, Routine Pullback, Indeterminate Pattern.

Data migration ([scripts/phase_5_5_data_migration.py](scripts/phase_5_5_data_migration.py))
extended with the 8 new entries plus chained-rename updates so a parquet
at any prior Phase 5.5–5.7 vocabulary migrates to the Phase 5.8 final
label in one pass. TV reference snapshots for NVDA, META, JPM, UNH
updated in lockstep.

**Caveat — "Consolidation Within Strong Theme" (#18) is currently
unreachable.** Its `theme_strong` gate is hardcoded `False` because the
theme aggregation layer runs after the setup classifier in the Phase 3
pipeline. The label exists for forward compatibility; no row can earn it
in the current pipeline order.

---

### Phase 6 — Foundation fixes (2026-05-25)

Three improvements to the composite layer driven by the Priority 1
foundation-fix mandate (empirical signal quality over theoretical
elegance):

**1. Per-date winsorization of CCQS display values**
([compute/ccqs.py:165](compute/ccqs.py:165))

The prior global `np.nanpercentile(ccqs_raw, 1.0/99.0)` clip computed one
fixed lower/upper threshold across the entire 1.55M-row long frame and
clipped every row against the same two numbers. Because that pair of
numbers was strictly determined by the global distribution, every row
beyond the threshold collapsed to those exact two values:

- Pre-fix: max tie count = **12,281 rows pinned at 97.74**, 12,281 at
  2.51. Total of 24,562 rows (≈1.6% of universe-days) lost any
  cross-sectional dispersion within their date.
- Post-fix (per-date `p1/p99` via [`_per_date_winsorize`](compute/ccqs.py:125)):
  max tie count = **9 rows**, 1,205,080 unique values across 1.55M rows.

Per-date `p1` ranges 0.64 – 5.71 across the 1,800 dates; `p99` ranges
94.50 – 99.18. Bear-market days clip 25+ tops, bull-market days clip 30+
floors — these previously collapsed to the same global pair regardless
of when they occurred. The fix preserves cross-sectional dispersion
within each date by clipping each row against its own date's local
tails.

Grade distribution is **unchanged** (S 6.37% / A 9.49% / B 19.73% /
C 19.74% / D 23.73%) because grading already used per-date quantiles —
the global clip only ever affected display values, never grade
assignment. Only 32,099 rows (2.07%) change display value; median |Δ| =
0.41 CCQS points, max 3.03.

**2. Removed `s_climax` from the component set**
([compute/components.py:51](compute/components.py:51),
[compute/ccqs.py:62](compute/ccqs.py:62))

`s_climax` carried weight 0.00 in every state since Phase X.2.1
(mean OOS IC = −0.0242, significantly negative at two horizons). The
component dimension dropped from 10 → 9. The math was also inverted vs
the label: `raw = 100 − (extension_penalty + time_score +
vol_climax_score)`, so a "high s_climax" meant *less* climactic risk —
contributing to the negative OOS IC. Removing it is bit-identical for
CCQS (verified: mean / median / all grade percentages unchanged) since
its weight was already zero, and simplifies the code surface without
loss of signal. The underlying features (`climax_volume_flag`,
`days_near_52w_high_60d`, `consecutive_high_intensity`) are still
computed and consumed by state classification and the setup classifier.

**3. Diagnostic fields in `ccqs_meta.json`**

Added `ccqs_unique_values`, `ccqs_max_tie_count`, and
`winsorization: "per-date p1/p99"` fields so any future tie regression
is detectable from the meta JSON alone.

---

### Known caveats & limitations (Phase 6 documentation)

**Cross-sectional standardization caveats**

All components are z-scored cross-sectionally per date. This means:

1. Component values are always relative to *that date's universe*, not
   to an absolute baseline. A "1.0 z" in 2020 reflects a different raw
   feature value than a "1.0 z" in 2026 if the universe distribution
   shifted.
2. CCQS percentile values reflect *relative rank within the date*, not
   absolute quality. A market-wide drawdown compresses the dispersion,
   so a CCQS of 80 in March 2020 represents a meaningfully different
   stock than a CCQS of 80 in March 2024.
3. The Bayesian state-weighted composite has narrow variance (≈ 0.14)
   before per-date renormalization. The `_per_date_zscore()` call in
   `compute_ccqs()` is what restores N(0,1) shape so `Φ(z)·100` spans
   the full 0–100 range.

**Per-date winsorization trade-off**

Per-date clipping eliminates the global tie problem but still creates
~1% of each date's universe pinned at the date's local `p99`. For a
900-stock day, that's ~9 stocks tied at the top. These ties are
intentional (winsorization is the standard treatment for display-value
extremes) and only affect the *display value*, not the *grade* (grades
use per-date quantile thresholds independently).

**State-confidence blending**

When `max(p_state) < 0.7`, state probabilities are blended toward
INDETERMINATE (50/50 if `max < 0.5`, 70/30 if `< 0.7`). This is by
design — it prevents low-confidence state classifications from
dominating Bayesian-averaged CCQS — but means INDETERMINATE-state
stocks effectively inherit the INDETERMINATE weight column, which is
a near-average column. The signal-to-noise on these rows is therefore
weaker by construction. State distribution shows 28.1% INDETERMINATE
in the current cache.

**`s_climax` removal — history note**

Phase X.2.1 zeroed `s_climax` in every state (negative OOS IC). Phase 6
removed it from the component set entirely. If a future validation
phase identifies a real climactic-extension signal worth modeling, the
component should be re-derived with an inverted sign (high score =
high climactic risk) and weighted negatively in the composite. The
underlying features remain available.

**TV reference snapshot staleness**

The reference values in [tests/reference/tv_snapshots.py](tests/reference/tv_snapshots.py)
were last pinned 2026-05-22 against a Phase 4 build. CCQS values
subsequently drifted 5–8 points on several large-caps (MSFT, META,
AMZN, TSM, NVDA) due to the Phase X.3 component-weight redistribution,
which happened before this repo's first commit. Per-date winsorization
(Phase 6) does **not** affect any of the 10 canaries — verified by
running both global and per-date paths on the live components/state
cache and confirming identical outputs. Refresh of CCQS / grade / setup
pins to the current build is a pending decision; the technical-indicator
pins (close, RSI, ADX, ATR, pct_ma_*) remain accurate within tolerance.

**Setup label "Consolidation Within Strong Theme" is structurally
inactive in Phase 3** — its `theme_strong` gate is hardcoded `False`
because the theme aggregation layer runs after the setup classifier.
The label is preserved for forward compatibility.

---

### Priority 2 — Empirical validation of current methodology (2026-05-25)

Investigation-only pass (no code changes). Two parallel studies under the
Phase 6 baseline (9 components, per-date winsorized CCQS):

  - **2a Bootstrap CIs on STATE_WEIGHTS** — 54 cells (9 components × 6
    states), 4 horizons (5d / 20d / 60d / 126d), block bootstrap with
    21-day blocks and 1000 iterations. Per-cell IC = cross-sectional
    Spearman of component vs forward return, restricted to rows where
    `primary_state == s`.

  - **2b Conditional CCQS IC** — partitioning the 1,553,400 row-days by
    primary state, dollar-volume quintile, per-stock 60d realized-vol
    quintile, SPY 20d realized-vol tercile (market regime), year, and
    91 primary baskets (n ≥ 5 members each).

Reference baseline IC of unconditional CCQS (1,362–1,483 dates):
`5d: +0.0121 (t=2.57)`, `20d: +0.0118 (t=2.78)`, `60d: +0.0108 (t=2.90)`,
`126d: +0.0233 (t=7.41)`. All four horizons clear t > 2.0 unconditionally.

**Headline finding 2a-i — Most state-conditional weight cells are
statistically indistinguishable from zero.** Out of 54 cells per horizon
(90% bootstrap CI excluding zero):

| Horizon | Sig positive | Sig negative | Insignificant |
|---------|--------------|--------------|---------------|
|  5d  |  9 / 54  |  3 / 54  | 42 / 54 (78%) |
| 20d  |  5 / 54  |  5 / 54  | 44 / 54 (81%) |
| 60d  | 13 / 54  |  5 / 54  | 36 / 54 (67%) |
| 126d | 19 / 54  |  3 / 54  | 32 / 54 (59%) |

At the 20d institutional horizon, only ~9% of weight cells carry an IC
statistically distinguishable from zero. This does not mean the matrix
is wrong — it means the 1,468 dates of data are not enough to resolve
individual per-state per-component IC at 90% confidence for most cells.

**Headline finding 2a-ii — State-conditional weighting is largely
empirically arbitrary at 20d.** For each (component, horizon) we
compared IC across all 15 state-pairs:

| Horizon | State-pairs differing at 90% CI |
|---------|--------------------------------:|
|  5d  | 30 / 135  (22%) |
| 20d  | 11 / 135  ( 8%) |
| 60d  | 33 / 135  (24%) |
| 126d | 46 / 135  (34%) |

At 20d, only 8% of state-pairs show statistically distinguishable IC
for the same component. The remaining 92% of pairs cannot reject the
null hypothesis that the component has the same IC in both states.
State-conditional weighting at this horizon adds structural / narrative
value but limited measurable OOS signal.

The state-pair differences that *do* emerge are concentrated:
EXHAUSTION state appears in most significant pairs, suggesting EXHAUSTION
is the one regime worth treating differently. CONSOLIDATING is the
next most distinguishable.

**Headline finding 2a-iii — Component-level empirical quality is
strongly unequal.** Across the 24 cells per component (6 states × 4
horizons):

| Component | avg IC | sig+/24 | sig−/24 | total weight | Verdict |
|-----------|-------:|--------:|--------:|-------------:|---------|
| s_rs | +0.023 | 10 |  0 | 5.24 | **Carrier** |
| s_structure | +0.018 | 11 |  0 | 4.48 | **Carrier (most consistent)** |
| s_rs_leadership | +0.016 |  8 |  0 | 6.04 | **Carrier (highest weight)** |
| s_mtf | +0.010 |  6 |  0 | 3.56 | **Carrier (smaller magnitude)** |
| s_extension | +0.005 |  4 |  0 | 0.20 | Marginal positive (correctly small weight) |
| s_rsl | +0.004 |  2 |  2 | 0.56 | Noise / neutral |
| s_trend_slope | +0.001 |  3 |  3 | 0.52 | Noise / neutral |
| s_momentum | +0.001 |  2 |  5 | 0.24 | Marginal negative |
| **s_demand** | **−0.009** | **0** | **6** | **3.16** | **Negative carrier — actively harmful** |

The four carriers (s_rs, s_rs_leadership, s_structure, s_mtf) account
for total weight 19.32 / 54 = ~64% of the matrix. Within those four,
weight is well-aligned with the sign of empirical IC.

**`s_demand` is the next removal candidate.** Like `s_climax` before it,
`s_demand` carries the third-highest total weight (3.16, second only to
`s_rs_leadership` and `s_structure`) despite having an average IC of
−0.009 and 6 of 24 cells with significantly negative IC. The cells with
significantly negative IC include `s_demand` in CONSOLIDATING (w=0.15)
at all four horizons, PULLBACK at 20d and 60d, and INDETERMINATE at 60d.
Removing or zeroing `s_demand` would free ~10% of total weight for the
four carrier components.

Pearson correlation between the current matrix and empirical IC across
all 54 cells:

| Horizon | Pearson | Spearman | p-value | OLS slope |
|---------|--------:|---------:|--------:|----------:|
|  5d  | +0.465 | +0.527 | <0.001 | +0.086 |
| 20d  | +0.403 | +0.399 |  0.002 | +0.056 |
| 60d  | +0.269 | +0.272 |  0.049 | +0.059 |
| 126d | +0.263 | +0.308 |  0.023 | +0.061 |

The matrix is positively correlated with empirical IC at every horizon
— the *directional* intuition behind hand-crafted weights is right.
But the moderate correlation (0.26–0.47) means only 7–22% of the
variance in actual per-cell IC is captured by current weight choices.
Half or more of the per-cell weight magnitude is not statistically
informative.

**Headline finding 2b-i — CCQS works best on smaller, more volatile
stocks during low-vol markets.** Monotonic patterns:

| Bucket | 60d IC | 126d IC | Notes |
|--------|-------:|--------:|-------|
| Dollar-volume Q1 (smallest) | +0.048 | +0.061 | Strongest single bucket |
| Dollar-volume Q3 | +0.015 | +0.022 | Mid |
| Dollar-volume Q5 (largest) | **−0.017** | **−0.007** | Negative in mega-caps |
| Per-stock vol Q1 (low vol) | +0.021 | +0.020 | Weaker |
| Per-stock vol Q5 (high vol) | +0.041 | +0.058 | Strong |
| Market vol regime LOW | +0.039 | +0.045 | Strong all horizons |
| Market vol regime MID | +0.007 | +0.051 | Mixed |
| Market vol regime HIGH | **−0.014** | **−0.025** | **Signal fails in crises** |

The signal flips sign in mega-caps and high-vol regimes — these are
explicit out-of-distribution domains where the composite should not be
trusted at long horizons.

**Headline finding 2b-ii — Regime sensitivity by year.**

| Year | 5d | 20d | 60d | 126d |
|------|----|-----|-----|------|
| 2020 | +0.038 (t=2.1) | +0.054 (t=3.4) | +0.035 (t=2.7) | **−0.052 (t=−6.1)** |
| 2021 | −0.018 | **−0.058 (t=−6.3)** | **−0.062 (t=−7.8)** | **−0.045 (t=−6.6)** |
| 2022 | +0.017 | +0.020 | +0.012 | +0.026 (t=3.0) |
| 2023 | −0.015 | −0.014 | +0.011 | +0.082 (t=12.9) |
| 2024 | +0.026 (t=2.7) | +0.039 (t=4.2) | +0.008 | +0.061 (t=14.1) |
| 2025 | +0.013 | +0.021 (t=2.2) | +0.046 (t=5.4) | +0.033 (t=4.7) |

The 2021 meme-stock / SPAC-mania year drove the composite to negative
IC at every horizon. The Phase X.3 multi-window OOS framework averages
across regimes and is therefore conservative in good regimes and too
optimistic in adverse ones. **The signal does not work in speculative-
euphoria regimes** — a category to flag in pre-trade conditioning.

**Headline finding 2b-iii — Sector dispersion is enormous.**

Among 91 baskets with ≥ 100 row-days, basket-level 60d IC ranges from
**+0.205** (Hotels and Casinos) to **−0.275** (Household and Personal
Care). Median basket IC at 60d is −0.009, IQR [−0.063, +0.049]. The
positive tail is dominated by cyclicals and recovery names (Hotels,
Auto Affordability, Oilfield Services, Heavy Machinery, Coal,
Aggregates). The negative tail is dominated by defensives and stable
traditional sectors (Household/Personal Care, Gold Royalty, Energy
Majors, Gaming Publishers, Railroads, Beverages, Industrial Automation).

CCQS encodes a clear **cyclical / non-defensive bias**. The composite
favors stocks whose returns are momentum / quality-driven and underweights
or actively works against stocks whose returns are mean-reverting or
yield-dominated.

**Conditional state IC (CCQS, full universe).**

| State | 5d | 20d | 60d | 126d |
|-------|----|-----|-----|------|
| TRENDING | +0.014 (t=3.0) | +0.006 | +0.028 (t=7.1) | +0.042 (t=12.3) |
| PULLBACK | +0.015 (t=2.9) | +0.007 | +0.013 (t=2.9) | +0.010 (t=2.6) |
| CONSOLIDATING | +0.026 (t=4.6) | +0.025 (t=4.6) | +0.039 (t=7.6) | +0.029 (t=5.7) |
| EXHAUSTION | +0.023 (t=3.0) | **−0.002 (t=−0.3)** | +0.007 | +0.032 (t=3.7) |
| DETERIORATING | +0.005 | +0.006 | +0.009 (t=2.6) | +0.018 (t=5.3) |
| INDETERMINATE | +0.006 | +0.011 (t=2.6) | +0.004 | +0.019 (t=5.6) |

CONSOLIDATING is the strongest state for CCQS — significant at all four
horizons. EXHAUSTION at 20d shows IC ≈ 0 (t = −0.32) — the signal does
not predict 20d returns for stocks in this state, even though it does
at 5d and 126d. This is consistent with the empirical literature on
momentum-crash behavior at intermediate horizons after extension peaks.

**Where Priority 2 leads.**

The empirical evidence motivates Priority 3 — empirically-driven
simplification:

1. **Reduced-component test**: a CCQS using only the four carriers
   (s_rs, s_rs_leadership, s_structure, s_mtf) should perform at least
   as well as the current 9-component composite. To be verified
   under Priority 3.

2. **`s_demand` removal**: parallel to `s_climax` in Phase 6 — drop or
   zero the component, redistribute its ~10% weight to the four carriers.

3. **State-conditional flattening**: at 20d, weights essentially could
   be made flat across states with no measurable OOS loss. Whether to
   keep state-conditioning for 5d / 60d / 126d (where ~25-34% of
   state-pairs differ) is a separate decision.

4. **Pre-trade conditioning**: signal performance is so different across
   regime / cap / sector that the composite should not be applied
   uniformly. Specifically:
   - mega-caps (Q5 by dollar volume) — disable or invert
   - high-market-vol regimes — disable
   - 2021-like speculative-euphoria years — disable
   - defensive sectors — apply with diminished confidence

5. **Bit-identical OOS validation gate**: any Priority 3 changes should
   preserve or improve the Phase X.3 OOS baseline (1d t=4.16, 126d
   t=2.59, 252d t=2.05). The current Phase 6 baseline is 5d t=2.57,
   20d t=2.78, 60d t=2.90, 126d t=7.41 — all above t=2.0.

---

### Phase 7 — Priority 3a: `s_demand` removal + carrier redistribution (2026-05-25)

Empirically-driven simplification motivated by the Priority 2 finding
that `s_demand` carried 10–15% of weight per state while averaging
−0.009 OOS IC across 24 (state × horizon) cells, with 6 cells
significantly negative (CONSOLIDATING at all four horizons, PULLBACK
at 20d / 60d, INDETERMINATE at 60d).

**Methodology.** Zero `s_demand` in every state and redistribute the
freed weight proportionally to the four carrier components (`s_rs`,
`s_rs_leadership`, `s_structure`, `s_mtf`) by their existing
within-carrier weight share. Each state row is then renormalized to
sum to 1.0. No other weight cell is touched; `s_rsl`, `s_trend_slope`,
`s_extension`, `s_momentum` keep their current weights. Surgical change.

The new STATE_WEIGHTS matrix is in [compute/ccqs.py:62](compute/ccqs.py:62).
Per-state Δ on the four carriers:

| State | s_demand removed | s_rs Δ | s_rs_leadership Δ | s_structure Δ | s_mtf Δ |
|---|---:|---:|---:|---:|---:|
| TRENDING | −0.100 | +0.030 | +0.030 | +0.022 | +0.018 |
| PULLBACK | −0.130 | +0.036 | +0.041 | +0.030 | +0.023 |
| CONSOLIDATING | −0.150 | +0.038 | +0.042 | +0.042 | +0.028 |
| EXHAUSTION | −0.150 | +0.041 | +0.052 | +0.030 | +0.028 |
| DETERIORATING | −0.150 | +0.038 | +0.047 | +0.038 | +0.028 |
| INDETERMINATE | −0.110 | +0.030 | +0.035 | +0.024 | +0.020 |

**Validation: per-date IC (full history, paired block bootstrap 90% CI).**

| Horizon | Pre IC | Post IC | Δ | 90% CI on Δ | Verdict |
|---|---:|---:|---:|---|---|
| 5d | +0.0121 | +0.0137 | +0.0016 | [+0.0003, +0.0028] | **post better** |
| 20d | +0.0118 | +0.0135 | +0.0017 | [−0.0003, +0.0035] | directional, not sig |
| 60d | +0.0108 | +0.0144 | +0.0037 | [+0.0016, +0.0059] | **post better** |
| 126d | +0.0233 | +0.0259 | +0.0026 | [+0.0009, +0.0044] | **post better** |

**Validation: Phase X.3 walk-forward (252-train / 21-test, 73 windows).**

| Horizon | Pre OOS / t | Post OOS / t | Paired Δ | Paired t | Verdict |
|---|---|---|---:|---:|---|
| 5d | +0.0105 / 1.28 | +0.0120 / 1.42 | +0.0015 | 2.01 | **post better** |
| 20d | +0.0106 / 0.71 | +0.0121 / 0.80 | +0.0015 | 1.34 | directional, not sig |
| 60d | +0.0086 / 0.58 | +0.0122 / 0.81 | +0.0036 | 2.77 | **post better** |
| 126d | +0.0240 / 1.82 | +0.0269 / 2.02 | +0.0029 | 2.64 | **post better** |

Both frameworks agree: significant improvement at 5d, 60d, 126d.
20d is directionally positive (+14% in mean IC) but the change is
not statistically distinguishable. Notably, the post-Phase-7 126d
walk-forward t-statistic crosses the t > 2.0 institutional bar that
the pre-Phase-7 composite narrowly missed (1.82 → 2.02).

**Grade and ranking stability.** Grade distribution preserved within
rounding (S 8.05% / A 12.00% / B 24.95% / C 24.97% / D 30.02%).
13.19% of rows experience a grade change — almost all are one-step
shifts between adjacent grades on stocks near a per-date quantile
boundary. Spearman rank correlation between pre- and post-Phase-7
CCQS is **0.9901**. Mean |Δ CCQS| is 3.16 points; max 31.4 points.

**Conditional-regime robustness.** Tested whether any specific bucket
gets worse:

- Market vol regime: post ≥ pre in 11 of 12 cells (LOW 5d flat at
  −0.0002). Critically, the problematic HIGH regime improves at every
  horizon (HIGH 60d −0.0135 → −0.0100; HIGH 126d −0.0245 → −0.0235).
- Dollar-volume quintile: post ≥ pre in 19 of 20 cells (Q3 20d flat).
  The mega-cap (Q5) regime improves at every horizon (Q5 60d
  −0.0167 → −0.0109; Q5 126d −0.0069 → −0.0034). Still negative but
  materially less so — these remain documented out-of-domain conditions.
- Year buckets (27 cells with ≥1000 rows): post ≥ pre in 22; flat in 3;
  two minor regressions both confined to **2020 long horizons**
  (60d −0.0022, 126d −0.0071). 2020 was the COVID liquidity shock —
  `s_demand` may have captured shock-specific signal not present elsewhere.
  This is the single regime where the simplification loses signal, and the
  losses are small in absolute terms. **Documented caveat below.**
- 2021 (the negative-IC meme/SPAC year): post improves at every horizon
  by +0.003 to +0.008. The simplification helps where the signal was
  weakest before.

**Implementation.** Code change is the `STATE_WEIGHTS` dict in
`compute/ccqs.py`. `s_demand` is **kept as a zero-weight diagnostic
component** in `compute/components.py` (parallel to `s_climax`'s
pre-Phase-6 history). It still appears in `components.parquet` and
the dashboard component decomposition; it just contributes 0 to CCQS.
This is the safer mid-state — no risk of breaking downstream paths
that reference the field, and the field remains available for
diagnostic display or future re-enable. A later phase may follow the
Phase 6 model and remove the underlying computation entirely.

**Known caveat — COVID-2020 long-horizon regression.** The 2020 60d /
126d minor IC loss reflects a known limitation: `s_demand` (up/down
volume ratios, accumulation/distribution line, distribution-day count,
CMF, volume z-score) carries information about liquidity-shock-driven
selling that other components do not capture. In a comparable
crash-then-V-shaped-recovery regime, the post-Phase-7 composite would
under-perform the pre-Phase-7 composite by roughly the magnitude
observed (Δ IC ≈ −0.003 to −0.007). The improvement at every other
year × horizon cell outweighs this loss in expectation, but the loss
is real and worth flagging for users interpreting CCQS during a
liquidity crisis.

**TV reference snapshots** — *not* refreshed in this commit. Per
Priority 3 plan, refresh deferred until Priority 3b and 3c complete
so we make a single pin update covering all of Priority 3.

---

### Priority 3 — Simplification investigation summary (2026-05-25)

Three weight-matrix simplification hypotheses were tested with the
in-memory CCQS framework + paired bootstrap + walk-forward OOS. One
shipped (3a, now Phase 7). Two were skipped on regime-level
degradation evidence (3b and 3c). The skipped tests revealed an
architectural feature worth documenting.

| Test | Construction | Headline OOS Δ vs Phase 7 | Status |
|---|---|---|---|
| **3a** | s_demand → 0 in all states; redistribute to four carriers | 5d/60d/126d sig improved | **Shipped (Phase 7)** |
| **3b** | Reduced 4-carrier-only (zero s_rsl, s_trend_slope, s_extension, s_momentum everywhere) | 5d/20d marginal improvement; EXHAUSTION 60d −48%, 126d −26% | Skipped |
| **3c** | Hybrid (zero non-carriers in TRENDING/PULLBACK/DETERIORATING/INDETERMINATE only; preserve EXHAUSTION + CONSOLIDATING) | Essentially identical to 3b; EXHAUSTION regression persisted | Skipped |

**Architectural finding: confidence-blending mutes per-state weight
customization for low-confidence states.**

Phase X.2.1 introduced a confidence-blending step in
[compute/state.py](compute/state.py): when `state_confidence < 0.7`, the
state probabilities are blended toward INDETERMINATE (50/50 if
`max(p) < 0.5`, 70/30 if `< 0.7`). The blended probabilities `p_adj_<s>`
are then used for Bayesian-averaging the state-conditional component
weights:

    ccqs_z_raw = Σ_state p_adj_<state> · Σ_comp w[state][comp] · z_comp

This design correctly prevents low-confidence state classifications from
dominating CCQS. But it also means **a row classified as state X uses
state X's weight column only partially** — the rest comes from the
state columns its `p_adj` mass falls on. The Priority 3c investigation
quantified this for the live cache:

| Primary state | n rows | Mean state_confidence | Mean p_adj of own column | Mean p_adj of INDETERMINATE column |
|---|---:|---:|---:|---:|
| TRENDING | 262,002 | 0.61 | 0.47 | 0.38 |
| PULLBACK | 303,456 | 0.54 | 0.38 | 0.46 |
| **CONSOLIDATING** | 81,002 | 0.51 | **0.33** | **0.51** |
| **EXHAUSTION** | 34,215 | 0.60 | **0.45** | **0.45** |
| DETERIORATING | 436,066 | 0.69 | 0.61 | 0.32 |
| INDETERMINATE | 436,659 | 0.73 | 0.83 | 0.83 |

Implications:

1. **INDETERMINATE acts as a universal fallback column.** Across the
   six states, INDETERMINATE's column contributes a weighted average of
   45–80% of every state's CCQS. Changes to the INDETERMINATE column
   propagate to every state's stocks.
2. **State-conditional differentiation has reduced reach for
   low-confidence states.** TRENDING / PULLBACK / CONSOLIDATING /
   EXHAUSTION all have mean confidence 0.51–0.61, so their own
   columns contribute only 33–47% of their stocks' CCQS. Customizing
   those columns has limited effect on those stocks specifically.
3. **High-confidence states are where weight customization matters
   most.** INDETERMINATE (own column 83%) and DETERIORATING (own
   column 61%) are the two states whose customized weights actually
   reach their stocks at full magnitude.
4. **EXHAUSTION-state long-horizon signal cannot be cleanly isolated.**
   The 3c hybrid preserved EXHAUSTION's column exactly but still lost
   60d/126d EXHAUSTION-state signal — because EXHAUSTION-state stocks
   pull 45% from INDETERMINATE, and 3c zeroed non-carriers in
   INDETERMINATE.

This is not a defect; it's a deliberate property of the
confidence-blending design. But it sets a practical ceiling on what
state-conditional weight tuning can achieve within the current
architecture. Future simplification work that wants to remove non-carrier
components further would need to either (a) relax confidence-blending
(architectural change with downstream effects), (b) accept the
low-confidence-state signal cost as the price of simplification, or
(c) work on a different axis (e.g. feature-level rather than
component-level reduction).

**Audit trail for skipped tests preserved.** The detailed Priority 3b
and 3c findings live in commit message history and the original
investigation outputs (`/tmp/p3b_results.json`, `/tmp/p3c_results.json`
on the build machine; reproducible by re-running
`/tmp/p3b_carrier_only.py` and `/tmp/p3c_hybrid.py`). The decision not
to implement either is documented here. **Priority 3a (Phase 7,
s_demand removal) captured the available empirical wins within the
current architecture.**

---

### Priority 3d — Conditional performance warnings, display layer (2026-05-25)

Honest disclosure surface in the Streamlit dashboard. **No methodology
change** — CCQS values, grades, components, state probabilities, and
the OOS validation framework are all bit-identical. Only the display
layer is touched.

Motivated by Priority 2b's conditional-IC findings: CCQS has documented
regimes where signal is reduced or negative. The dashboard now surfaces
these directly so users do not silently misuse the score in
out-of-domain conditions.

**Implementation surface:**

1. New regime context bake into the slim dashboard cache:
   [`compute/build_dashboard_cache.py`](compute/build_dashboard_cache.py)
   writes a `regime_context.json` containing:
   - Per-ticker dollar-volume quintile for the latest snapshot date
     (Q5 = mega-caps where CCQS turns negative at 60d/126d)
   - SPY 20d realized vol tercile thresholds + current regime label
   - Frozen list of 10 "defensive" baskets that had significantly
     negative basket-level 60d IC in the Priority 2b analysis
2. Dashboard top-of-page banner: when SPY 20d vol is in the HIGH
   tercile, a warning explicitly says CCQS IC turns negative at
   longer horizons in this regime. Hidden in LOW / MID regimes.
3. Stock Detail reliability chips: rendered below the existing header.
   Up to four chips per stock:
   - "Mega-cap" — for tickers in dollar-volume Q5
   - "Defensive sector" — for tickers in the 10 defensive baskets
   - "High market vol regime" — when SPY regime is HIGH (also already
     shown as top-of-page banner)
   - "EXHAUSTION 20d caveat" — for tickers classified as EXHAUSTION
     state, flagging the documented near-zero 20d IC (t = -0.3)
   Each chip has a tooltip with the specific IC numbers from
   Priority 2b. Chips disappear when nothing applies (clean stocks
   in normal regimes show no chips).
4. New "Where CCQS Works Best" and "Known Limitations" expanders
   in the System Health section: concise plain-language summary of
   Priority 2b findings (best-performing regimes, basket lists, OOS IC
   numbers per horizon).
5. Updated methodology blurb: corrected to reflect post-Phase-7 state
   (seven contributing components plus two zero-weight diagnostics,
   per-date winsorization, confidence-blended Bayesian state averaging).

**Defensive basket list:** Frozen from the Priority 2b bottom-10 by
60d basket-level IC. To refresh, re-run `/tmp/p2b_conditional_ic.py`
and update `DEFENSIVE_BASKETS` in
[`compute/build_dashboard_cache.py`](compute/build_dashboard_cache.py).
The list is intentionally static so the dashboard doesn't need to run
the IC analysis at request time.

Current frozen list: Household and Personal Care; Gold Royalty and
Streamers; Integrated Energy Majors; Gaming Publishers; Offshore
Drilling; Railroads; Diagnostics and Life Science Tools; LNG and LPG
Shipping; Beverages and Tobacco; Industrial Automation.

**Validation.** `data/cache/ccqs.parquet` vs
`data/cache/dashboard/ccqs.parquet` max |diff| = 0.000000000 — no
methodology change. Grade equality preserved 100%. The dashboard
compiles, imports, and the regime-context helpers produce expected
flag counts on test tickers (AAPL → Mega-cap; XOM → Mega-cap +
Defensive sector; EXHAUSTION-state ticker → EXHAUSTION caveat; small
non-defensive ticker → no flags).

---

### Phase X.4 — Targeted 20-60d horizon audit (2026-05-22)

Goal: push 20d and 60d OOS IC toward statistical significance (t > 2.0) while
preserving Phase X.3 M8 wins at 1d, 126d, 252d. Outcome: audit completed,
single rebalance tested, **rejected on adoption criteria** — declared
practical signal-extraction limit for this universe / architecture at the
20-60d band.

**Audit** (`compute/validation/horizon_audit_20_60d.py`,
`data/cache/horizon_specific_audit_20_60d.json`): for each of 119
standardized features, computed mean OOS IC + t-stat at 20d and 60d across
48 rolling windows; cross-referenced against current effective weight in
CCQS via `Σ_c state_avg_weight(c) × intra_component_weight(f, c)`.

Categorization: A = OOS IC > +0.025 at 20d OR 60d AND effective weight <
0.020 (under-allocated strong carrier). C = effective weight > 0.020 AND
|IC| < 0.005 at both 20d and 60d (over-allocated weak). B = everything else.

| Category | Count | Notes |
|----------|-------|-------|
| A — underweighted strong | 12 | clusters into 2 themes |
| B — properly weighted | 106 | no action |
| C — over-weighted weak  | 1 | `rs_line_spy_r_squared_60d` (weak 20-60d but strong 126d/252d — leave) |

**Category A clustering:**

- **252d quality block** (3 features in `s_rs_leadership`) — `gain_to_pain_ratio_252d`
  (OOS IC 60d = +0.048, t = 2.86), `sharpe_rank_252d` (+0.045, t = 2.66),
  `sortino_rank_126d` (+0.033, t = 1.98). Effective weights 0.0038–0.0113.
- **Vol / range cluster** (7 features, no current component home) —
  `realized_vol_60`, `realized_vol_20`, `downside_vol_60d`, `upside_vol_60d`,
  `vol_percentile_21d`, `atr_pct`, `adr_pct_20`. All OOS IC 60d ≈ +0.04
  but **mutually correlated > 0.85** — one signal in seven costumes, not
  seven independent carriers.
- **Singletons:** `pct_from_52w_low` (t = 2.45 @ 60d), `days_near_52w_high_60d`
  (in `s_climax` which carries 0 weight).

**Rebalance test** (one path tried, then reverted). Boost the 252d quality
block within `s_rs_leadership` and trim the over-paid r_squared exposure:

| Sub-block | Phase X.3 | Phase X.4 trial |
|-----------|-----------|------------------|
| primary_rs (`rs_rating_spy`) | 0.30 | 0.20 (cuts overlap with `s_rs`) |
| quality (252d trio + sortino_126d) | 0.15 | 0.25 |
| accel | 0.10 | 0.10 |
| rsl | 0.20 | 0.15 (cuts `rs_line_spy_r_squared_60d` exposure) |
| confluence | 0.15 | 0.15 |
| info_ratio_252d direct | 0.10 | 0.15 |

**Empirical result** — every horizon nudged up, but well under the adoption threshold:

| Horizon | M8 baseline t | Phase X.4 trial t | Δ t |
|---------|---------------|--------------------|------|
| 1d   | +3.86 | +3.93 | +0.07 |
| 5d   | +1.43 | +1.48 | +0.05 |
| 20d  | +1.00 | +1.05 | **+0.05** |
| 60d  | +0.97 | +1.03 | **+0.06** |
| 126d | +2.90 | +2.96 | +0.06 |
| 252d | +2.01 | +2.07 | +0.06 |

Adoption rule was "20d t-stat ≥ +0.5 lift, 20-60d ≥ +0.3 lift, no primary
regression". Achieved: +0.05 / +0.06 at 20d / 60d — well under threshold.
No regressions, but lift insufficient. **Reverted to Phase X.3 M8 production
formula.**

**Practical-limit conclusion.** The single substantive Cat A cluster (252d
quality block) is already inside `s_rs_leadership`; tripling its intra-block
weight delivers ~0.06 t-stat lift, suggesting the 20-60d IC is already near
the ceiling that the current 9-component / 121-feature architecture can
extract without adding a vol-derived component. The vol cluster is a single
correlated signal, not seven, and is already proxied by `s_rs` (high-RS
names are high-vol in this universe). **No further action taken at this
phase.** The 20-60d horizon remains the weakest part of the CCQS signal
surface; raising it materially would require either a new vol-conditioned
component (architectural change, out of scope) or universe expansion.

**Scope constraints honoured.** No new features added. No multi-horizon
variants, no cross-sectional neutralization, no regime conditioning, no
ML — all inappropriate for the user's discretionary thematic long-biased
trading style.

---

### Phase X.3 — Component cleanup + regularization study (2026-05-22)

Filtered scope: **M8 (component-weight cleanup) adopted**, **M1 (regularized
component weighting) rejected on OOS evidence**. M2 (multi-horizon), M3
(cross-sectional neutralization), M5 (regime conditioning) intentionally
**not pursued** — they encode systematic-factor assumptions inappropriate
for the user's discretionary thematic long-biased trading style (CCQS is a
chart-quality screen, not a market-neutral alpha factor).

**M8 — component weight cleanup (adopted).** Redistribute weight from the
four zero / negative OOS-IC components onto the four proven positive-OOS
carriers, based on the Phase X.2.1 component OOS audit:

| Component | Mean OOS IC | Action |
|-----------|-------------|--------|
| `s_momentum` | +0.0000 | shrink to 0.01 in every state |
| `s_trend_slope` | -0.0001 | shrink to 0.01-0.03 |
| `s_rsl` | -0.0013 | shrink to 0.01-0.03 |
| `s_extension` | -0.0070 | shrink to 0.00-0.02 |
| `s_climax` | -0.0242 | hold at 0.00 (Phase X.2.1) |
| `s_structure` | +0.0185 | boost to 0.16-0.22 |
| `s_mtf` | +0.0154 | boost to 0.14-0.15 |
| `s_rs` | +0.0272 | boost to 0.20-0.25 |
| `s_rs_leadership` | +0.0266 | boost to 0.22-0.28 |

Cumulative weight on zero-contribution components: 29% (Phase X.2.1) → 8-10%
(Phase X.3 M8). State-conditional rows in §7 reflect the new matrix; every
row sums to 1.00.

**M8 — empirical effect.** All six OOS horizons improved in both mean IC and
t-stat versus Phase X.2.1; baseline OOS IC @ 126d rose to +0.0478 (t = 2.90)
and @ 1d to +0.0163 (t = 3.86).

**M1 — regularized component weighting (rejected).** Built
`compute/validation/regularized_weighting.py`: RidgeCV (α ∈ {0.01, 0.1, 1,
10, 100}) over rolling 252-day train / 21-day test windows (48 total), fit
against forward-126d cross-sectional return z-scores, with sum-to-one
normalization of the 10 component weights and OOS Spearman IC at six
horizons. Decision rule: adopt iff ≥+10% OOS IC at *both* 1d and 126d *and*
no component shows std/|mean| > 4 *and* reg t-stat at 126d ≥ M8 baseline.

Result — **every criterion failed**:

| Horizon | M8 baseline IC | Regularized IC | Δ % | reg t-stat |
|---------|----------------|----------------|------|-------------|
| 1d   | +0.0163 | +0.0031 | **-81.2%**  | +0.78 |
| 5d   | +0.0150 | +0.0083 | -44.8%      | +0.91 |
| 20d  | +0.0186 | +0.0081 | -56.6%      | +0.59 |
| 60d  | +0.0179 | **-0.0118** | -166.0% | -0.81 |
| 126d | +0.0478 | **-0.0091** | -119.1% | -0.70 |
| 252d | +0.0387 | +0.0008 | -97.8%      | +0.06 |

All 10 components had std/|mean| > 4 across windows (s_rs std 84 on mean 10;
s_mtf std 73 on mean -9; multiple sign-flips per ticker). Root cause: the
10 components are strongly cross-correlated, so ridge picks one regime's
solution and re-picks differently the next window. The sum-to-one
renormalization amplified noise when the unconstrained ridge coefficients
summed close to zero. The hand-set matrix encodes a stable cross-state
prior that data-driven fitting cannot match on this universe / window size.

**Decision:** Production retains the Phase X.3 M8 hand-set matrix.
Regularized-weights output remains in `data/cache/regularized_weights*` for
diagnostic reference only.

---

### Phase X.2.1 — OOS-driven configuration patch (2026-05-22)

Five empirical fixes applied after the Phase X.2 feature-level OOS audit
(`compute/validation/feature_audit.py` consuming `oos_ic_diagnostics.parquet`,
6 horizons × 131 scores × 48 rolling windows). Each fix is grounded in an
audit finding cited inline:

| # | Fix | Driver |
|---|-----|--------|
| 1 | **Sign-flip `hh_count_60d`** in S_STRUCTURE | mean OOS IC = -0.0335 (t = -9.0 @ 5d) — wrong-direction signal |
| 2 | **Zero `S_CLIMAX` weight** in every state, redistribute to S_RS / S_RS_LEADERSHIP | mean OOS IC = -0.0242, significantly negative at 2 horizons |
| 3 | **Restore 252d quality features** in S_RS_LEADERSHIP Tier 2 (sharpe_rank_252d / gain_to_pain_ratio_252d / information_ratio_252d) | top-3 OOS contributors at *every* horizon |
| 4 | **Boost `hl_count_60d` weight** in S_STRUCTURE (0.08 → 0.25) | OOS IC = +0.049 (t = +14.1 @ 1d) — strongest single feature |
| 5 | **Remove `new_20d_high`** | max \|OOS IC\| < 0.005 across all 6 horizons — pure noise |

Feature count: 122 → **121**.

---

## RS Rating Methodology

The `rs_rating_spy` feature shown in the dashboard ("RS rating vs SPY") is the
**cross-sectional percentile rank, within the CCQS universe, of a weighted
multi-horizon RS-Line slope vs. SPY**. The lock holds as of 2026-05-23; this
section documents the existing methodology, not a change.

### Exact computation (per `compute/features.py:721–728`)

For each date `t` and each ticker, define the SPY-relative RS Line:

    rs_line_spy(t) = close(t) / SPY_close(t),  rebased so rs_line_spy(t₀) = 100

Compute the relative-return ("slope") at four quarterly lookbacks:

    slope_63  = (rs_line(t) / rs_line(t − 63d)  − 1) × 100
    slope_126 = (rs_line(t) / rs_line(t − 126d) − 1) × 100
    slope_189 = (rs_line(t) / rs_line(t − 189d) − 1) × 100
    slope_252 = (rs_line(t) / rs_line(t − 252d) − 1) × 100

Weighted composite, with the most recent quarter overweighted 2×:

    rs_composite = 0.40 × slope_63 + 0.20 × slope_126
                 + 0.20 × slope_189 + 0.20 × slope_252

Cross-sectional rank within the CCQS universe at date `t`, mapped to `[1, 99]`:

    rank_pct(t)    = rs_composite(t).rank(pct=True)          # per-date, across tickers
    rs_rating_spy  = clip(rank_pct × 98 + 1, 1, 99)

### Properties

| Aspect          | Value |
|-----------------|-------|
| Lookbacks       | 63, 126, 189, 252 trading days (~Q1–Q4) |
| Weights         | 0.40 / 0.20 / 0.20 / 0.20 (newest quarter 2×) |
| Slope target    | RS Line (stock/SPY ratio), not raw returns |
| Universe        | CCQS universe at date `t` (currently 858 names) |
| Range           | `[1, 99]` continuous percentile |
| Warm-up         | 252 trading days; earlier rows are NaN |
| Interpretation  | 50 = median, 80 = top quintile, 99 = top ~1% within CCQS universe |

### Spot-check (NVDA, 2026-05-22)

| Step                | Value |
|---------------------|-------|
| slope_63            | +2.88% |
| slope_126           | +2.59% |
| slope_189           | +4.89% |
| slope_252           | +27.71% |
| rs_composite        | 0.40·2.88 + 0.20·2.59 + 0.20·4.89 + 0.20·27.71 = **+8.19** |
| Universe size       | 858 |
| Rank percentile     | 0.7016 |
| `rs_rating_spy`     | clip(0.7016 × 98 + 1) = **69.76** |
| `features.parquet`  | **69.71** (Δ ≈ 0.05, rank-tie precision) |

### Difference from IBD-style RS Rating

IBD-style RS Rating (TradingView, MarketSmith, etc.) uses the same four
quarterly lookbacks and the same 0.4 / 0.2 / 0.2 / 0.2 weights, but differs in
two material ways:

| | IBD-style | CCQS `rs_rating_spy` |
|--|-----------|----------------------|
| **Composite target** | weighted ratio of stock returns to SPY returns: `(Σ wᵢ · rᵢ_stock) / (Σ wᵢ · rᵢ_SPY) × 100` | weighted slope of the **RS Line itself** (stock/SPY ratio): `Σ wᵢ · ((rs_line_t / rs_line_{t-i}) − 1)` |
| **Ranking universe** | full US-listed market (~6,000 stocks) | CCQS curated universe (currently 858 names) |
| **Output mapping**   | rank → percentile 1–99 | rank → percentile 1–99 (same shape) |

The two are conceptually similar — both measure quarterly momentum relative
to SPY, weighted to the newest quarter — but they are not numerically
identical. The same stock will typically have **different** values in each
system. Both are mathematically valid; they measure different things.

CCQS chooses **universe-relative** because the L/S workflow is to select
**within** a curated thematic universe. Ranking against ~6,000 US-listed
stocks would penalize names in the CCQS universe relative to large-cap mega-
caps outside it, distorting the within-basket and within-theme comparisons
that drive the workflow. A 70 RS in CCQS means "stronger than 70% of the
investable CCQS universe today"; a 70 RS in IBD means "stronger than 70% of
all US-listed equities". Both signals are useful — they answer different
questions.

This methodology is **locked**. Pattern observation in historical RS
distributions is not a valid motivation for change (Methodology Lock
principle 4).

---

## Table Of Contents

1. [Project Overview](#1-project-overview)
2. [Constraints & Scope](#2-constraints--scope)
3. [Universe](#3-universe)
4. [Data Layer](#4-data-layer)
5. [Feature Engineering — 104 Features](#5-feature-engineering--104-features)
6. [Cross-Sectional Standardization](#6-cross-sectional-standardization)
7. [Component Scoring — 9 Components](#7-component-scoring--9-components)
8. [State Classification — 6 States](#8-state-classification--6-states)
9. [Composite Scoring & Grading](#9-composite-scoring--grading)
10. [Setup Categories — 24 Setups](#10-setup-categories--24-setups)
11. [Leadership & Theme Classification](#11-leadership--theme-classification)
12. [Aggregation Layer — Theme Strength](#12-aggregation-layer--theme-strength)
13. [Reliability Architecture — 8 Layers](#13-reliability-architecture--8-layers)
14. [Output Layer — Dashboard Views](#14-output-layer--dashboard-views)
15. [File Structure](#15-file-structure)
16. [Build Phases](#16-build-phases)

---

## 1. Project Overview

### Purpose

Daily technical screening system for 910 stocks/ETFs across 275 baskets. Identifies:

- Trending leaders (RS-confirmed, multi-timeframe)
- Buyable pullbacks (Tier S setups)
- Pre-breakout coils (VCP, BB squeeze)
- Climactic exhaustion (short candidates)
- Broken downtrends (avoid / short)
- Early-stage multibaggers (RS ramping in strong themes)

### Output

For each ticker:
- **CCQS score** (0-100)
- **Grade** (S / A / B / C / D)
- **State** (TRENDING / PULLBACK / CONSOLIDATING / EXHAUSTION / DETERIORATING / INDETERMINATE) with confidence
- **Setup category** (24 named labels)
- **Leadership tier** (7 levels — Path 1.5)
- **Cross-sectional RS vs SPY** + QQQ RS Line context

For each basket:
- **Theme CCQS** (0-100)
- **Theme classification** (7 tiers: ELITE / STRONG / EMERGING / etc.)
- **Breadth metrics**
- **Theme RS Line dynamics**

### Use Case

- **User:** ADFM L/S discretionary equity analyst
- **Workflow:** Macro models say risk-on → use CCQS to find best equity setups
- **Time horizons:** 1 day to several weeks to months
- **Tool role:** Screening + ranking; user judgment overlays
- **NOT:** Predictive signal generator, position sizer, or systematic execution

---

## 2. Constraints & Scope

### Strict Constraints

| Constraint | Detail |
|------------|--------|
| Data | Daily OHLCV only (yfinance primary, Stooq backup for verification) |
| Scope | Pure technical and momentum/strength analysis |
| Timeframes | Daily primary; weekly + monthly confluence |
| Universe | 910 unique tickers (expandable to mid/small caps later) |
| No macro/regime detection | User has separate models for that |
| No fundamentals | No earnings, no estimates, no revisions |
| No positioning data | No short interest, no insider, no options flow |
| No sentiment | No AAII, NAAIM, put/call ratios |

### What's Explicitly Excluded

- Earnings dates, short interest, market cap, beta (these belong to other models)
- Sector ETF flows, sentiment indicators
- Options data (IV, skew, gamma)
- Insider transactions, news/social NLP
- Single-bar candle patterns (noise on dailies)
- Stochastic, Williams %R, MFI (redundant with RSI)
- Mass Index, Choppiness Index (redundant with ADX+R²)
- ROC acceleration (second derivative, noisy)

---

## 3. Universe

### Universe File

The canonical universe lives in `data/universe.py`. **DO NOT REGENERATE OR MODIFY THIS FILE.**

### Universe Stats

- **879 unique tickers** (post Phase 5.2: removed CTRA, TRUL.CN, EUROB.AT)
- **858 stocks** survive the data-quality firewall and are CCQS-scored
- **SPY, QQQ** are kept as benchmarks only (RS denominator + chart overlays) and
  are NOT in the scored panel — their OHLCV is persisted separately at
  `data/cache/benchmarks.parquet`
- **275 baskets** across **9 categories**
  - **180 CORE baskets** (sector/industry primary classifications)
  - **60 TAG baskets** (thematic cross-sector overlays)
  - **35 COUNTRY baskets** (country ETF tier)
- **219 populated baskets**, **152 healthy** (≥3 primary tickers)
- **734 manual business-descriptor overrides** already applied

### Removed Tickers (Phase 5.2)

| Ticker | Reason for removal |
|--------|--------------------|
| `CTRA` | Insufficient post-merger history (Cabot/Cimarex 2021); cannot be scored cleanly |
| `TRUL.CN` | Canadian exchange listing with sparse OHLCV; cannot be scored cleanly |
| `EUROB.AT` | Greek ATHEX listing; data limitations prevent stable cross-sectional features |

The previous workaround (KNOWN_BENCHMARKS / INSUFFICIENT_HISTORY_EXCEPTIONS in
the Level-3 validator) is removed — the scored panel has zero hardcoded
exceptions.

### Universe Tiers (For Scoring Behavior)

| Tier | Description | Scoring Treatment |
|------|-------------|-------------------|
| Tier 1 | Stocks in populated CORE baskets | Full CCQS + within-basket ranking |
| Tier 2 | Country ETFs | CCQS + separate "Country ETF Ranking" view |
| Tier 3 | Tag-basket-only stocks | CCQS but no within-basket ranking |
| Tier 4 | Benchmarks (SPY, QQQ) | Used for RS computation and chart overlays; EXCLUDED from CCQS scoring |

### Helper Functions (Provided In universe.py)

```python
from data.universe import (
    all_unique_tickers,       # List of 879 scored-panel tickers (post Phase 5.2)
    primary_basket,           # ticker -> primary basket name
    tags_for,                 # ticker -> list of tag baskets
    constituents,             # basket -> list of primary tickers
    tickers_tagged,           # basket -> all tickers (primary + tags)
    baskets_by_type,          # "CORE" / "TAG" / "COUNTRY" -> list of baskets
    category_of,              # basket -> category
    basket_type,              # basket -> "CORE" / "TAG" / "COUNTRY"
    BENCHMARKS,               # {"SPY", "QQQ"} — set; carved out of scoring panel
)
```

---

## 4. Data Layer

### Data Source

**Primary:** yfinance (Python library, free, no API key)
- Daily OHLCV: open, high, low, close, adj_close, volume
- 5-year lookback (1,260 trading days)
- Batch download, ~60-120 seconds for 910 tickers
- Use `auto_adjust=False` to get both `close` and `adj_close`

**Backup verification:** Stooq (via pandas-datareader)
- Used weekly to cross-check persistent yfinance errors
- NOT used in daily scoring pipeline

### Benchmark Tickers

Pull these two alongside the universe (Path 1.5 — single-benchmark RS):

```python
BENCHMARK_TICKERS = ['SPY', 'QQQ']
```

- **SPY**: S&P 500 ETF — primary cross-sectional RS benchmark
- **QQQ**: Nasdaq 100 ETF — context-only RS Line (not cross-sectionally ranked)

> **SUPERSEDED:** IWM (Russell 2000) was previously pulled as a third
> benchmark. Removed in Path 1.5 because SPY-QQQ-IWM slope-composite
> cross-sectional ranks were ~Pearson 1.0000 (per-horizon ranks are
> benchmark-invariant under additive constants; only the weighted
> composite re-shuffles, and highly-correlated benchmarks barely
> re-shuffle). See SPEC §5 Category 8 for full reasoning.

### Caching Strategy

```
data/cache/
├── ohlcv_daily.parquet         # All tickers OHLCV (parquet, ~80-100 MB)
├── ohlcv_meta.json             # Pull timestamp, ticker counts, date range
├── failed_tickers.json         # Tickers that failed fetch
└── data_quality_report.json    # Output of quality firewall
```

- TTL: 3 hours during market hours
- TTL: 18 hours after market close
- Last-good fallback: if today's pull fails entirely, use last good cache

### Daily Snapshot Archive

Every successful refresh saves a complete snapshot:

```
data/snapshots/YYYY-MM-DD/
├── ohlcv.parquet
├── features.parquet
├── z_scores.parquet
├── components.parquet
├── states.parquet
├── scores.parquet
├── theme_aggregates.parquet
└── metadata.json
```

Enables time-travel, audit, and diff comparisons.

---

## 5. Feature Engineering — 104 Features

All features computed from daily OHLCV. Vectorized across full universe in single pass.

### Smoothing Conventions (TradingView-Aligned)

| Smoothing | Formula | Used For |
|-----------|---------|----------|
| Simple Moving Average (SMA) | `mean(x[-n:])` | SMA features |
| Exponential Moving Average (EMA) | `α = 2/(n+1)` | EMA features, MACD |
| Wilder's RMA (Running Moving Average) | `α = 1/n`, first value = SMA | ATR, ADX, RSI, +DI, -DI |

Wilder's RMA Python implementation:

```python
def wilder_rma(series, period):
    rma = pd.Series(index=series.index, dtype=float)
    rma.iloc[period-1] = series.iloc[:period].mean()
    for i in range(period, len(series)):
        rma.iloc[i] = (rma.iloc[i-1] * (period - 1) + series.iloc[i]) / period
    return rma
```

### Category 1: Price-Based (9 features)

| # | Feature | Definition |
|:-:|---------|------------|
| 1 | `close` | Daily close (adj for splits/divs) |
| 2 | `open` | Daily open |
| 3 | `high` | Daily high |
| 4 | `low` | Daily low |
| 5 | `sma_50` | 50-day SMA |
| 6 | `sma_200` | 200-day SMA |
| 7 | `ema_8` | 8-day EMA |
| 8 | `ema_21` | 21-day EMA |
| 9 | `ema_50` | 50-day EMA |

### Category 2: Volatility & Range (5 features)

| # | Feature | Definition |
|:-:|---------|------------|
| 10 | `atr_14` | Wilder RMA of True Range, 14 periods |
| 11 | `atr_pct` | atr_14 / close * 100 |
| 12 | `adr_pct_20` | mean(log(high/low) over 20 days) * 100 |
| 13 | `realized_vol_20` | std(daily_returns[-20:]) * sqrt(252) * 100 |
| 14 | `realized_vol_60` | std(daily_returns[-60:]) * sqrt(252) * 100 |

True Range: `TR_t = max(high - low, |high - close_prev|, |low - close_prev|)`

### Category 3: Position & Extension (5 features)

| # | Feature | Definition |
|:-:|---------|------------|
| 15 | `pct_ma_50` | (close - sma_50) / sma_50 * 100 |
| 16 | `pct_ma_200` | (close - sma_200) / sma_200 * 100 |
| 17 | `atr_x_50` | (close - sma_50) / atr_14 |
| 18 | `atr_x_200` | (close - sma_200) / atr_14 |
| 19 | `vol_normalized_extension` | atr_x_50 / max(adr_pct_20, 1.0) |

### Category 4: Trend Slope & Regression (5 features)

Linear regression of `log(close)` on `range(60)` over last 60 days:

| # | Feature | Definition |
|:-:|---------|------------|
| 20 | `trend_slope_60d` | OLS slope, annualized: (exp(slope * 252) - 1) * 100 |
| 21 | `trend_r_squared_60d` | R² of regression |
| 22 | `trend_slope_t_stat` | slope / standard_error |
| 23 | `trend_slope_significant` | Binary: abs(t_stat) > 1.96 |
| 24 | `price_z_score_vs_trend` | (actual_log_price - predicted_log_price) / residual_std |

### Category 5: Trend Strength (4 features)

| # | Feature | Definition |
|:-:|---------|------------|
| 25 | `adx_14` | Wilder RMA of DX, 14 periods |
| 26 | `plus_di` | 100 * wilder_rma(+DM, 14) / atr_14 |
| 27 | `minus_di` | 100 * wilder_rma(-DM, 14) / atr_14 |
| 28 | `adx_trend_direction` | +1 if plus_di > minus_di else -1 |

### Category 6: Supertrend (2 features)

ATR-based trend indicator with 3.0x multiplier, 10-period ATR:

| # | Feature | Definition |
|:-:|---------|------------|
| 29 | `supertrend_direction` | +1 (bull) or -1 (bear) |
| 30 | `supertrend_days_since_flip` | Days since last direction change |

### Category 7: Volume (7 features)

| # | Feature | Definition |
|:-:|---------|------------|
| 31 | `volume` | Daily volume |
| 32 | `volume_z_20_252` | (mean(vol[-20:]) - mean(vol[-252:])) / std(vol[-252:]) |
| 33 | `up_down_vol_ratio_50` | sum(vol up days [-50:]) / sum(vol down days [-50:]) |
| 34 | `distribution_days_25` | Count of days where close < close_prev*0.998 AND vol > vol_prev (last 25) |
| 35 | `ad_line_slope_20` | 20-day slope of Accumulation/Distribution Line |
| 36 | `cmf_21` | Chaikin Money Flow, 21-day |
| 37 | `capitulation_volume_flag` | Binary: vol > 3x 50d avg AND drop > 2% AND in bottom 20% of 50d range |

A/D Line: `CLV = ((close - low) - (high - close)) / (high - low); AD_t = AD_{t-1} + CLV * volume`

CMF: `sum(CLV * vol, 21) / sum(vol, 21)`

### Category 8: Relative Strength — Single-Benchmark vs SPY (4 features)

**Path 1.5:** Cross-sectional RS rating is computed *only against SPY*. QQQ
appears as a context-only RS Line in Category 9 (raw line + slope +
new-high flags) but is not cross-sectionally percentile-ranked. IWM was
dropped entirely.

RS-Line slope composite (multiplicative formulation, vs SPY):
```
rs_line_spy(t) = stock_close(t) / spy_close(t)        # normalized to 100 at series start

rs_slope_63d_spy  = (rs_line_spy[t] / rs_line_spy[t-63]  - 1) * 100   # 3-month
rs_slope_126d_spy = (rs_line_spy[t] / rs_line_spy[t-126] - 1) * 100   # 6-month
rs_slope_189d_spy = (rs_line_spy[t] / rs_line_spy[t-189] - 1) * 100   # 9-month
rs_slope_252d_spy = (rs_line_spy[t] / rs_line_spy[t-252] - 1) * 100   # 12-month

rs_composite_spy = 0.40*rs_slope_63d_spy + 0.20*rs_slope_126d_spy
                 + 0.20*rs_slope_189d_spy + 0.20*rs_slope_252d_spy

# Cross-sectional continuous percentile rank across universe, clipped to [1, 99]:
rs_rating_spy = (rank_pct(rs_composite_spy) * 98 + 1).clip(1, 99)
```

> **SUPERSEDED A — additive excess returns (do not use):** an earlier draft
> used `rel_nm = return_stock_nm - return_bench_nm` and percentile-ranked
> the resulting composite per benchmark. Subtracting a per-date benchmark
> constant from every ticker is rank-invariant, so `rs_rating_spy`,
> `rs_rating_qqq`, `rs_rating_iwm` collapsed to identical values for every
> stock.
>
> **SUPERSEDED B — multi-benchmark slope composite ranked per benchmark
> (do not use):** the multiplicative slope formula above, applied
> independently to SPY/QQQ/IWM and cross-sectionally ranked per benchmark.
> Per-horizon ranks of `(1+r_T_n)/(1+r_B_n) − 1` are still
> benchmark-invariant (dividing all stocks by the same constant
> `(1+r_B_n)` doesn't reorder them); only the weighted blend of horizons
> reshuffles. Empirically the SPY/QQQ rating pair had Pearson ~1.0000
> (mean |Δ| ≈ 0.07 pts) because SPY-QQQ horizon return profiles co-move
> tightly. We considered beta-residualizing per benchmark but the added
> complexity didn't serve the discretionary workflow, so Path 1.5 collapses
> to single-benchmark cross-sectional RS vs SPY with QQQ retained only as
> a contextual RS Line.

| # | Feature | Definition |
|:-:|---------|------------|
| 38 | `rs_rating_spy` | Cross-sectional RS Rating vs SPY, continuous [1, 99] |
| 39 | `sharpe_momentum_rank_126d` | Cross-sectional rank of (mean_return_126d / vol_126d) |
| 40 | `sortino_rank_126d` | Cross-sectional rank using downside vol only |
| 41 | `within_basket_z_21d` | Z-score of 21d return vs same-basket peers |

### Category 9: RS Line & Acceleration (13 features)

SPY RS Line is the primary; QQQ RS Line features are **context-only** (raw,
not cross-sectionally ranked) — they support visual peer-context and
leadership confirmation gating, not scoring weight.

RS Line = close / benchmark_close, normalized to base 100.

| # | Feature | Definition |
|:-:|---------|------------|
| 42 | `rs_line_spy_value` | RS Line vs SPY |
| 43 | `rs_line_qqq_value` | RS Line vs QQQ (context-only) |
| 44 | `rs_line_spy_new_high_60d` | Binary: SPY RS Line at 60d high |
| 45 | `rs_line_spy_new_high_252d` | Binary: SPY RS Line at 252d high |
| 46 | `rs_line_spy_slope_20d` | 20-day slope of SPY RS Line (%) |
| 47 | `rs_line_spy_slope_60d` | 60-day slope of SPY RS Line (%) |
| 48 | `rs_line_spy_r_squared_60d` | R² of SPY RS Line trend |
| 49 | `rs_line_qqq_new_high_60d` | Binary: QQQ RS Line at 60d high (context-only) |
| 50 | `rs_line_qqq_new_high_252d` | Binary: QQQ RS Line at 252d high (context-only) |
| 51 | `rs_line_qqq_slope_20d` | 20-day slope of QQQ RS Line (%) (context-only) |
| 52 | `rs_line_qqq_slope_60d` | 60-day slope of QQQ RS Line (%) (context-only) |
| 53 | `rs_rating_slope_60d` | rs_rating_spy[-1] - rs_rating_spy[-60] (acceleration) |
| 54 | `rs_rating_slope_120d` | rs_rating_spy[-1] - rs_rating_spy[-120] |

> **SUPERSEDED:** `rs_line_iwm_value` and `rs_line_iwm_new_high_252d`
> removed in Path 1.5 (IWM no longer fetched).

### Category 10: Structure & Pivots (9 features)

| # | Feature | Definition |
|:-:|---------|------------|
| 58 | `sma_stack_score` | 0-100: composite of (close > sma_50), (close > sma_200), (sma_50 > sma_200), bonus if all aligned |
| 59 | `ema_stack_score` | 0-100: composite of (close > ema_8 > ema_21 > ema_50) alignment |
| 60 | `hh_count_60d` | Count of higher pivot highs in last 60d (max 3) |
| 61 | `hl_count_60d` | Count of higher pivot lows in last 60d (max 3) |
| 62 | `trend_integrity` | Binary: hh_count >= 2 AND hl_count >= 2 |
| 63 | `new_252d_high` | Binary: close >= max(high[-253:-1]) |
| 64 | `pct_up_days_21` | (returns[-21:] > 0).mean() |
| 65 | `failed_breakout_flag_10d` | Binary: broke 20d high in last 10d but currently below that prior high |

> Phase X.2.1 — `new_20d_high` removed. The OOS feature audit (2026-05) showed
> max |OOS IC| < 0.005 across all six forward horizons. It was the only
> feature in the entire 122-set that qualified as pure noise.

Pivot detection: 5-bar lookback (high at index i is a pivot if it equals max(high[i-5:i+6])).

### Category 11: Multi-Timeframe — Weekly (6 features)

Weekly resampling: `daily.resample('W-FRI').agg({'open':'first', 'high':'max', 'low':'min', 'close':'last', 'volume':'sum'})`

| # | Feature | Definition |
|:-:|---------|------------|
| 67 | `weekly_stack_alignment` | Binary: weekly_close > EMA10w > SMA30w > SMA40w |
| 68 | `weekly_higher_highs` | Binary: max(weekly_high[-8:]) > max(weekly_high[-16:-8]) |
| 69 | `weekly_rs_rising` | Binary: weekly RS Line > 5 weeks ago |
| 70 | `weekly_rsi_14` | RSI(14) on weekly bars |
| 71 | `weekly_macd_posture` | MACD posture on weekly bars (Positive/Negative) |
| 72 | `weekly_trend_slope_sign` | Sign of 26-week regression slope |

### Category 12: Multi-Timeframe — Monthly (2 features)

Monthly resampling: `daily.resample('ME').last()`

| # | Feature | Definition |
|:-:|---------|------------|
| 73 | `monthly_close_above_sma_10` | Binary: monthly close > 10-month SMA |
| 74 | `monthly_higher_highs_3m` | Binary: monthly high[-3:] strictly increasing |

### Category 13: MTF Coherence (1 feature)

| # | Feature | Definition |
|:-:|---------|------------|
| 75 | `mtf_rs_coherence` | Score 0-3: count of (daily RS rising, weekly RS rising, monthly RS rising) |

### Category 14: Momentum Oscillators (7 features)

| # | Feature | Definition |
|:-:|---------|------------|
| 76 | `rsi_14` | RSI(14) with Wilder smoothing |
| 77 | `macd_line` | EMA12 - EMA26 |
| 78 | `macd_signal` | EMA9 of macd_line |
| 79 | `macd_histogram` | macd_line - macd_signal |
| 80 | `macd_posture` | 3-tuple: (Positive/Negative, Accelerating/Decelerating, Strong/Weak) |
| 81 | `bullish_divergence_20d` | Binary: price LL in last 20d, RSI HL in same window |
| 82 | `bearish_divergence_20d` | Binary: price HH in last 20d, RSI LH in same window |

MACD posture logic:
```python
sign = 'Positive' if macd_line > 0 else 'Negative'

direction_recent = macd_histogram[-1] - macd_histogram[-2]
if sign == 'Positive':
    direction = 'Accelerating' if direction_recent > 0 else 'Decelerating'
else:
    direction = 'Accelerating' if direction_recent < 0 else 'Decelerating'

strength_threshold = mean(abs(macd_histogram[-50:])) * 1.5
strength = 'Strong' if abs(macd_histogram[-1]) > strength_threshold else 'Weak'
```

### Category 15: Pattern Setup (6 features)

| # | Feature | Definition |
|:-:|---------|------------|
| 83 | `bb_upper_20` | sma_20 + 2 * std_20 |
| 84 | `bb_lower_20` | sma_20 - 2 * std_20 |
| 85 | `bb_width_pct_252d` | Percentile of current (bb_upper - bb_lower)/sma_20 in 252d range |
| 86 | `bb_squeeze_flag` | Binary: BB inside Keltner Channels (KC = EMA20 ± 1.5*ATR10) |
| 87 | `vcp_quality_score` | 0-100: sequential contraction (Minervini VCP detection) |
| 88 | `base_duration_days` | Count of days in last 252 where close < (rolling 252d high * 0.90) |

VCP detection: identify last 3 peaks (10-bar lookback); for each peak-to-peak segment, measure depth and volume-drying; score by (monotonically contracting AND volume drying).

### Category 16: Climax & Time-at-Top (3 features)

| # | Feature | Definition |
|:-:|---------|------------|
| 89 | `days_near_52w_high_60d` | Count of days where close >= 0.97 * 252d rolling high (last 60d) |
| 90 | `consecutive_high_intensity` | Sum over last 5d of (close within 3% of 52w high) |
| 91 | `climax_volume_flag` | Binary: vol > 4x 50d avg AND up day > 5% AND in top 20% of 50d range |

### Category 17: Within-Basket Leadership (4 features)

| # | Feature | Definition |
|:-:|---------|------------|
| 92 | `within_basket_z_63d` | Z-score of 63d return vs same-basket peers |
| 93 | `within_basket_z_126d` | Z-score of 126d return vs same-basket peers |
| 94 | `within_basket_rank` | 1-N rank within primary basket (1 = best) |
| 95 | `within_basket_rank_pct` | within_basket_rank / basket_size |

### Category 18: Volume Leadership Confirmation (1 feature)

| # | Feature | Definition |
|:-:|---------|------------|
| 96 | `volume_leadership_confirmed` | Binary: ud_vol_ratio_50 >= 1.5 AND ad_line_slope_60d > 0.05 AND distribution_days_25 <= 3 |

### Category 19: REMOVED (Path 1.5)

> **SUPERSEDED:** `multi_bench_leadership_class` (the 9-class
> UNIVERSAL/GROWTH/BROAD/TECH/DEFENSIVE/RISK_ON/UNUSUAL/MIXED/LAGGARD
> categorical) has been removed. It depended on three benchmark RS ratings
> that collapse to near-identical values under the slope-composite formula
> (see Cat 8 superseded notes). The 7-tier leadership classification in
> §11 is now keyed off `rs_rating_spy`, `mtf_rs_coherence`, and the QQQ
> RS Line direction as a context confirmation gate.

### Additional Computed Features (11)

These are computed in the pipeline for use in components:

| # | Feature | Definition |
|:-:|---------|------------|
| 98 | `pct_above_sma_50` | Binary: close > sma_50 |
| 99 | `pct_above_sma_200` | Binary: close > sma_200 |
| 100 | `weekly_rs_new_high_26w` | Binary: weekly RS Line at 26-week high |
| 101 | `monthly_rs_rising_3m` | Binary: monthly RS Line > 3 months ago |
| 102 | `monthly_rs_rising_6m` | Binary: monthly RS Line > 6 months ago |
| 103 | `pct_from_52w_high` | (close / max(high[-252:]) - 1) * 100 |
| 104 | `pct_from_52w_low` | (close / min(low[-252:]) - 1) * 100 |

> Path C removed 4 low-value features formerly numbered 103-106:
> `recent_5d_returns_consistency`, `golden_cross_60d`, `death_cross_60d`,
> `recent_volume_surge_5d`. Three further candidates
> (`bullish_divergence_20d`, `bearish_divergence_20d`,
> `capitulation_volume_flag`) were initially flagged for removal but
> **retained** because they are load-bearing in the s_momentum component
> ([components.py:313-314](compute/components.py)) and in three setup labels
> ("Exhaustion w/ Bearish Divergence", "Capitulation Selling",
> "Deteriorating w/ Bullish Divergence" in
> [setup_classifier.py:137,155,161](compute/setup_classifier.py)).

> **Path C reverted (Path D).** The six short-term features once stored in
> Category 20 (`vol_surge_5d_ratio`, `range_position_5d`, `momentum_5d_pct`,
> `consecutive_strong_closes_3d`, `coil_resolution_pending`,
> `volume_climax_short`) and the two state-aware flags
> (`pullback_bounce_setup`, `mean_reversion_setup`) were measured against
> 1d / 5d / 20d forward returns and showed near-zero predictive value
> (IC_1d ≈ −0.007, IC_5d ≈ −0.002, IC_20d ≈ +0.0035). They were removed in
> favour of the medium-long-term quality features below, which target the
> signals not visible to naked-eye chart reading.

### Category 20: Trend Quality (Path D)

Persistence and smoothness signals over medium-long horizons.

| # | Feature | Description |
|:-:|---------|------------|
| 105 | `hurst_exponent_252d` | Single-window R/S Hurst over 252d of log returns. H>0.5 = trending; H<0.5 = mean-reverting |
| 106 | `return_autocorrelation_60d_lag1` | Rolling 60d Pearson correlation between daily returns and their 1-lag |
| 107 | `return_smoothness_60d` | abs(mean_60d_return) / std_60d_return — higher = cleaner trend |
| 108 | `trend_rsquared_252d` | R² of OLS regression of log(close) on time over 252d |

### Category 21: Volatility Quality (Path D)

Asymmetric and sustained-drawdown vol measures.

| # | Feature | Description |
|:-:|---------|------------|
| 109 | `upside_vol_60d` | std of positive daily returns over 60d, ×100 |
| 110 | `downside_vol_60d` | std of negative daily returns over 60d, ×100 |
| 111 | `ulcer_index_60d` | sqrt(mean(drawdown²)) where drawdown is (close / max(close[-60:]) − 1) × 100 |
| 112 | `gain_to_pain_ratio_252d` | sum(positive returns) / abs(sum(negative returns)) over 252d |

### Category 22: Risk-Adjusted Performance (Path D)

Multi-horizon Sharpe ranks, tail ratio, information ratio vs SPY.

| # | Feature | Description |
|:-:|---------|------------|
| 113 | `sharpe_rank_60d` | Cross-sectional percentile of annualized 60d Sharpe |
| 114 | `sharpe_rank_252d` | Cross-sectional percentile of annualized 252d Sharpe |
| 115 | `tail_ratio_252d` | Cross-sectional percentile of (p95 / abs(p5)) of 252d daily returns |
| 116 | `information_ratio_252d` | Mean / std of (stock_return − SPY_return) over 252d, ×√252 |

**Path D rationale.** Chart-readable patterns (short-term volume, range, momentum) are already largely priced in. The 12 features above quantify trend *quality* (persistence, regression cleanness, autocorrelation), risk *asymmetry* (upside vs downside vol, ulcer, gain-to-pain), and risk-adjusted *strength* (multi-horizon Sharpe ranks, tail behaviour, alpha-IR). They feed into the existing components as follows:

- `S_TREND_SLOPE`: hurst (+15%), return_autocorrelation (+15%), trend_rsquared_252d (+10%); ADX cut from 30% → 20%.
- `S_STRUCTURE`: ulcer_index_60d was negated and weighted 13% in Path D. *Phase X.2.1 removed this term* (peak |OOS IC| = 0.016 @ 126d, below the universally-good cluster). `ulcer_index_60d` is still computed as a feature.
- `S_RS_LEADERSHIP`: sharpe_rank_252d, gain_to_pain_ratio_252d, information_ratio_252d are the audit's top-3 OOS contributors. Path E briefly demoted them; *Phase X.2.1 restored them as the entire Tier-2 quality sub-block* (30/30/30/10 with sortino_rank_126d).

`upside_vol_60d`, `downside_vol_60d`, `sharpe_rank_60d`, `tail_ratio_252d` are kept as feature-only columns (no component weight) for analyst views and future model use.

### Category 23: Horizon-Specific (Path E)

Targeted at the 20–60d forward-return horizon, where Path D pipeline showed IC ≈ 0.01 — much weaker than the 126d IC (≈ 0.037). Cat 23 adds 21d momentum + RS-line slope, 60d Sharpe / IR / Sortino, 60d max drawdown, short-horizon AR(1), and a vol-rank — signals that drive medium-term continuation but were not directly represented before.

| # | Feature | Description |
|:-:|---------|------------|
| 117 | `momentum_21d_pct` | Cross-sectional percentile of 21d return |
| 118 | `rs_line_spy_slope_21d` | (rs_line_spy / rs_line_spy[-21] − 1) × 100 |
| 119 | `ad_line_slope_21d` | 21-day OLS slope of cumulative A/D Line |
| 120 | `bb_position_21d` | 21d mean of (close − bb_lower_20) / (bb_upper_20 − bb_lower_20) |
| 121 | `sharpe_ratio_60d` | mean(daily_ret_60d) / std(daily_ret_60d) × √252 (raw, not ranked) |
| 122 | `information_ratio_60d` | mean(stock − SPY return) / std(stock − SPY return) over 60d × √252 |
| 123 | `sortino_ratio_60d` | mean(daily_ret_60d) / std(neg_ret_60d) × √252 |
| 124 | `max_drawdown_pct_60d` | Cross-sectional percentile of min(drawdown_pct) over 60d window |
| 125 | `return_autocorrelation_21d_lag1` | AR(1) coefficient of daily returns over 21d |
| 126 | `vol_percentile_21d` | Cross-sectional percentile of 21d annualized realized vol |

**Path E rationale.** The 20–60d IC gap is where most discretionary-trader edge lives — too long for noise traders, too short for the slow-moving quality features Path D dialled up. Cat 23 components flow into:

- `S_MOMENTUM` (rewritten): 40% `momentum_21d_pct` + 20% `rs_line_spy_slope_21d` + 20% MACD posture z + 10% RSI extremes z + 10% divergence z. The 60/40 split pulls S_MOMENTUM toward 3–12 week price/RS trajectory while preserving the legacy oscillator info.
- `S_RS_LEADERSHIP` (quality sub-block, Path E version): 30% `sharpe_ratio_60d` + 30% `information_ratio_60d` + 20% `sharpe_momentum_rank_126d` + 20% `sortino_rank_126d`. **Phase X.2.1 reverted this** — the 252d versions of the same risk-adjusted family were the top-3 OOS carriers, so the quality block is now 30/30/30/10 across `sharpe_rank_252d` / `gain_to_pain_ratio_252d` / `information_ratio_252d` / `sortino_rank_126d`.

`ad_line_slope_21d`, `bb_position_21d`, `sortino_ratio_60d`, `max_drawdown_pct_60d`, `return_autocorrelation_21d_lag1`, `vol_percentile_21d` are kept feature-only (available to downstream consumers / analyst views) but do not carry component weight in this revision.

### Total: 121 Features (Path 1.5 + Path C + Path D + Path E + Phase X.2.1)

All features per-stock, derivable from daily OHLCV + benchmarks (SPY, QQQ).

> Path 1.5 net change: −7 + 3 = 104.
> Path C (subsequently reverted): +6 then −6.
> Path D net change: +12 quality features = 112.
> Path E net change: +10 horizon-specific features = 122.
> Phase X.2.1 net change: −1 (`new_20d_high` removed as OOS noise) = **121**.

---

## 6. Cross-Sectional Standardization

All features are standardized cross-sectionally using **robust z-scores** (median/MAD), not mean/std.

```python
def robust_z_score(series):
    """Robust z-score using median and MAD."""
    median = np.median(series)
    mad = np.median(np.abs(series - median))
    return (series - median) / (1.4826 * mad + 1e-10)
```

### Why Robust Statistics

- Resistant to outliers
- Stable across regimes (today's "average" stays consistent)
- 1.4826 × MAD ≈ σ for normal distributions

### When To Use Standard vs Robust

| Feature Type | Method |
|--------------|--------|
| RS Ratings (already percentile) | No standardization |
| ADX, RSI (bounded [0, 100]) | Standard z-score around 50 |
| Returns, %MA, ATR× (skewed) | Robust z-score |
| Volume ratios | Log-transform first, then standard z-score |
| Binary features | No standardization (use as-is) |
| R² (bounded [0, 1]) | Logit-transform first |

### Winsorization

Apply 1st/99th percentile winsorization to final CCQS scores to cap
extreme outliers. **Phase 6 (2026-05-25):** winsorization is now applied
**per-date** rather than globally across the long frame. Each row is
clipped against its own date's `p1 / p99` quantiles. The earlier global
clip produced 24,562 exact ties at two literal display values across all
dates; per-date clipping reduces the maximum tie count to 9 rows while
preserving the same grade assignments (grading uses per-date quantiles
independently). See the Phase 6 narrative above for the full rationale
and impact metrics.

---

## 7. Component Scoring — 9 Components

### Component Architecture

Each component is a weighted sum of standardized feature z-scores. Components themselves are in z-score space (then converted to 0-100 for display via normal CDF).

### Default Weights (INDETERMINATE State) — Phase X.2.1, post Phase 6 removal of S_CLIMAX

Post-Phase-7 weights (INDETERMINATE state, the default fallback row):

```
S_RS:               25.0%   # Classical cross-sectional momentum
S_RS_LEADERSHIP:    29.5%   # Multi-benchmark, multi-dim leadership
S_RSL:               3.0%   # RS Line dynamics
S_TREND_SLOPE:       3.0%   # Trend cleanness (ADX + R² + t-stat)
S_STRUCTURE:        20.4%   # MA stacks + HH/HL + Supertrend
S_MTF:              17.0%   # Multi-timeframe confluence
S_EXTENSION:         1.0%   # Vol-normalized extension
S_DEMAND:            0.0%   # Zero-weight diagnostic (Phase 7)
S_MOMENTUM:          1.0%   # MACD + RSI + divergences
                    -----
Total:             100.0%
```

> **Phase X.2.1 — FIX 2.** The OOS feature audit (2026-05) found
> `S_CLIMAX` had mean OOS IC = -0.0242, significantly negative at two
> horizons. The component was harmful to the composite. Phase X.2.1
> zeroed its weight; **Phase 6 (2026-05-25)** removed it from the
> component set entirely. The component dimension dropped from 10 → 9.
> Bit-identical for CCQS output since the weight was already zero; the
> underlying features (`climax_volume_flag`, `days_near_52w_high_60d`,
> `consecutive_high_intensity`) remain available to state classification
> and the setup classifier. The original 8% freed by zeroing was already
> redistributed to `S_RS` (+5%) and `S_RS_LEADERSHIP` (+3%).
>
> **Phase 7 (2026-05-25) — `S_DEMAND` zeroed.** Same pattern as
> `S_CLIMAX`. Priority 2 bootstrap analysis found `S_DEMAND` averaged
> −0.009 OOS IC across 24 (state × horizon) cells with 6 significantly
> negative cells. Setting its weight to 0 and redistributing the freed
> 10–15% per state to the four carriers (`S_RS`, `S_RS_LEADERSHIP`,
> `S_STRUCTURE`, `S_MTF`) improved unconditional walk-forward OOS IC at
> 5d / 60d / 126d (paired t = 2.01 / 2.77 / 2.64). The component is
> still computed and stored — kept available for diagnostics and
> dashboard display — but contributes 0 to CCQS. See the Phase 7
> narrative section for full validation.

### Component Formulas

**S_RS (17%) — Path 1.5:**
```python
S_RS = (
    0.55 * z(rs_rating_spy) +
    0.30 * z(sharpe_momentum_rank_126d) +
    0.15 * z(within_basket_z_21d)
)
```

> **SUPERSEDED:** previously weighted `rs_rating_composite`
> (0.50·SPY + 0.30·QQQ + 0.20·IWM). With Path 1.5 the composite is gone;
> SPY is the only cross-sectional benchmark.

**S_RS_LEADERSHIP (21%) — Path 1.5 single-benchmark composite (Phase X.2.1 quality block restored):**
```python
# Tier 1: Primary RS vs SPY (30%)
primary_rs = z(rs_rating_spy)

# Tier 2: Quality (15%) — Phase X.2.1 FIX 3.
# The OOS audit (2026-05) showed sharpe_rank_252d, gain_to_pain_ratio_252d
# and information_ratio_252d are the top-3 OOS contributors at *every*
# horizon. Path E had demoted them in favour of 60d versions; restoring
# them recovers the strongest signal carriers.
quality = (
    0.30 * z(sharpe_rank_252d) +
    0.30 * z(gain_to_pain_ratio_252d) +
    0.30 * z(information_ratio_252d) +
    0.10 * z(sortino_rank_126d)
)

# Tier 3: Acceleration (10%)
accel = (
    0.50 * z(rs_rating_slope_60d) +
    0.50 * z(rs_rating_slope_120d)
)

# Tier 4: RS Line quality (20%) — SPY primary, QQQ as context confirmation
rsl = (
    0.20 * z(rs_line_spy_new_high_252d) +
    0.15 * z(rs_line_spy_slope_60d) +
    0.50 * z(rs_line_spy_r_squared_60d) +
    0.15 * z(rs_line_qqq_new_high_252d)        # QQQ context confirmation
)

# Tier 5: Confluence (20%)
confluence = (
    0.55 * (mtf_rs_coherence / 3) * 100 +
    0.45 * z(within_basket_z_63d)
)

S_RS_LEADERSHIP = (
    0.35 * primary_rs +
    0.15 * quality +
    0.10 * accel +
    0.20 * rsl +
    0.20 * confluence
)

# Volume gate: if not volume_leadership_confirmed, cap at 70 (in 0-100 space)
if not volume_leadership_confirmed:
    S_RS_LEADERSHIP = min(S_RS_LEADERSHIP, 70)
```

> **SUPERSEDED:** the Tier-1 `multi_bench` blend
> (0.50·SPY + 0.30·QQQ + 0.20·IWM) collapsed in Path 1.5 because
> SPY/QQQ/IWM ranks were near-identical (Pearson ~1.0000). The
> `n_benchmarks_beaten` confluence term and the `rs_line_iwm_new_high_252d`
> RSL term are removed for the same reason. QQQ's RS Line new-high flag is
> kept as a contextual confirmation signal (lower weight).

**S_RSL (8%):**
```python
S_RSL = (
    0.40 * z(rs_line_spy_new_high_252d) +
    0.25 * z(rs_line_spy_new_high_60d) +
    0.20 * z(rs_line_spy_slope_20d) +
    0.15 * z(rs_line_spy_r_squared_60d)
)
```

**S_TREND_SLOPE (10%):**
```python
S_TREND_SLOPE = (
    0.30 * z(adx_14) +
    0.25 * z(trend_r_squared_60d) +
    0.15 * z(trend_slope_60d) +
    0.20 * z(supertrend_direction * supertrend_days_since_flip) +
    0.10 * z(plus_di - minus_di)
)

# Significance gating
if trend_slope_t_stat < 1.96:
    S_TREND_SLOPE *= 0.5  # Half-weight noisy trends
```

**S_STRUCTURE (13%) — Phase X.2.1 rewrite (FIX 1 + FIX 4):**
```python
S_STRUCTURE = (
    0.20 * z(sma_stack_score) +
    0.20 * z(ema_stack_score) +
    0.10 * z(-hh_count_60d) +           # FIX 1: sign-flip; raw IC = -0.0335
    0.25 * z(hl_count_60d) +            # FIX 4: 0.08 → 0.25 (OOS IC=+0.049, t=14.1 @ 1d)
    0.10 * z(supertrend_direction) +
    0.10 * z(new_252d_high) +
    0.05 * z(pct_up_days_21)
)
```

> **FIX 1 (`hh_count_60d` sign-flip).** OOS audit found mean OOS IC = -0.0335
> with t = -9.0 at the 5d horizon — negative at *every* horizon. Higher pivot
> highs in 60d empirically predict *lower* forward returns (likely an
> over-extension / exhaustion proxy). Multiplied by -1 before z-scoring so
> the contribution flows in the correct direction.
>
> **FIX 4 (`hl_count_60d` weight 0.08 → 0.25).** OOS audit found OOS IC = +0.049
> with t = +14.1 at 1d — the strongest single OOS carrier in the entire
> feature set. Was under-weighted at 0.08.
>
> Two terms dropped from the legacy formula:
>
> - `ulcer_index_60d` (was 0.13): peak |OOS IC| = 0.016 @ 126d, well below
>   the universally-good cluster.
> - `failed_breakout_flag_10d` (was 0.05 + state-machine -0.5 penalty):
>   removed from S_STRUCTURE composition; still computed and consumed by
>   the setup classifier.

**S_MTF (11%):**
```python
weekly_score = (
    0.30 * z(weekly_stack_alignment) +
    0.20 * z(weekly_higher_highs) +
    0.20 * z(weekly_rs_rising) +
    0.15 * z(weekly_macd_posture == 'Positive') +
    0.15 * z(weekly_trend_slope_sign > 0)
)

monthly_score = (
    0.50 * z(monthly_close_above_sma_10) +
    0.50 * z(monthly_higher_highs_3m)
)

S_MTF = 0.80 * weekly_score + 0.20 * monthly_score
```

**S_EXTENSION (8%) — Inverted (less extended = better):**
```python
if pct_ma_50 < -10:
    S_EXTENSION = -1.0  # Severely broken
elif pct_ma_50 < -3:
    S_EXTENSION = -0.5  # Below 50MA
else:
    # Above 50MA — vol-normalized scoring
    S_EXTENSION = (
        0.55 * z(-vol_normalized_extension) +
        0.30 * z(-pct_ma_50) +
        0.15 * z(-price_z_score_vs_trend)
    )
```

**~~S_CLIMAX~~ — removed in Phase 6 (2026-05-25).** Carried weight 0% in
every state since Phase X.2.1 (mean OOS IC −0.0242). The math was also
inverted vs the label: `100 − (extension_penalty + time_score +
vol_climax_score)` made "high s_climax" mean *less climactic*,
contributing to the negative IC. Removed from the component set; the
underlying features (`climax_volume_flag`, `days_near_52w_high_60d`,
`consecutive_high_intensity`) remain available to state classification
and the setup classifier.

**S_DEMAND (0% in Phase 7, kept as zero-weight diagnostic):**
```python
S_DEMAND = (
    0.30 * z(np.log(up_down_vol_ratio_50)) +
    0.25 * z(-distribution_days_25) +
    0.20 * z(ad_line_slope_20) +
    0.15 * z(cmf_21) +
    0.10 * z(volume_z_20_252) +
    # capitulation_volume_flag handled in setup classification, not direct scoring
)
```

> **Phase 7 (2026-05-25) — `S_DEMAND` zeroed.** Priority 2 bootstrap
> analysis found `S_DEMAND` averaged −0.009 OOS IC across 24 (state ×
> horizon) cells with 6 cells significantly negative (CONSOLIDATING at
> all four horizons, PULLBACK at 20d/60d, INDETERMINATE at 60d). The
> component is still computed and stored in `components.parquet` for
> diagnostic display, but its weight is set to 0.0 in every state.
> Freed weight (10-15% per state) redistributed proportionally to the
> four carrier components (`S_RS`, `S_RS_LEADERSHIP`, `S_STRUCTURE`,
> `S_MTF`). Validation: walk-forward OOS IC improved at 3 of 4 horizons
> with paired t > 1.96 (5d, 60d, 126d). See Phase 7 narrative for the
> full empirical evidence and the 2020-COVID-regression caveat.

**S_MOMENTUM (3%):**
```python
posture_scores = {
    ('Positive', 'Accelerating', 'Strong'): 100,
    ('Positive', 'Accelerating', 'Weak'): 80,
    ('Positive', 'Decelerating', 'Strong'): 65,
    ('Positive', 'Decelerating', 'Weak'): 50,
    ('Negative', 'Decelerating', 'Weak'): 40,
    ('Negative', 'Decelerating', 'Strong'): 30,
    ('Negative', 'Accelerating', 'Weak'): 20,
    ('Negative', 'Accelerating', 'Strong'): 0,
}
macd_score = posture_scores[macd_posture]

# RSI extremes
if rsi_14 < 30: rsi_score = 80   # oversold = mean-revert opp
elif rsi_14 > 75: rsi_score = 20
else: rsi_score = 50

# Divergence adjustments (additive)
div_adj = 0
if bullish_divergence_20d: div_adj += 15
if bearish_divergence_20d: div_adj -= 15

S_MOMENTUM = 0.70 * macd_score + 0.30 * rsi_score + div_adj
```

---

## 8. State Classification — 6 States

Per-stock state describes the chart's current behavior. State classification is **probabilistic** using softmax over log-likelihoods.

### The 6 States

| State | Description |
|-------|-------------|
| TRENDING | Clean uptrend in progress |
| PULLBACK | Buyable pullback within uptrend |
| CONSOLIDATING | Pre-breakout consolidation |
| EXHAUSTION | Parabolic / late-stage exhaustion |
| DETERIORATING | Structurally damaged downtrend |
| INDETERMINATE | Indeterminate / transitioning |

### Probabilistic Classification

For each state, compute log-likelihood based on how well features match the state's expected profile:

```python
def state_likelihood(features, state):
    # Log-pdf is kernel-only: normal_logpdf(x, μ, σ) = -0.5 * ((x-μ)/σ)^2
    # (the σ-dependent constant is dropped so all states peak at 0 and the
    # INDETERMINATE prior of -2.5 sits on the same scale as the directional states).
    #
    # Calibration note: σ values are *wide enough* that a feature within
    # ±1.5σ of the state's centre still contributes a competitive
    # log-likelihood. Tight σ's caused 96% INDETERMINATE dominance because no
    # directional state matched a real-world chart well enough.
    if state == 'TRENDING':
        return (
            normal_logpdf(features['adx_14'], μ=30, σ=12) +
            normal_logpdf(features['trend_r_squared_60d'], μ=0.65, σ=0.20) +
            indicator_logpdf(features['sma_stack_score'] >= 80, conf=0.85) +
            normal_logpdf(features['pct_ma_50'], μ=10, σ=12)
        )

    elif state == 'PULLBACK':
        return (
            indicator_logpdf(features['sma_stack_score'] >= 75, conf=0.80) +
            normal_logpdf(features['pct_ma_50'], μ=5, σ=5) +
            normal_logpdf(features['atr_x_50'], μ=1.5, σ=1.0) +
            normal_logpdf(features['rsi_14'], μ=45, σ=15)
        )

    elif state == 'CONSOLIDATING':
        return (
            normal_logpdf(features['bb_width_pct_252d'], μ=15, σ=12) +
            normal_logpdf(features['adx_14'], μ=15, σ=8) +
            indicator_logpdf(features['bb_squeeze_flag'], conf=0.60) +
            normal_logpdf(features['vcp_quality_score'], μ=55, σ=25)
        )

    elif state == 'EXHAUSTION':
        return (
            normal_logpdf(features['atr_x_50'], μ=6.0, σ=2.0) +
            normal_logpdf(features['rsi_14'], μ=75, σ=8) +
            normal_logpdf(features['rs_rating_spy'], μ=92, σ=8) +
            indicator_logpdf(features['days_near_52w_high_60d'] >= 25, conf=0.70)
        )

    elif state == 'DETERIORATING':
        return (
            normal_logpdf(features['pct_ma_50'], μ=-12, σ=10) +
            normal_logpdf(features['distribution_days_25'], μ=8, σ=4) +
            indicator_logpdf(features['supertrend_direction'] == -1, conf=0.75) +
            normal_logpdf(features['rs_rating_spy'], μ=25, σ=20)
        )

    elif state == 'INDETERMINATE':
        # Low constant prior: INDETERMINATE only wins when no directional state's
        # likelihood beats -2.5. With the kernel scale, this corresponds to
        # roughly ~√5 standardized deviations of joint mismatch.
        return -2.5

# Softmax for probability distribution
def classify_state_probabilistic(features):
    states = ['TRENDING', 'PULLBACK', 'CONSOLIDATING', 'EXHAUSTION', 'DETERIORATING', 'INDETERMINATE']
    log_likelihoods = {s: state_likelihood(features, s) for s in states}
    
    max_ll = max(log_likelihoods.values())
    exp_ll = {s: np.exp(ll - max_ll) for s, ll in log_likelihoods.items()}
    total = sum(exp_ll.values())
    probs = {s: v/total for s, v in exp_ll.items()}
    
    return {
        'primary_state': max(probs, key=probs.get),
        'confidence': max(probs.values()),
        'probabilities': probs,
    }
```

### State-Conditional Component Weights (Phase 7)

| Component | TRENDING | PULLBACK | CONSOLIDATING | EXHAUSTION | DETERIORATING | INDETERMINATE |
|-----------|:--------:|:--------:|:-------:|:---------:|:------:|:-----:|
| S_RS | 28.0% | 25.6% | 23.8% | 26.1% | 23.8% | 25.0% |
| S_RS_LEADERSHIP | 28.0% | 29.1% | 26.2% | 33.2% | 29.7% | 29.5% |
| S_RSL | 3.0% | 3.0% | 2.0% | 1.0% | 2.0% | 3.0% |
| S_TREND_SLOPE | 3.0% | 2.0% | 2.0% | 1.0% | 2.0% | 3.0% |
| S_STRUCTURE | 20.2% | 21.0% | 26.2% | 19.0% | 23.8% | 20.4% |
| S_MTF | 16.8% | 16.3% | 17.8% | 17.8% | 17.8% | 17.0% |
| S_EXTENSION | 0.0% | 2.0% | 1.0% | 1.0% | 0.0% | 1.0% |
| S_DEMAND | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| S_MOMENTUM | 1.0% | 1.0% | 1.0% | 1.0% | 1.0% | 1.0% |

(Pre-Phase-7 values for reference: S_RS 20-25%, S_DEMAND 10-15%; Phase 7
zeroed S_DEMAND and redistributed proportionally to the four carriers.)

> **Phase X.2.1 — FIX 2 / Phase 6.** `S_CLIMAX` was zeroed in every state
> at X.2.1 (mean OOS IC = -0.0242, sig-negative at two horizons) and
> **removed from the component set entirely in Phase 6** (2026-05-25).
> Component dimension dropped from 10 → 9. Bit-identical for CCQS output
> since the weight was already zero everywhere.
>
> **Phase X.3 — M8 (component cleanup).** Four components carry essentially
> zero OOS signal across all six horizons:
>
> | component | mean OOS IC | post-X.2.1 weight (INDETERMINATE) | post-X.3 weight (INDETERMINATE) |
> |-----------|------------:|--------------------------:|------------------------:|
> | s_momentum    |  0.0000 |  3% |  1% |
> | s_trend_slope | -0.0001 | 10% |  3% |
> | s_rsl         | -0.0013 |  8% |  3% |
> | s_extension   | -0.0070 |  8% |  1% |
>
> The freed 21% (INDETERMINATE state) flows to the four positive OOS carriers:
> `S_RS` +5, `S_RS_LEADERSHIP` +5, `S_STRUCTURE` +5, `S_MTF` +4, `S_DEMAND` +2.
> Same redistribution principle applied to every other state, with
> state-specific tilts (e.g. `S_STRUCTURE` boosted in CONSOLIDATING/DETERIORATING where
> chart structure is most diagnostic; `S_RS_LEADERSHIP` boosted in EXHAUSTION
> as a quality filter against late-stage exhaustion names).
| **Total** | 100% | 100% | 100% | 100% | 100% | 100% |

### Bayesian Averaging Across States

```python
def compute_ccqs_z(component_scores, state_probabilities):
    """
    CCQS = expected value of CCQS over state probability distribution.
    """
    total_z = 0
    for state, p_state in state_probabilities.items():
        state_weights = STATE_WEIGHTS[state]
        state_composite_z = sum(state_weights[c] * component_scores[c] for c in COMPONENTS)
        total_z += p_state * state_composite_z
    
    return total_z
```

### Confidence Blending

When state confidence is low, blend toward INDETERMINATE weights:

```python
def confidence_adjusted_probs(state_probs):
    max_prob = max(state_probs.values())
    
    if max_prob >= 0.7:
        return state_probs  # High confidence: use as-is
    elif max_prob >= 0.5:
        # Medium: 70% original + 30% INDETERMINATE
        adjusted = {s: 0.7 * p for s, p in state_probs.items()}
        adjusted['INDETERMINATE'] = adjusted.get('INDETERMINATE', 0) + 0.3
        return adjusted
    else:
        # Low: 50% original + 50% INDETERMINATE
        adjusted = {s: 0.5 * p for s, p in state_probs.items()}
        adjusted['INDETERMINATE'] = adjusted.get('INDETERMINATE', 0) + 0.5
        return adjusted
```

---

## 9. Composite Scoring & Grading

### From z-score To Displayable 0-100

```python
import scipy.stats as ss

ccqs_z = compute_ccqs_z(components, state_probabilities)
ccqs_raw = ss.norm.cdf(ccqs_z) * 100

# Winsorize at 1st/99th percentile — per-date since Phase 6 (2026-05-25).
# Each row is clipped against its own date's p1 / p99 quantiles. The earlier
# global clip computed one (p1, p99) pair across the entire long frame and
# collapsed every clipped row to those two literal values (24,562 exact ties).
# Per-date clipping preserves cross-sectional dispersion within each date.
ccqs = ccqs_raw.groupby(level='date').transform(
    lambda s: s.clip(lower=s.quantile(0.01), upper=s.quantile(0.99))
)
```

### Grade Thresholds (Per-Date Percentile)

Grades are assigned by cross-sectional percentile rank **within each
snapshot date**, not by absolute CCQS thresholds. Absolute cuts drift with
the universe's mean quality (broad rallies push everyone above 85; broad
selloffs pull everyone below 70), making tier sizes unstable. Per-date
quantiles keep the S/A/B/C/D mix roughly constant day to day.

```python
def grade_per_date(ccqs_series_for_one_date):
    q30 = ccqs_series_for_one_date.quantile(0.30)
    q55 = ccqs_series_for_one_date.quantile(0.55)
    q80 = ccqs_series_for_one_date.quantile(0.80)
    q92 = ccqs_series_for_one_date.quantile(0.92)

    def label(x):
        if x >= q92: return 'S'  # top 8%
        if x >= q80: return 'A'  # next 12%
        if x >= q55: return 'B'  # next 25%
        if x >= q30: return 'C'  # next 25%
        return 'D'               # bottom 30%

    return ccqs_series_for_one_date.map(label)
```

Target tier sizes (by construction of the quantile cuts):
- Grade S: ~8%
- Grade A: ~12%
- Grade B: ~25%
- Grade C: ~25%
- Grade D: ~30%

---

## 10. Setup Categories — 29 Setups

Direct multi-feature detection with priority ordering. Higher-priority setups checked first.

```python
def classify_setup(features, state_probs, ccqs):
    """
    Priority order: most-specific setups first.
    Returns: setup_label, confidence
    """
    
    # ===== EXHAUSTION SETUPS (Priority 1-4) =====
    
    # 1. Extreme Extension  (Phase 5.8 audit: math is pure extension, not "blow-off")
    if features['atr_x_50'] >= 6.5:
        return 'Extreme Extension', 0.95
    
    # 2. Exhaustion w/ Bearish Divergence
    if (features['atr_x_50'] >= 4.0 and 
        features['bearish_divergence_20d'] and
        features['rs_rating_spy'] >= 85):
        return 'Exhaustion w/ Bearish Divergence', 0.90
    
    # 3. Volume-Confirmed Exhaustion
    if (features['atr_x_50'] >= 4.5 and 
        features['climax_volume_flag']):
        return 'Volume-Confirmed Exhaustion', 0.90
    
    # 4. Extended Exhaustion
    if (features['atr_x_50'] >= 4.0 and 
        features['days_near_52w_high_60d'] >= 15 and
        features['rs_rating_spy'] >= 80):
        return 'Extended Exhaustion', 0.75
    
    # ===== DETERIORATING SETUPS (Priority 5-8) =====
    
    # 5. Capitulation Selling
    if (features['pct_ma_50'] < -8 and 
        features['capitulation_volume_flag']):
        return 'Capitulation Selling', 0.85
    
    # 6. Deteriorating w/ Bullish Divergence
    if (features['pct_ma_50'] < -5 and 
        features['bullish_divergence_20d']):
        return 'Deteriorating w/ Bullish Divergence', 0.80
    
    # 7. Distribution Pattern
    if (features['pct_ma_50'] < -5 and 
        features['distribution_days_25'] >= 8):
        return 'Distribution Pattern', 0.85
    
    # 8. Sustained Weakness  (Phase 5.8 audit: math is a static threshold,
    #    not a trend-transition event)
    if features['pct_ma_50'] < -8:
        return 'Sustained Weakness', 0.70
    
    # ===== ELITE LEADER SETUPS (Priority 9-10) =====
    
    # 9. Elite Leader Continuation (TRENDING state, all benchmarks beaten)
    if (state_probs.get('TRENDING', 0) > 0.5 and
        features.get('leadership_tier') == 'ELITE_LEADER'):
        return 'Elite Leader Continuation', 0.95
    
    # 10. Elite Leader Pullback (PULLBACK state, elite)
    if (state_probs.get('PULLBACK', 0) > 0.5 and
        features.get('leadership_tier') == 'ELITE_LEADER'):
        return 'Elite Leader Pullback', 0.95
    
    # ===== PREMIUM LONG SETUPS (Priority 11-13) =====

    # 11. Premium Pullback  (Phase 5.8 audit: math does not check CCQS grade)
    if (features['sma_stack_score'] >= 85 and
        features['ema_stack_score'] >= 70 and
        0 < features['pct_ma_50'] < 10 and
        features['atr_x_50'] < 2.5 and
        features['rs_rating_spy'] >= 80 and
        features['up_down_vol_ratio_50'] >= 1.3):
        return 'Premium Pullback', 0.95

    # 12. Emerging Leader  (Phase 5.8 audit: forward "(Multibagger Setup)" claim dropped)
    if (60 <= features['rs_rating_spy'] <= 85 and
        features['rs_rating_slope_60d'] >= 10 and
        features['mtf_rs_coherence'] >= 2 and
        features['volume_leadership_confirmed']):
        return 'Emerging Leader', 0.85
    
    # 13. Theme Leader Pullback
    if (features.get('is_basket_leader', False) and
        state_probs.get('PULLBACK', 0) > 0.4):
        return 'Theme Leader Pullback', 0.80
    
    # ===== TRENDING SETUPS (Priority 14-15) =====
    
    # 14. Trend Continuation
    if (features['sma_stack_score'] >= 85 and
        features['adx_14'] >= 25 and
        features['atr_x_50'] < 4.5 and
        features['rs_rating_spy'] >= 80 and
        features['supertrend_direction'] == 1):
        return 'Trend Continuation', 0.90

    # 15. Trending Leadership (new_252d_high dropped — too restrictive in
    # range-bound markets; ADX cut loosened from 25 to 20.)
    if (features['sma_stack_score'] >= 75 and
        features['rs_rating_spy'] >= 80 and
        features['adx_14'] >= 20):
        return 'Trending Leadership', 0.85
    
    # ===== PULLBACK SETUPS (Priority 16-17) =====
    
    # 16. Pullback to 21EMA
    if (features['sma_stack_score'] >= 80 and
        abs(features['close'] - features['ema_21']) / features['atr_14'] < 0.7 and
        features['rs_rating_spy'] >= 75):
        return 'Pullback to 21EMA', 0.85
    
    # 17. Pullback to 50MA
    if (features['sma_stack_score'] >= 75 and
        abs(features['close'] - features['sma_50']) / features['atr_14'] < 1.2 and
        features['rs_rating_spy'] >= 70):
        return 'Pullback to 50MA', 0.80
    
    # ===== CONSOLIDATING SETUPS (Priority 18-22) =====
    
    # 18. Consolidation Within Strong Theme
    if (features['bb_squeeze_flag'] and
        features.get('theme_class') in ('ELITE_THEME', 'STRONG_THEME')):
        return 'Consolidation Within Strong Theme', 0.85
    
    # 19. Tight Consolidation Pre-Breakout
    if (features['bb_squeeze_flag'] and
        features['vcp_quality_score'] >= 70 and
        features['rs_rating_spy'] >= 85 and
        features['volume_z_20_252'] >= 0.5):
        return 'Tight Consolidation Pre-Breakout', 0.90
    
    # 20. VCP Setup
    if (features['vcp_quality_score'] >= 60 and
        features['rs_rating_spy'] >= 75 and
        features['sma_stack_score'] >= 75):
        return 'VCP Setup', 0.80
    
    # 21. BB Squeeze with RS
    if (features['bb_squeeze_flag'] and
        features['bb_width_pct_252d'] < 20 and
        features['rs_rating_spy'] >= 70):
        return 'BB Squeeze with RS', 0.75
    
    # 22. Range Consolidation
    if (features['bb_squeeze_flag'] or 
        features['bb_width_pct_252d'] < 15):
        return 'Range Consolidation', 0.70
    
    # ===== FAILURE / TRANSITION (Priority 23) =====

    # 23. Failed Breakout — tightened. The raw `failed_breakout_flag_10d`
    # fires whenever price closes back through a recent breakout pivot,
    # which happens often on healthy "flag taps" of strong stocks. We
    # only label it a real failure when the stock is also below its 50MA
    # and not a market leader.
    if (features['failed_breakout_flag_10d'] and
        features['pct_ma_50'] < 0 and
        features['rs_rating_spy'] < 70):
        return 'Failed Breakout', 0.85

    # ===== STATE-AWARE CATCH-ALLS (Priority 24-29) =====
    # When no specific rule fires, label the row by its primary state so
    # downstream consumers can still distinguish a healthy trend with no
    # sharp setup from a chart in a degenerate state. Only truly INDETERMINATE
    # rows collapse to 'Indeterminate Pattern'.
    # Phase 5.8 audit: catch-all labels renamed to "<State> (Generic)" so
    # they don't imply duration / bias / cycle position / confidence that
    # the catch-all doesn't verify. "Routine Pullback" and
    # "Indeterminate Pattern" remain accurate and unchanged.
    primary = state_probs_argmax  # name of highest-probability state
    if primary == 'TRENDING':      return 'Trending (Generic)',      0.65
    if primary == 'PULLBACK':      return 'Routine Pullback',        0.65
    if primary == 'CONSOLIDATING': return 'Consolidating (Generic)', 0.65
    if primary == 'EXHAUSTION':    return 'Exhaustion (Generic)',    0.65
    if primary == 'DETERIORATING': return 'Deteriorating (Generic)', 0.65
    return 'Indeterminate Pattern', 0.55
```

### Setup Categories Summary

| # | Setup | Direction | Hold Horizon |
|:-:|-------|:---------:|:------------:|
| 1 | Parabolic Blow-Off | SHORT/AVOID | DAYS |
| 2 | Exhaustion w/ Bearish Divergence | SHORT | DAYS |
| 3 | Volume-Confirmed Exhaustion | SHORT | DAYS |
| 4 | Extended Exhaustion | CAUTION | DAYS-WEEKS |
| 5 | Capitulation Selling | LONG-REVERSAL | DAYS-WEEKS |
| 6 | Deteriorating w/ Bullish Divergence | LONG-REVERSAL | DAYS-WEEKS |
| 7 | Distribution Pattern | SHORT | WEEKS |
| 8 | Trend Failure | SHORT/AVOID | WEEKS |
| 9 | Elite Leader Continuation | LONG | WEEKS-MONTHS |
| 10 | Elite Leader Pullback | LONG | WEEKS-MONTHS |
| 11 | Tier S Pullback | LONG | WEEKS-MONTHS |
| 12 | Emerging Leader (Multibagger) | LONG | MONTHS |
| 13 | Theme Leader Pullback | LONG | WEEKS |
| 14 | Trend Continuation | LONG | WEEKS-MONTHS |
| 15 | Trending Leadership | LONG | WEEKS-MONTHS |
| 16 | Pullback to 21EMA | LONG | DAYS-WEEKS |
| 17 | Pullback to 50MA | LONG | WEEKS |
| 18 | Consolidation Within Strong Theme | LONG | WEEKS-MONTHS |
| 19 | Tight Consolidation Pre-Breakout | LONG | WEEKS |
| 20 | VCP Setup | LONG | WEEKS |
| 21 | BB Squeeze with RS | LONG | WEEKS |
| 22 | Range Consolidation | WAIT | - |
| 23 | Failed Breakout | AVOID/SHORT | DAYS |
| 24 | Sustained Uptrend | LONG (low-conf) | WEEKS |
| 25 | Routine Pullback | LONG (low-conf) | WEEKS |
| 26 | Constructive Consolidation | WAIT | WEEKS |
| 27 | Late-Cycle Pattern | CAUTION | DAYS-WEEKS |
| 28 | Low-Confidence Pattern | AVOID | WEEKS |
| 29 | Indeterminate Pattern | WAIT | - |

---

## 11. Leadership & Theme Classification

### Leadership Tier (9 Levels Per Stock — Path 1.5)

Single-benchmark RS keyed off SPY, with QQQ RS Line direction as a
**context confirmation gate** (not a separate ranking dimension).

| Tier | RS Band / Condition | Description |
|------|---------------------|-------------|
| `ELITE_LEADER` | s_lead≥90, rs_spy≥95, mtf=3, vol_conf, basket leader, qqq↑ | Top-shelf, all confirmations on |
| `STRONG_LEADER` | s_lead≥80, rs_spy≥75, mtf≥2 | High RS with MTF confluence |
| `EMERGING_LEADER` | rs_spy 60-85, slope≥10, mtf≥2, qqq↑ | Multibagger discovery zone |
| `ESTABLISHED_LEADER` | rs_spy≥75 & SPY RSL new 252d high | Confirmed leader with structural RS |
| `STRONG_PERFORMER` | rs_spy≥60 | Above-average RS |
| `NEUTRAL` | rs_spy 45-60 | Mid-pack, no other signal |
| `WEAK_PERFORMER` | rs_spy 25-45 & slope≥-5 | Low RS but stable / slightly improving momentum. Not in active decline. Often value / cyclical names in mid-cycle or recovering laggards. |
| `DETERIORATING` | rs_spy<40 & slope<-5 | Actively declining RS |
| `WEAK_LAGGARD` | rs_spy<25 & slope<0 | Chronically weak and still rolling over |

```python
def classify_leadership(features):
    s_lead   = features['s_rs_leadership']
    rs_spy   = features['rs_rating_spy']
    rs_slope = features['rs_rating_slope_60d']
    mtf_coh  = features['mtf_rs_coherence']
    vol_conf = features['volume_leadership_confirmed']
    spy_nh_252 = features['rs_line_spy_new_high_252d']
    qqq_slope_60 = features['rs_line_qqq_slope_60d']   # QQQ context gate
    is_basket_leader = features.get('is_basket_leader', False)

    qqq_context_ok = qqq_slope_60 > 0    # tech-peer confirmation gate

    if (s_lead >= 90 and rs_spy >= 95 and mtf_coh == 3 and vol_conf
        and is_basket_leader and qqq_context_ok):
        return 'ELITE_LEADER'

    if s_lead >= 80 and rs_spy >= 75 and mtf_coh >= 2:
        return 'STRONG_LEADER'

    if (60 <= rs_spy <= 85 and rs_slope >= 10 and mtf_coh >= 2
        and qqq_context_ok):
        return 'EMERGING_LEADER'

    if rs_spy >= 75 and spy_nh_252:
        return 'ESTABLISHED_LEADER'

    if rs_spy >= 60:
        return 'STRONG_PERFORMER'

    if 45 <= rs_spy < 60:
        return 'NEUTRAL'

    # WEAK_PERFORMER — low RS but stable (slope hasn't turned actively
    # negative). Absorbs ~7-9% of the universe that used to be misclassified
    # as NEUTRAL.
    if 25 <= rs_spy < 45 and rs_slope >= -5:
        return 'WEAK_PERFORMER'

    if rs_spy < 40 and rs_slope < -5:
        return 'DETERIORATING'

    if rs_spy < 25 and rs_slope < 0:
        return 'WEAK_LAGGARD'

    # Orphan band (rs_spy<25 with rs_slope≥0, very rare): chronically weak
    # but stabilising — defaults to NEUTRAL.
    return 'NEUTRAL'
```

> **SUPERSEDED (multi-bench 9-tier):** the original classifier branched on
> `rs_rating_qqq`, `rs_rating_iwm`, and `n_benchmarks_beaten`, and added a
> `MID_PACK` tier for the 30 ≤ rs_spy < 50 band. Path 1.5 collapses those
> ranking dimensions (they had collinear ranks anyway) into a single SPY-
> based scheme. `MID_PACK` was folded into the catch-all `NEUTRAL` tier
> since the band-level distinction wasn't load-bearing for the
> discretionary workflow. `qqq_slope_60 > 0` is the surviving QQQ signal,
> acting as a context confirmation gate for top tiers.
>
> **Phase 3 addition:** `WEAK_PERFORMER` was reintroduced as a 9th tier to
> absorb the low-RS-but-stable cohort (~7-9% of the universe) that was
> bloating `NEUTRAL` to 40%+ after the multi-bench collapse. With this
> tier, `NEUTRAL` recovers its intended meaning: genuinely mid-pack RS,
> not chronically weak.

### Theme Classification (7 Tiers Per Basket)

Computed in aggregation layer (Section 12):

```python
def classify_theme(theme_features):
    theme_ccqs = theme_features['theme_ccqs']
    momentum_class = theme_features['theme_momentum_class']
    leadership_conc = theme_features['leadership_concentration']
    rs_nh = theme_features['theme_rs_new_252d_high']
    breadth = theme_features['pct_above_50dma']
    
    if (theme_ccqs >= 90 and 
        momentum_class in ['STRONG_ACCELERATING', 'MODERATE_ACCELERATING'] and
        rs_nh and breadth >= 75):
        return 'ELITE_THEME'
    
    if theme_ccqs >= 80 and breadth >= 60 and rs_nh:
        return 'STRONG_THEME'
    
    if (60 <= theme_ccqs < 80 and 
        momentum_class == 'STRONG_ACCELERATING' and 
        breadth >= 50):
        return 'EMERGING_THEME'  # Multibagger discovery zone
    
    if theme_ccqs >= 75 and leadership_conc == 'CONCENTRATED':
        return 'NARROW_LEADERSHIP'
    
    if 50 <= theme_ccqs < 75:
        return 'STABLE'
    
    if (theme_ccqs < 50 and 
        momentum_class in ['DECELERATING', 'WEAKENING']):
        return 'WEAKENING'
    
    if theme_features['pct_deteriorating'] >= 30:
        return 'BROKEN_THEME'
    
    return 'MIXED'
```

---

## 12. Aggregation Layer — Theme Strength

For each populated CORE basket, compute ~25 metrics:

### Per-Basket Metrics

**Score aggregates:** mean, median, std, max, min, q25, q75 of constituent CCQS.

**Breadth metrics:**
- `pct_above_50dma`, `pct_above_200dma`
- `pct_at_60d_high`, `pct_at_252d_high`
- `pct_full_sma_stack`, `pct_full_ema_stack`
- `pct_supertrend_bull`
- `pct_rs_rating_above_70`, `pct_rs_rating_above_85`
- `pct_rs_line_new_high`
- `pct_grade_s`, `pct_grade_a_plus`, `pct_grade_d`
- `pct_exhaustion`, `pct_deteriorating`

**Theme RS Line (basket equal-weighted index vs SPY):**
```python
basket_returns = ohlcv_df[basket_constituents].pct_change().mean(axis=1)
basket_index = (1 + basket_returns).cumprod() * 100
theme_rs_line = basket_index / spy_index
```
- `theme_rs_line_value`
- `theme_rs_new_60d_high`, `theme_rs_new_252d_high`
- `theme_rs_slope_20d`, `theme_rs_slope_60d`
- `theme_rs_r_squared_60d`
- `theme_rs_pct_252d`

**Momentum acceleration:**
- `theme_rs_change_30d`, `theme_rs_change_60d`, `theme_rs_change_90d`
- `theme_momentum_class`: STRONG_ACCELERATING / MODERATE_ACCELERATING / STABLE / DECELERATING / WEAKENING

**Dispersion:**
- `basket_ccqs_cv` (coefficient of variation)
- `basket_top_3_share` (Gini-like concentration)
- `leadership_concentration`: CONCENTRATED / MODERATE / BROAD

**Volume:**
- `theme_avg_ud_ratio`, `theme_pct_strong_ud`
- `theme_avg_cmf`
- `theme_avg_dist_days`
- `theme_volume_confirmation` (binary)

**Setup counts:**
- `n_multibagger_setups`
- `n_tier_s_pullback`
- `n_elite_leaders`

### Theme CCQS Composite

```python
theme_ccqs_z = (
    0.25 * z(avg_ccqs) +
    0.25 * z(breadth_composite) +
    0.20 * z(theme_rs_composite) +
    0.15 * z(momentum_acceleration) +
    0.10 * z(volume_confirmation) +
    0.05 * z(health_indicators)
)
theme_ccqs = norm.cdf(theme_ccqs_z) * 100
```

---

## 13. Reliability Architecture — 8 Layers

### Layer 1: Data Quality Firewall (Critical)

Run BEFORE any feature computation. Tickers failing critical checks excluded from scoring.

**Critical failures (exclude from scoring):**
- `NO_DATA`: empty DataFrame
- `INSUFFICIENT_HISTORY`: < 252 days
- `STALE_DATA`: last bar > 5 days ago
- `INVALID_PRICES`: zero or negative prices
- `ZERO_VOLUME`: 20-day vol sum = 0
- `INSUFFICIENT_LIQUIDITY`: < $100K ADV
- `SUSPICIOUS_BAR`: > 50% one-day move with reversal

**Warnings (score but flag):**
- `LARGE_GAP_RECENT`: > 30% one-day move in last 20d
- `VOLUME_COLLAPSE`: recent vol < 10% historical
- `LOW_LIQUIDITY`: < $1M ADV
- `FREQUENT_GAPS`: 5+ gaps > 5% in 20d
- `FREQUENT_DOJI`: 5+ doji bars in 20d
- `POSSIBLE_CORPORATE_ACTION`: close vs adj_close discrepancy

### Layer 2: Corporate Action Detection

Detect splits, spinoffs, halts:

```python
def detect_corporate_actions(ohlcv):
    ratio = ohlcv['close'] / ohlcv['adj_close']
    ratio_change = ratio.pct_change()
    split_dates = ratio_change[abs(ratio_change) > 0.10].index
    
    close_return = ohlcv['close'].pct_change()
    adj_return = ohlcv['adj_close'].pct_change()
    spinoff_candidates = (abs(close_return - adj_return) > 0.05)
    
    return {'splits': split_dates, 'possible_spinoffs': spinoff_candidates}
```

### Layer 3: TradingView Parity Tests

Maintain ~20 reference snapshots:

```python
TV_REFERENCE_VALUES = {
    'NVDA_2024-12-31': {
        'close': 134.29, 'sma_50': 138.42, 'sma_200': 117.93,
        'atr_14': 4.31, 'adx_14': 27.85, 'rsi_14': 48.23,
        'macd_line': -1.42, 'macd_signal': -1.81, 'macd_histogram': 0.39,
        'bb_upper_20': 145.82, 'bb_lower_20': 130.91,
        'supertrend_direction': -1,
    },
    # ... ~20 more snapshots
}

def test_tv_parity():
    """All computed indicators must match TradingView to 2 decimal places."""
    for snapshot_id, expected in TV_REFERENCE_VALUES.items():
        ticker, date = snapshot_id.rsplit('_', 1)
        actual = compute_features(load_ohlcv(ticker, end=date))
        for indicator, expected_val in expected.items():
            assert abs(actual.iloc[-1][indicator] - expected_val) < 0.01
```

### Layer 4: Score Anomaly Detection

Daily comparison vs recent history. Flag:
- Score change > 4σ from 5-day rolling
- Grade jumps of 2+ levels
- Unexpected state flips
- New tickers / removed tickers

### Layer 5: Sanity Check Assertions

Daily automated assertions:
- CCQS bounded [0, 100]
- Grades match score ranges
- Component contributions sum to total
- State probabilities sum to 1
- Universe coverage ≥ 85%
- Grade S frequency in 2-20% range

If any assertion fails: log loudly, refuse to publish.

### Layer 6: Snapshot Archive

Every refresh saves complete state. Enables time-travel and audit.

### Layer 7: Manual Override Layer

YAML config (`data/manual_overrides.yaml`):
- `exclude_tickers`: list of tickers to skip
- `flag_tickers`: add warning flags
- `force_state`: override state classification
- `data_quality_overrides`: suppress specific warnings

### Layer 8: Health Monitoring Dashboard Banner

Top-of-app banner with system status:
- Last refresh timestamp
- Coverage (n_scored / n_universe)
- Anomalies count
- Sanity check pass/fail
- Running 60-day IC

---

## 14. Output Layer — Dashboard Views

Streamlit dashboard with 8 views:

### View 1: Theme Leaderboard (Primary View)

Ranked table of populated CORE baskets:
- Theme name, N constituents
- Theme CCQS, theme class, avg/median CCQS
- % Grade A+, % Climactic, % Broken
- Theme RS direction, breadth metrics
- Theme momentum acceleration
- Multibagger count, Tier S Pullback count
- Top 3 names

Sortable by any column. Filterable by category/class.

### View 2: Factor Decomposition

For selected basket: average component scores per S_X.
- Bar chart comparing to universe average
- Identifies which factors drive theme strength

### View 3: Per-Name Drill-Down

Sortable table:
- Ticker, CCQS, Grade, State (with confidence)
- Setup category, Leadership Tier
- RS Rating vs SPY (with QQQ RS Line direction as context)
- %MA50, ATR×50, U/D Vol
- MACD posture
- Tags (other baskets)

Click ticker → detailed view (Section 4 below).

### View 4: Tag/Theme Filter

Cross-sector overlay filtering. Select tag basket → see all names tagged.

### View 5: Country ETF Tier

Separate ranking for 35 country ETFs. Same CCQS framework.

### View 6: RS Leaders View

Filterable by:
- Leadership tier
- Multi-benchmark class
- Theme class
- State / setup

Show: all top RS leaders with full multi-benchmark context.

### View 7: Multibagger Discovery View

Names with:
- `leadership_tier == 'EMERGING_LEADER'`
- In themes classified `EMERGING_THEME` or `STRONG_THEME`
- Setup: 'Emerging Leader (Multibagger Setup)' or 'Consolidation Within Strong Theme'

This is the "where to look for next NVDA" view.

### View 8: Per-Name Detail (Drill-Down)

For selected ticker:
```
NVDA — CCQS 89 [Grade S]
├── Setup: Elite Leader Continuation (confidence 0.92)
├── State: TRENDING (conf 0.92)
├── Leadership Tier: ELITE_LEADER
│
├── RS Rating vs SPY: 99 (RS Line at 252d high ✓)
├── QQQ RS Line: slope_60d +14.2% (tech-peer context ✓)
│
├── MTF Coherence: 3/3
├── Volume Confirmed: ✓
├── Within-Basket Rank: 1/3
│
├── Theme: AI Compute and Accelerators (ELITE_THEME)
│   ├── Theme CCQS: 87
│   ├── Theme Breadth (>50DMA): 100%
│   └── Theme Momentum: STRONG_ACCELERATING
│
├── Components (contribution to CCQS):
│   S_RS_LEADERSHIP:  92  →  +0.17
│   S_RS:             87  →  +0.10
│   S_STRUCTURE:      85  →  +0.11
│   ...
│
├── Key Technical Features:
│   %MA 50:   +8.3%
│   ATR×50:    1.8
│   ADX:      32.5
│   R²:        0.82
│   RSI:      62
│   MACD:     Positive/Accelerating/Strong
│   ...
│
└── Tags: [AI Data Center Capex, HBM Capacity, Edge AI Inference]
```

### Branding

ADFM brand:
- Color palette: navy (#0a2540), gold accent
- Typography: DM Sans / DM Serif Display + IBM Plex
- Dark and white theme variants

---

## 15. File Structure

```
CCQS_V1/
├── data/
│   ├── __init__.py
│   ├── universe.py                 # Canonical universe (LOCKED - do not modify)
│   ├── manual_overrides.yaml       # Override mechanism
│   ├── cache/                      # Daily refresh cache (gitignored)
│   │   ├── ohlcv_daily.parquet
│   │   ├── ohlcv_meta.json
│   │   ├── failed_tickers.json
│   │   └── data_quality_report.json
│   └── snapshots/                  # Daily archives (gitignored)
│       └── YYYY-MM-DD/
│
├── compute/
│   ├── __init__.py
│   ├── loader.py                   # yfinance batch fetcher
│   ├── data_quality.py             # Data quality firewall
│   ├── features.py                 # 104 features, vectorized (Path 1.5)
│   ├── standardization.py          # Robust z-score framework
│   ├── components.py               # 10 component scores
│   ├── state.py                    # Probabilistic state classification
│   ├── ccqs.py                     # Composite engine + grading
│   ├── setup_classifier.py         # 24 setup categories
│   ├── leadership.py               # Leadership tier classification
│   ├── aggregation.py              # Theme-level rollup
│   └── reliability/
│       ├── __init__.py
│       ├── corporate_actions.py
│       ├── anomaly_detection.py
│       ├── sanity_checks.py
│       ├── snapshot.py
│       └── ic_tracker.py
│
├── output/
│   └── app.py                      # Streamlit dashboard (8 views)
│
├── tests/
│   ├── __init__.py
│   ├── test_loader.py
│   ├── test_data_quality.py
│   ├── test_features.py
│   ├── test_components.py
│   ├── test_state.py
│   ├── test_setup_classifier.py
│   ├── test_aggregation.py
│   ├── reference/
│   │   ├── tv_snapshots.py
│   │   └── test_tv_parity.py
│   └── integration/
│       └── test_end_to_end.py
│
├── .github/
│   └── workflows/
│       └── refresh.yml             # Daily refresh action
│
├── requirements.txt
├── README.md
├── SPEC.md                         # This document
└── .gitignore
```

---

## 16. Build Phases

Build the system incrementally, validating at each phase.

### Phase 1: Foundation (FIRST)

Create:
- `requirements.txt`
- `.gitignore`
- `README.md` (project description)
- `data/manual_overrides.yaml` (empty template)
- `data/__init__.py` (empty)
- `compute/__init__.py` (empty)
- `compute/reliability/__init__.py` (empty)
- `compute/loader.py` (yfinance batch fetcher with SPY/QQQ benchmarks, parquet caching, retry logic, failure logging)
- `compute/data_quality.py` (quality firewall per Section 13 Layer 1)

Test:
```bash
python3.13 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m compute.loader      # Pull 910 tickers + 3 benchmarks
python -m compute.data_quality # Run quality checks
```

Expected:
- ~895-905 tickers fetched successfully
- ~8-15 typical failures (delisted, illiquid)
- ~750-850 tickers PASS quality
- ~50-150 tickers WARNING (still scored)
- ~10-30 tickers FAIL (excluded)
- NVDA/SPY/QQQ closing prices match TradingView

### Phase 2: Features + Standardization

Create:
- `compute/features.py` (all 104 features, vectorized using pandas/numpy)
- `compute/standardization.py` (robust z-score framework)
- `tests/test_features.py` (unit tests for feature correctness)

Test on a sample of 10 tickers; verify feature values against TradingView spot checks.

### Phase 3: Components + State + Composite Scoring

Create:
- `compute/components.py` (10 component scores)
- `compute/state.py` (probabilistic classification)
- `compute/ccqs.py` (composite engine + grading)
- `compute/setup_classifier.py` (24 setups)
- `compute/leadership.py` (leadership tier)
- `tests/test_components.py`, `tests/test_state.py`

Test: full universe scoring. Should complete in <30s. Distribution sanity: ~5-10% Grade S.

### Phase 4: Aggregation + Reliability

Create:
- `compute/aggregation.py` (theme-level rollup)
- `compute/reliability/*.py` (all 5 reliability submodules)
- `tests/reference/tv_snapshots.py` (~20 TV reference snapshots)
- `tests/reference/test_tv_parity.py`
- `tests/integration/test_end_to_end.py`

Run end-to-end pipeline. All sanity checks pass.

### Phase 5: Streamlit Dashboard

Create:
- `output/app.py` (8 dashboard views with ADFM brand)

Test locally with `streamlit run output/app.py`. Verify all views render correctly.

### Phase 6: Deployment

Create:
- `.github/workflows/refresh.yml` (daily refresh at 4:15pm ET)
- README deployment instructions
- Streamlit Cloud configuration

Deploy to private GitHub + Streamlit Community Cloud.

---

## Implementation Guidelines

### Code Quality

- All functions documented with docstrings
- Type hints throughout (Python 3.13+)
- Vectorized operations (pandas/numpy); avoid Python loops where possible
- Pinned dependency versions in requirements.txt

### Determinism

- No random number generation in scoring
- All operations deterministic
- Same inputs → identical outputs

### Performance Targets

- Data pull: < 2 minutes for 910 tickers
- Feature computation: < 30 seconds for full universe
- Scoring: < 5 seconds
- Total daily refresh: < 5 minutes

### Logging

- Use `loguru` for structured logging
- INFO level for normal operations
- WARNING for quality issues
- ERROR for failures
- Logs to stdout AND `logs/ccqs.log`

---

## Reference Card — Key Numbers

| Metric | Value |
|--------|------:|
| Universe size | 910 tickers |
| Baskets | 275 (180 CORE / 60 TAG / 35 COUNTRY) |
| Manual overrides | 734 |
| Benchmarks | 2 (SPY, QQQ) — Path 1.5 |
| Features per stock | 104 — Path 1.5 |
| Components | 10 |
| States | 6 |
| Setup categories | 24 |
| Leadership tiers | 7 — Path 1.5 |
| Theme classes | 7 |
| Dashboard views | 8 |
| Reliability layers | 8 |

---

**End of Specification**

This is the complete locked specification for CCQS V1. Use this as the authoritative reference when implementing each phase. Do not deviate without explicit user approval.
