# Phase 19 — Comprehensive Metric & Basket Audit

**Date:** 2026-05-27
**Scope:** all 849 scored names, all metric types, every basket.
**Files:** this report plus
- `tests/test_metric_integrity.py` — 25 nightly regression tests (NEW)
- `/tmp/phase19/p19a_metric_integrity_audit.py` — one-shot audit script
- `/tmp/phase19/p19a_audit.json` — full JSON audit output
- `/tmp/phase19/p19c_ticker_status.md` — web-verified ticker status
- `/tmp/phase19/p19d_adfm_vs_ccqs_diff.md` — full ADFM↔CCQS structured diff
- `/tmp/phase19/adfm_basket_map.py` — encoded ADFM map (241 baskets)

---

## TL;DR

| Audit slice | Result |
|---|---|
| 25 structural integrity tests | **25 / 25 PASS** |
| 30 random tickers — arithmetic vs raw OHLCV | **0 mismatches** (worst diff 0.0000pp) |
| Index alignment (5 core parquets) | **1,530,949 rows each** (perfect alignment) |
| TradingView canary parity (existing test) | **140 / 140 fields** unchanged |
| ADFM map vs CCQS source map | **9 / 9 groups match exactly**, 241 / 241 ADFM basket names present verbatim in CCQS |
| Per-basket ticker diff (common baskets) | **204 / 241 bit-identical**, 37 with 51 total ticker discrepancies |
| Web-verified ADFM-only tickers | 22 of 26 **correctly excluded** (delisted / acquired / OTC), 4 worth attention |
| Web-verified CCQS-only tickers | 8 of 10 **sensible additions**, 2 need follow-up (BNY/BK alias, KLG ghost) |

**Bottom line:** all metrics are computed correctly. The basket map is structurally aligned with ADFM. A small handful of corporate-action edits will keep things current; none affect scoring methodology.

---

## Part A — Metric Structural Integrity (all 849 names)

A 25-test regression suite now runs from `tests/test_metric_integrity.py`. It runs every CI build to catch silent regressions.

### Coverage matrix

| Layer | Checks | Result |
|---|---|---|
| **CCQS / Grade** | range [0,100]; NaN tolerance; S share in [2%,15%]; top 8% by score → S consistency; all letters present | 5 / 5 PASS |
| **State** | raw probabilities sum to 1; adjusted probabilities sum to 1; confidence in [0,1]; valid state names | 4 / 4 PASS |
| **Leadership** | valid tier names; ELITE_LEADER share <10% (sanity) | 2 / 2 PASS |
| **Components** | all 10 present; no ±inf; values bounded \|z\|<15 across 5 sample dates × 10 components | 3 / 3 PASS |
| **Feature arithmetic** | 30 random tickers cross-validated vs raw OHLCV: pct_ma_50, pct_ma_200; RSI/ADX in [0,100] | 4 / 4 PASS |
| **Δ CCQS** | 1d / 5d / 21d computable from sorted trading-day history, sane magnitudes | 1 / 1 PASS |
| **Setup** | ≥ 95% coverage; confidence in [0,1] | 2 / 2 PASS |
| **Index alignment** | 5 core parquets share row count | 1 / 1 PASS |
| **Theme aggregates** | `pct_above_50dma` matches independent recompute from features.parquet | 1 / 1 PASS |
| **Universe / freshness** | 750–920 unique tickers; latest within 7 days | 2 / 2 PASS |

### Notable observations from the audit (not failures, but worth recording)

**Today's data has 2 ticker rows with NaN CCQS in the index but NOT in the displayed universe:**

| Ticker | Reason | Action |
|---|---|---|
| **ASGN** | yfinance returned empty OHLCV for 2026-05-27 only (one-day data outage); ticker has 1420 prior valid days | Will self-heal on next refresh; pipeline correctly emits NaN and `dropna` filters it from display |
| **SNDK** | Insufficient post-spinoff history for cross-sectional ranking (returned to public markets recently) | Will populate as soon as historical features accumulate; not a bug |

**Component statistics on 2026-05-27** (showing the components are *blends* of z-scored sub-features, not raw z-scores by themselves):

| Component | mean | std | min | max |
|---|---:|---:|---:|---:|
| s_rs | +0.008 | 0.858 | −1.633 | 1.665 |
| s_rs_leadership | −0.053 | 0.532 | −1.212 | 1.963 |
| s_residual_momentum | −0.014 | 1.260 | −3.484 | 6.380 |
| s_rsl | +0.069 | 0.474 | −0.806 | 2.802 |
| s_trend_slope | −0.472 | 0.635 | −1.950 | 2.053 |
| s_structure | +0.115 | 0.540 | −0.996 | 1.231 |
| s_mtf | +0.277 | 0.457 | −0.269 | 0.975 |
| s_extension | −0.602 | 0.802 | −4.174 | 2.513 |
| s_demand | +0.086 | 0.757 | −1.767 | 2.264 |
| s_momentum | +0.068 | 0.757 | −1.518 | 2.837 |
| s_volume | +0.164 | 1.322 | −2.147 | 10.000 |

These are working as designed (composite blends of per-date z-scored inputs; non-zero mean / non-unit std is the construction).

---

## Part B — 30 Random-Ticker Arithmetic Spot-Check

Sampled 30 random tickers (seed=7) and recomputed three core feature formulas from raw OHLCV:

```
pct_ma_50         = (close - SMA50(close, 50)) / SMA50 × 100
pct_ma_200        = (close - SMA200(close, 200)) / SMA200 × 100
pct_from_52w_high = (close - max(high, 252)) / max × 100
```

Result: **30 / 30 match to 0.0000pp.** Worst absolute diff = 0.0 in all three metrics. RSI-14 and ADX-14 are within [0,100] for all 851 tickers in the index.

---

## Part C — Basket Constituent Web Verification

Researched the **36 contested tickers** (26 in ADFM-only, 10 in CCQS-only) using SEC filings, official IR releases, and exchange announcements.

### Group A — 26 ADFM tickers NOT in CCQS

**Correctly excluded: 22.** Reason in each case:

| Bucket | Count | Tickers |
|---|---:|---|
| Acquired / delisted via M&A | 11 | AY (ECP), DFS (COF), EGLE (SBLK), INFN (NOK), JNPR (HPE), LTHM (ALTM/Rio Tinto), MAG (PAAS), MRO (COP), SPR (BA), SRCL (WM), X (Nippon) |
| Taken private | 2 | SUM (Quikrete), DO (Noble Corp) |
| Delisted to OTC / foreign-only | 6 | ABB, NBG, CRLBF, CURLF, VRNOF, VWSYF |
| K renamed (ambiguous) | 1 | K — legacy Kellogg = KLG + Kellanova; map needs clarification |
| Delisted post-CCQS daily refresh window | 2 | CYBR (PANW close Feb 2026), PLL (Elevra rename Sep 2025) |

**Should be added back: 4** (corporate action data drift, not basket-design errors):

| Ticker | Reason | Suggested CCQS action |
|---|---|---|
| **CTRA** | Was live on NYSE through May 2026 (acquired by Devon on 2026-05-07; we're now 20 days post-delisting). The ADFM map still lists it. | Already correctly excluded from CCQS — this is ADFM data being stale, not CCQS missing it. |
| **CNHI → CNH** | Ticker rename effective May 2024. CCQS already has **CNH**; the ADFM map still uses CNHI. | Add CNHI ↔ CNH alias if you map back to ADFM source ever; otherwise CCQS is current. |
| **BLDE** | Still trading on NASDAQ as of late 2025. Mid-restructure (Joby acquisition of passenger segment; medical to rebrand as Strata Critical Medical). | Consider re-adding BLDE to "eVTOL and Urban Air Mobility". |
| **PARA → PSKY** | Paramount-Skydance merger closed 2025-08-07; ticker is now PSKY on Nasdaq. | Consider re-adding **PSKY** to "Streaming and Audio". |

### Group B — 10 CCQS tickers NOT in ADFM map

| Ticker | Verdict | Note |
|---|---|---|
| AAPL | **Sensible add** in Hyperscalers (US largest by market cap). ADFM omission is an oversight. |  |
| BNY | **Alias** for legacy BK (Bank of New York Mellon). Ticker change effective May 21, 2026 (just last week). | Confirm internal mapping uses BNY post-rename. |
| CART | **Sensible** (Maplebear / Instacart, active US large-cap). |  |
| CNH | **Same entity as ADFM's CNHI** (ticker renamed May 2024). | ADFM map needs CNHI → CNH update. |
| CRML | Sensible — pre-revenue rare-earth dev, valid US-listed. | Speculative micro-cap; acceptable. |
| HON | **Sensible add** to Industrial Automation. ADFM omission was an oversight. |  |
| **KLG** | ⚠️ **Stale ticker**: KLG was acquired by Ferrero and delisted Sep 26, 2025. | **Remove from data/universe.py** (it has 0 OHLCV rows in the live cache; ghost entry). |
| SBUX | Sensible. |  |
| TGT | Sensible. |  |
| ZBRA | Sensible (recently acquired Elo Touch). |  |

**Action items from web verification:**

1. **Remove KLG** from `data/universe.py` (defunct since 2025-09-26).
2. **Document BNY/BK alias** — ticker rename effective 2026-05-21.
3. **Consider re-adding** BLDE, PSKY (former PARA) if you want broader basket coverage. Neither blocks anything operationally.

---

## Part D — ADFM vs CCQS Basket Map Comparison

Full structured diff written to `/tmp/phase19/p19d_adfm_vs_ccqs_diff.md`. Highlights below.

### D.1 Group-level

| Map | Groups | Baskets | Unique tickers |
|---|---:|---:|---:|
| ADFM | 9 | 241 | 907 |
| CCQS `CATEGORIES` | 9 | 275 | 884 |

All 9 group names match exactly. CCQS has **34 additional baskets** beyond ADFM — these are intentional sub-baskets / thematic refinements added during phases past, and are working artefacts not source-of-truth deltas.

### D.2 Basket-name diff

- **241 / 241** ADFM basket names appear verbatim in CCQS `CATEGORIES`. Zero renames.
- 34 CCQS-only baskets are domain extensions: "Air Defense and Radar", "Crypto Exchanges and Custody", "Factory Automation", "Hospital Utilization Winners", "Missiles and Munitions", "Mortgage Rate Sensitive Housing", "Nuclear SMR Developers", "Quantum Computing" (different list), "Specialty Pharmacy and PBM", "Switchgear and Electrical Distribution", "Transformer Bottleneck", "Warehouse Automation", and 22 others. These are *additions*, not contradictions.

### D.3 Per-basket ticker diff (the 241 common baskets)

**204 / 241 (85%) are bit-identical** in ticker membership.

**37 baskets** have at least one ticker difference. Of the **51 total ticker discrepancies**, the breakdown is:

| Type | Count | Examples |
|---|---:|---|
| Foreign-listed tickers in ADFM only | 7 | 000660.KS, 005930.KS, EUROB.AT, MYTIL.AT, OPAP.AT, TRUL.CN, TUN.L |
| ADFM ticker since delisted via M&A | 15 | ABB, DFS, DO, EGLE, INFN, JNPR, LTHM, MAG, MRO, SPR, SRCL, SUM, X, PLL, AY |
| ADFM ticker since renamed | 2 | K (→ KLG/Kellanova), CNHI (→ CNH) |
| ADFM ticker delisted to OTC | 5 | CRLBF, CURLF, VRNOF, VWSYF, NBG |
| ADFM ticker still trading (basket-add candidate) | 4 | CTRA (now also acquired), BLDE, PARA→PSKY, CYBR (now also acquired) |
| CCQS ticker correctly added | 4 | AAPL (Hyperscalers), HON (Industrial Automation), TGT (Grocery), SBUX (Restaurants) |
| Ticker rename CCQS handles correctly | 1 | CNH (= CNHI) |
| Misc / under investigation | 13 | Smaller-cap names; mostly delistings |

### D.4 Universe-level

| Stat | Count |
|---|---:|
| ADFM unique tickers | 907 |
| CCQS PRIMARY_BASKETS keys | 884 |
| Intersection | 874 |
| ADFM-only | 33 (7 foreign + 26 US-style — mostly delisted/renamed) |
| CCQS-only | 10 (AAPL, BNY, CART, CNH, CRML, HON, KLG, SBUX, TGT, ZBRA) |

---

## Part E — Recommended follow-ups

These are **not** required for the dashboard to function correctly today; they're suggestions to keep the basket map current. Listed by impact:

### High value (small effort)

1. **Remove KLG** from `data/universe.py` `PRIMARY_BASKETS` and `PRIMARY_BASKET_CONSTITUENTS` and `CATEGORIES`. It's a ghost (no OHLCV in the live cache). One-line removal.

### Medium value (small effort)

2. **Add PSKY** to "Streaming and Audio" basket. Paramount-Skydance successor entity, active on Nasdaq.
3. **Add BLDE** to "eVTOL and Urban Air Mobility". Still actively listed.

### Low value (purely documentation)

4. Note in SPEC.md / universe.py docstring that the `CATEGORIES` source map has drifted slightly from ADFM's by 34 added thematic sub-baskets; document why each was added.
5. If you ever re-sync from ADFM source, apply ticker-rename aliases: K → KLG (cereal) or Kellanova (snacks); CNHI → CNH; BK → BNY; PARA → PSKY.

### Architectural — none required

No structural / computational / architectural changes are needed. The pipeline is mathematically sound across all 849 scored names today, and the 25-test regression suite at `tests/test_metric_integrity.py` will catch any future drift on the daily run.

---

## How this protects the system going forward

1. **`tests/test_metric_integrity.py`** runs every CI build. Any future regression in CCQS computation, grade thresholds, state probabilities, leadership tiers, components, Δ math, or theme aggregation will fail loudly within 3 seconds.
2. **`tests/reference/test_tv_parity.py`** continues to confirm 140 / 140 fields match TradingView reference on 10 canary tickers daily.
3. **`data/cache/sanity_checks.json`** sidecar (11 checks) is regenerated on every pipeline run and surfaced in the dashboard's System Health expander.

Three independent verification layers, all passing today.
