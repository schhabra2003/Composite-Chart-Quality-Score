"""
TradingView parity test — checks the live pipeline outputs against
`tv_snapshots.TV_SNAPSHOTS` for 10 canary tickers.

Run:
    python -m tests.reference.test_tv_parity

Exit code 0 if all canaries pass tolerance, non-zero with a per-field
report if any fail. Intended for daily CI / pre-publish gating.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from tests.reference.tv_snapshots import TV_SNAPSHOTS, TOLERANCES, EXACT_FIELDS, REFERENCE_DATE

CACHE = Path("data/cache")


def _load_live() -> dict[str, pd.DataFrame]:
    return {
        "features": pd.read_parquet(CACHE / "features.parquet"),
        "ccqs": pd.read_parquet(CACHE / "ccqs.parquet"),
        "state": pd.read_parquet(CACHE / "state.parquet"),
        "leadership": pd.read_parquet(CACHE / "leadership.parquet"),
        "setups": pd.read_parquet(CACHE / "setups.parquet"),
        "ohlcv": pd.read_parquet(CACHE / "ohlcv_daily.parquet"),
    }


def _live_row(d: dict[str, pd.DataFrame], ticker: str, date: pd.Timestamp) -> dict:
    f = d["features"].loc[(ticker, date)]
    c = d["ccqs"].loc[(ticker, date)]
    s = d["state"].loc[(ticker, date)]
    l = d["leadership"].loc[(ticker, date)]
    st = d["setups"].loc[(ticker, date)]
    oh = d["ohlcv"]
    oh_row = oh[(oh["ticker"] == ticker) & (oh["date"] == date)].iloc[0]
    return {
        "close": float(oh_row["close"]),
        "rs_rating_spy": float(f["rs_rating_spy"]),
        "pct_ma_50": float(f["pct_ma_50"]),
        "pct_ma_200": float(f["pct_ma_200"]),
        "adx_14": float(f["adx_14"]),
        "rsi_14": float(f["rsi_14"]),
        "atr_x_50": float(f["atr_x_50"]),
        "ccqs": float(c["ccqs"]),
        "grade": str(c["grade"]),
        "state": str(s["primary_state"]),
        "state_confidence": float(s["state_confidence"]),
        "leadership_tier": str(l["leadership_tier"]),
        "setup": str(st["setup"]),
        "setup_confidence": float(st["setup_confidence"]),
    }


def main() -> int:
    d = _load_live()
    ref_date = pd.Timestamp(REFERENCE_DATE)
    available_dates = sorted(d["ccqs"].index.get_level_values("date").unique())
    if ref_date not in available_dates:
        print(
            f"  FAIL: reference date {REFERENCE_DATE} not in pipeline output "
            f"(latest is {available_dates[-1]}). Re-run the pipeline or "
            f"regenerate tv_snapshots."
        )
        return 1

    print("=" * 80)
    print(f"TV PARITY  ({REFERENCE_DATE})")
    print("=" * 80)
    print(
        f"{'TICKER':<8}{'FIELD':<20}{'EXPECTED':>14}{'OBSERVED':>14}"
        f"{'DELTA':>10}  STATUS"
    )
    print("-" * 80)

    n_total = 0
    n_failed = 0
    per_ticker_pass: dict[str, bool] = {}
    for ticker, expected in TV_SNAPSHOTS.items():
        try:
            obs = _live_row(d, ticker, ref_date)
        except KeyError:
            print(f"{ticker:<8}{'MISSING':<20}")
            n_failed += 1
            per_ticker_pass[ticker] = False
            continue

        ticker_pass = True
        for field, exp_val in expected.items():
            if field == "date":
                continue
            n_total += 1
            if field in EXACT_FIELDS:
                ok = (str(obs[field]) == str(exp_val))
                delta_str = ""
            else:
                tol = TOLERANCES.get(field, 1.0)
                ok = abs(float(obs[field]) - float(exp_val)) <= tol
                delta_str = f"{float(obs[field]) - float(exp_val):+.2f}"

            if not ok:
                n_failed += 1
                ticker_pass = False
            status = "PASS" if ok else "FAIL"
            print(
                f"{ticker:<8}{field:<20}{str(exp_val):>14}{str(obs[field]):>14}"
                f"{delta_str:>10}  {status}"
            )
        per_ticker_pass[ticker] = ticker_pass

    print("-" * 80)
    print(f"Field checks   : {n_total - n_failed}/{n_total} passed")
    print(
        f"Tickers passing: "
        f"{sum(per_ticker_pass.values())}/{len(per_ticker_pass)}"
    )
    print("=" * 80)
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
