# CCQS V1 — Composite Chart Quality Score

**Daily technical, momentum, and strength screening tool** for L/S discretionary equity analysis.

Computes a 0-100 CCQS score for each of 910 stocks/ETFs across 275 baskets:
- Trending leaders (RS-confirmed, multi-timeframe)
- Buyable pullbacks (Tier S setups)
- Pre-breakout coils (VCP, BB squeeze)
- Climactic exhaustion (short candidates)
- Broken downtrends (avoid/short)
- Early-stage multibaggers (RS ramping in strong themes)

See [SPEC.md](SPEC.md) for the full specification.

---

## Setup (macOS)

Requires **Python 3.13+**. Install with Homebrew if missing:

```bash
brew install python@3.13
```

Create venv, activate, and install dependencies:

```bash
cd /Users/shreyaansh/Documents/CCQS_V1
python3.13 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Phase 1 Usage

Pull OHLCV data (910 tickers + SPY/QQQ/IWM benchmarks, 5-year lookback):

```bash
python -m compute.loader
```

Run data quality firewall:

```bash
python -m compute.data_quality
```

Outputs go to `data/cache/`:
- `ohlcv_daily.parquet` — all OHLCV
- `ohlcv_meta.json` — pull timestamp, ticker counts
- `failed_tickers.json` — tickers that failed fetch
- `data_quality_report.json` — quality firewall results

---

## Project Structure

```
CCQS_V1/
├── data/
│   ├── universe.py             # Canonical universe (910 tickers, LOCKED)
│   ├── manual_overrides.yaml   # Override layer
│   ├── cache/                  # Daily refresh cache (gitignored)
│   └── snapshots/              # Daily archives (gitignored)
│
├── compute/
│   ├── loader.py               # yfinance batch fetcher
│   ├── data_quality.py         # Quality firewall (Layer 1)
│   ├── features.py             # 108 features (Phase 2)
│   ├── standardization.py      # Robust z-scores (Phase 2)
│   ├── components.py           # 10 components (Phase 3)
│   ├── state.py                # Probabilistic state (Phase 3)
│   ├── ccqs.py                 # Composite engine (Phase 3)
│   ├── setup_classifier.py     # 24 setups (Phase 3)
│   ├── leadership.py           # Leadership tier (Phase 3)
│   ├── aggregation.py          # Theme rollup (Phase 4)
│   └── reliability/            # 5 reliability submodules (Phase 4)
│
├── output/
│   └── app.py                  # Streamlit dashboard (Phase 5)
│
├── tests/                      # Unit + integration + TV parity
│
├── requirements.txt
├── README.md
└── SPEC.md                     # Specification
```

---

## Build Phases

| Phase | Status | Description |
|-------|--------|-------------|
| 1     | In progress | Foundation: loader + data quality |
| 2     | Pending  | 108 features + standardization |
| 3     | Pending  | Components + state + composite scoring |
| 4     | Pending  | Aggregation + reliability layers |
| 5     | Pending  | Streamlit dashboard |
| 6     | Pending  | Deployment (Streamlit Cloud + GH Actions) |

---

## Data

- **Source:** yfinance (free, no API key); Stooq backup for verification
- **Cadence:** Daily refresh, 3hr TTL during market hours
- **Lookback:** 5 years (1,260 trading days)
- **Benchmarks:** SPY, QQQ, IWM

`data/universe.py` is **LOCKED** — do not regenerate or modify.

---

## Use Case

- **User:** ADFM L/S discretionary equity analyst
- **Workflow:** Macro models say risk-on → use CCQS to find best equity setups
- **Time horizons:** Days to weeks to months
- **Tool role:** Screening + ranking; user judgment overlays
- **NOT:** Predictive signal, position sizer, or systematic execution
