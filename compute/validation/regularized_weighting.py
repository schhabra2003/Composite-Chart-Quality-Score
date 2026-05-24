"""
CCQS V1 — Regularized Component Weighting (Phase X.3, M1)

Replaces hand-set component weights with weights learned from data via
ridge regression with rolling-window cross-validation.

For each rolling window in [252d train / 21d test / 21d step]:

    Training period
    ---------------
    X_train = component_scores[train_dates]        # 10 components × n_train
    y_train = forward_126d_returns[train_dates]    # primary horizon
    y_train standardized cross-sectionally per date

    Fit RidgeCV with alphas = [0.01, 0.1, 1.0, 10.0, 100.0]
    Normalize learned coefficients to sum to 1.0 (sign-preserving)

    Test period
    -----------
    X_test = component_scores[test_dates]
    ccqs_predicted = X_test @ learned_weights
    OOS IC at h ∈ HORIZONS = mean cross-sectional Spearman(predicted, fwd_h)

Outputs
-------
    data/cache/regularized_weights.parquet
        Per-window: window_idx, alpha, train_start..test_end, w_<component>
    data/cache/regularized_weights_summary.json
        Consensus mean & std of weights, OOS IC at each horizon,
        comparison to Phase X.3 (M8) hand-set baseline

Run:
    python -m compute.validation.regularized_weighting
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from scipy.stats import spearmanr
from sklearn.linear_model import RidgeCV

from compute.loader import CACHE_DIR, LOG_DIR
from compute.components import COMPONENT_COLS

COMPONENTS_PATH = CACHE_DIR / "components.parquet"
OHLCV_PATH = CACHE_DIR / "ohlcv_daily.parquet"
OOS_SUMMARY_PATH = CACHE_DIR / "oos_ic_summary.json"

REG_WEIGHTS_PATH = CACHE_DIR / "regularized_weights.parquet"
REG_SUMMARY_PATH = CACHE_DIR / "regularized_weights_summary.json"

HORIZONS = [1, 5, 20, 60, 126, 252]
PRIMARY_HORIZON = 126  # used to fit the model
TRAIN_WINDOW = 252
TEST_WINDOW = 21
STEP = 21
MIN_TRAIN_OBS = 1_000     # require at least this many (ticker, date) rows in train
MIN_WINDOW_DATES = 5      # min valid date-ICs to keep a window
RIDGE_ALPHAS = (0.01, 0.1, 1.0, 10.0, 100.0)

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO", format="<level>{level: <8}</level> | {message}")
logger.add(LOG_DIR / "ccqs.log", level="DEBUG", rotation="10 MB", retention="30 days")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _forward_returns(ohlcv: pd.DataFrame, horizon: int) -> pd.Series:
    df = ohlcv[["ticker", "date", "adj_close"]].sort_values(["ticker", "date"]).copy()
    df["adj_close"] = df["adj_close"].astype(float)
    df["adj_fwd"] = df.groupby("ticker", sort=False)["adj_close"].shift(-horizon)
    df["fwd_ret"] = df["adj_fwd"] / df["adj_close"] - 1.0
    return df.set_index(["ticker", "date"])["fwd_ret"].rename(f"fwd_ret_{horizon}d")


def _cs_zscore_per_date(s: pd.Series) -> pd.Series:
    """Cross-sectional z-score per date (zero-mean, unit-var per date)."""
    g = s.groupby(level="date", sort=False)
    mu = g.transform("mean")
    sd = g.transform("std").replace(0.0, np.nan)
    return ((s - mu) / sd).fillna(0.0)


def _spearman_per_date(s_score: pd.Series, s_fwd: pd.Series) -> pd.Series:
    df = pd.concat([s_score.rename("c"), s_fwd.rename("f")], axis=1).dropna()
    if df.empty:
        return pd.Series(dtype=float)

    def _rho(g: pd.DataFrame) -> float:
        if len(g) < 20:
            return np.nan
        rho, _ = spearmanr(g["c"], g["f"])
        return float(rho) if rho == rho else np.nan

    return df.groupby(level="date", sort=True).apply(_rho)


def _rolling_windows(dates: list[pd.Timestamp]) -> list[dict]:
    n = len(dates)
    out = []
    k = 0
    while True:
        train_lo = k * STEP
        train_hi = train_lo + TRAIN_WINDOW
        test_lo = train_hi
        test_hi = test_lo + TEST_WINDOW
        if test_hi > n:
            break
        out.append({
            "window_idx": k,
            "train_start": dates[train_lo],
            "train_end": dates[train_hi - 1],
            "test_start": dates[test_lo],
            "test_end": dates[test_hi - 1],
        })
        k += 1
    return out


def _normalize_weights(coef: np.ndarray) -> np.ndarray:
    """Normalize to sum = 1.0. Falls back to equal-weight if sum is ~0."""
    total = float(coef.sum())
    if abs(total) < 1e-9:
        return np.full_like(coef, 1.0 / len(coef))
    return coef / total


# ---------------------------------------------------------------------------
# Per-window fit + OOS evaluation
# ---------------------------------------------------------------------------

def _fit_and_score(
    components: pd.DataFrame,
    fwd_primary_z: pd.Series,
    fwd_by_h: dict[int, pd.Series],
    window: dict,
) -> dict | None:
    """Fit RidgeCV on the train slice, then evaluate predictions OOS on test slice."""
    train_mask = (components.index.get_level_values("date") >= window["train_start"]) & \
                 (components.index.get_level_values("date") <= window["train_end"])
    test_mask = (components.index.get_level_values("date") >= window["test_start"]) & \
                (components.index.get_level_values("date") <= window["test_end"])

    X_train = components.loc[train_mask]
    y_train = fwd_primary_z.reindex(X_train.index)
    valid = X_train.notna().all(axis=1) & y_train.notna()
    X_train = X_train.loc[valid]
    y_train = y_train.loc[valid]

    if len(X_train) < MIN_TRAIN_OBS:
        return None

    model = RidgeCV(alphas=list(RIDGE_ALPHAS))
    model.fit(X_train.to_numpy(dtype=float), y_train.to_numpy(dtype=float))
    coef = np.asarray(model.coef_, dtype=float)
    alpha = float(model.alpha_)
    weights = _normalize_weights(coef)

    # Apply to test slice → predicted composite per (ticker, date).
    X_test = components.loc[test_mask]
    valid_test = X_test.notna().all(axis=1)
    X_test = X_test.loc[valid_test]
    if X_test.empty:
        return None

    pred = pd.Series(
        X_test.to_numpy(dtype=float) @ weights,
        index=X_test.index,
        name="ccqs_pred",
    )

    # OOS IC at each horizon over the test slice (mean of per-date Spearman).
    ic_by_h: dict[int, float] = {}
    for h, fwd in fwd_by_h.items():
        fwd_test = fwd.reindex(pred.index)
        ic = _spearman_per_date(pred, fwd_test)
        ic_by_h[h] = float(ic.mean()) if not ic.empty else float("nan")

    row = {
        "window_idx": window["window_idx"],
        "train_start": window["train_start"],
        "train_end": window["train_end"],
        "test_start": window["test_start"],
        "test_end": window["test_end"],
        "alpha": alpha,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
    }
    for c, w in zip(COMPONENT_COLS, weights):
        row[f"w_{c}"] = float(w)
    for h, ic in ic_by_h.items():
        row[f"oos_ic_{h}d"] = ic
    return row


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run() -> tuple[pd.DataFrame, dict]:
    if not (COMPONENTS_PATH.exists() and OHLCV_PATH.exists()):
        raise RuntimeError("Missing inputs — run the main pipeline first.")

    components = pd.read_parquet(COMPONENTS_PATH)
    ohlcv = pd.read_parquet(OHLCV_PATH)
    logger.info(f"Loaded components {components.shape}, ohlcv {ohlcv.shape}")

    components = components[COMPONENT_COLS].astype(float)

    fwd_by_h: dict[int, pd.Series] = {h: _forward_returns(ohlcv, h) for h in HORIZONS}
    fwd_primary_z = _cs_zscore_per_date(fwd_by_h[PRIMARY_HORIZON])

    dates = sorted(components.index.get_level_values("date").unique().tolist())
    windows = _rolling_windows(dates)
    logger.info(f"Rolling windows: {len(windows)}  (train=252d / test=21d / step=21d)")

    rows: list[dict] = []
    for i, w in enumerate(windows):
        if i % 10 == 0:
            logger.info(f"  window {i}/{len(windows)} — train {w['train_start'].date()} → {w['train_end'].date()}")
        out = _fit_and_score(components, fwd_primary_z, fwd_by_h, w)
        if out is not None:
            rows.append(out)

    diag = pd.DataFrame(rows)
    if diag.empty:
        raise RuntimeError("No windows produced valid fits.")

    # ----- Consensus weights ------------------------------------------------
    w_cols = [f"w_{c}" for c in COMPONENT_COLS]
    mean_weights = diag[w_cols].mean()
    std_weights = diag[w_cols].std()
    abs_mean = mean_weights.abs()

    # ----- OOS IC summary ---------------------------------------------------
    oos_summary: dict[int, dict] = {}
    for h in HORIZONS:
        col = f"oos_ic_{h}d"
        ic = diag[col].dropna()
        if ic.empty:
            continue
        oos_summary[h] = {
            "mean": float(ic.mean()),
            "std": float(ic.std(ddof=1)) if len(ic) > 1 else float("nan"),
            "t_stat": float(ic.mean() / (ic.std(ddof=1) / np.sqrt(len(ic)))) if len(ic) > 1 and ic.std(ddof=1) > 0 else float("nan"),
            "n_windows": int(len(ic)),
        }

    # ----- Baseline (M8 hand-set) OOS for comparison -----------------------
    baseline_oos: dict[int, float] = {}
    baseline_t: dict[int, float] = {}
    if OOS_SUMMARY_PATH.exists():
        with open(OOS_SUMMARY_PATH) as f:
            base = json.load(f)
        for r in base.get("rows", []):
            if r.get("score_name") == "CCQS":
                h = r["horizon"]
                baseline_oos[h] = r.get("oos_ic_mean")
                baseline_t[h] = r.get("oos_ic_t_stat")

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_windows": int(len(diag)),
        "train_window": TRAIN_WINDOW,
        "test_window": TEST_WINDOW,
        "step": STEP,
        "primary_horizon": PRIMARY_HORIZON,
        "alphas_tried": list(RIDGE_ALPHAS),
        "alpha_distribution": {
            str(a): int((diag["alpha"] == a).sum()) for a in sorted(diag["alpha"].unique())
        },
        "components": COMPONENT_COLS,
        "mean_weights": {c: float(mean_weights[f"w_{c}"]) for c in COMPONENT_COLS},
        "std_weights": {c: float(std_weights[f"w_{c}"]) for c in COMPONENT_COLS},
        "oos_ic_regularized": oos_summary,
        "oos_ic_baseline_m8": baseline_oos,
        "oos_ic_baseline_m8_tstats": baseline_t,
    }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    diag.to_parquet(REG_WEIGHTS_PATH, compression="snappy")
    logger.info(f"Wrote {REG_WEIGHTS_PATH} ({len(diag)} rows)")
    REG_SUMMARY_PATH.write_text(json.dumps(summary, indent=2, default=str))
    logger.info(f"Wrote {REG_SUMMARY_PATH}")

    return diag, summary


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _print_report(diag: pd.DataFrame, summary: dict, m8_weights: dict[str, float]) -> None:
    print("=" * 84)
    print("PHASE X.3 — M1 REGULARIZED COMPONENT WEIGHTING REPORT")
    print("=" * 84)
    print(
        f"Windows: {summary['n_windows']}  |  "
        f"Train {summary['train_window']}d / Test {summary['test_window']}d / Step {summary['step']}d"
    )
    print(f"Primary fit horizon: {summary['primary_horizon']}d  (forward return z-scored cross-sectionally per date)")
    print(f"Ridge alphas tried:  {summary['alphas_tried']}")
    print(f"Alpha distribution:  {summary['alpha_distribution']}")

    # ---- [1] OOS IC comparison --------------------------------------------
    print("\n[1] OOS IC COMPARISON — baseline (M8 hand-set) vs regularized")
    print(f"  {'horizon':>8} {'baseline':>10} {'regularized':>13} {'delta':>10} {'delta %':>10} {'reg t-stat':>11}")
    base = summary["oos_ic_baseline_m8"]
    for h in HORIZONS:
        b = base.get(h) or base.get(str(h))
        r = summary["oos_ic_regularized"].get(h) or summary["oos_ic_regularized"].get(str(h))
        if r is None:
            print(f"  {h:>8}d {'-':>10} {'-':>13}")
            continue
        r_mean = r["mean"]
        r_t = r["t_stat"]
        if b is not None:
            delta = r_mean - b
            pct = (delta / abs(b) * 100) if abs(b) > 1e-9 else float("nan")
            print(f"  {h:>8}d {b:>+10.4f} {r_mean:>+13.4f} {delta:>+10.4f} {pct:>+9.1f}% {r_t:>+11.2f}")
        else:
            print(f"  {h:>8}d {'-':>10} {r_mean:>+13.4f} {'-':>10} {'-':>10} {r_t:>+11.2f}")

    # ---- [2] Mean learned weights vs hand-set -----------------------------
    print("\n[2] LEARNED WEIGHTS (mean across windows)  vs  HAND-SET (Phase X.3 M8, MIXED state)")
    print(f"  {'component':<22} {'hand-set':>10} {'learned':>10} {'delta':>9} {'|learned|':>10}")
    mean_w = summary["mean_weights"]
    sum_abs = sum(abs(v) for v in mean_w.values())
    norm_abs = {c: abs(mean_w[c]) / sum_abs if sum_abs > 0 else 0.0 for c in COMPONENT_COLS}
    for c in COMPONENT_COLS:
        h_w = m8_weights.get(c, 0.0)
        l_w = mean_w[c]
        print(f"  {c:<22} {h_w:>10.4f} {l_w:>10.4f} {l_w - h_w:>+9.4f} {norm_abs[c]:>10.4f}")

    # ---- [3] Weight stability --------------------------------------------
    print("\n[3] WEIGHT STABILITY  (std across windows; lower = more stable)")
    print(f"  {'component':<22} {'mean':>10} {'std':>10} {'std/|mean|':>12}")
    for c in COMPONENT_COLS:
        m = summary["mean_weights"][c]
        s = summary["std_weights"][c]
        ratio = s / abs(m) if abs(m) > 1e-9 else float("nan")
        print(f"  {c:<22} {m:>10.4f} {s:>10.4f} {ratio:>12.2f}")

    # ---- [4] Recommendation -----------------------------------------------
    print("\n[4] DECISION CHECK")
    primary_h = PRIMARY_HORIZON
    short_h = 1
    base = summary["oos_ic_baseline_m8"]
    reg_summary = summary["oos_ic_regularized"]
    def _delta_pct(h):
        b = base.get(h) or base.get(str(h))
        r = reg_summary.get(h) or reg_summary.get(str(h))
        if not b or not r or abs(b) < 1e-9:
            return None
        return (r["mean"] - b) / abs(b) * 100

    pct_primary = _delta_pct(primary_h)
    pct_short = _delta_pct(short_h)
    print(f"  Δ at {primary_h}d (primary): {pct_primary:+.1f}%  threshold +10%" if pct_primary is not None else "  Δ at 126d unavailable")
    print(f"  Δ at {short_h}d           : {pct_short:+.1f}%  threshold +10%" if pct_short is not None else "  Δ at 1d unavailable")

    meets_10pct = (
        pct_primary is not None and pct_short is not None
        and pct_primary >= 10.0 and pct_short >= 10.0
    )
    # Stability check: any component with std > 4× |mean| flag as unstable
    unstable = [
        c for c in COMPONENT_COLS
        if abs(summary["mean_weights"][c]) > 1e-9
        and summary["std_weights"][c] / abs(summary["mean_weights"][c]) > 4.0
    ]
    t_check_ok = (
        (reg_summary.get(primary_h, reg_summary.get(str(primary_h), {})) or {}).get("t_stat", 0)
        >= (summary.get("oos_ic_baseline_m8_tstats", {}).get(primary_h)
            or summary.get("oos_ic_baseline_m8_tstats", {}).get(str(primary_h)) or 0)
    )

    print(f"  Unstable components (std/|mean| > 4): {unstable if unstable else 'none'}")
    print(f"  Reg t-stat at 126d ≥ baseline t-stat: {t_check_ok}")

    adopt = meets_10pct and not unstable and t_check_ok
    print()
    if adopt:
        print("  RECOMMENDATION: ADOPT learned weights.")
        print("                  All criteria met (≥+10% at 1d AND 126d, stable weights, t-stat OK).")
    else:
        reasons = []
        if not meets_10pct:
            reasons.append("Δ < +10% at 1d or 126d")
        if unstable:
            reasons.append(f"unstable weights for {unstable}")
        if not t_check_ok:
            reasons.append("t-stat at 126d below baseline")
        print("  RECOMMENDATION: KEEP Phase X.3 (M8) hand-set weights.")
        print(f"                  Reasons: {'; '.join(reasons)}")
    print("=" * 84)


def main() -> int:
    t0 = time.time()
    diag, summary = run()

    # Pull M8 MIXED-state weights for the comparison table.
    from compute.ccqs import STATE_WEIGHTS
    m8_mixed = STATE_WEIGHTS["MIXED"]

    _print_report(diag, summary, m8_mixed)
    logger.info(f"Total elapsed: {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
