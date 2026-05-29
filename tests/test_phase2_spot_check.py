"""Phase 2 spot-check: verify features.parquet shape and NVDA latest values."""
import pandas as pd
import numpy as np

# Load
features = pd.read_parquet('data/cache/features.parquet')

# Spot check NVDA latest features
nvda = features.xs('NVDA', level='ticker').iloc[-1]
print('NVDA latest features:')
print(f'  RSI(14):              {nvda["rsi_14"]:.2f}      (expected: 0-100)')
print(f'  MACD posture:         {nvda["macd_posture"]!s:>8s}')
print(f'  ADR pct 20:           {nvda["adr_pct_20"]:.2f}%')
print(f'  ADX(14):              {nvda["adx_14"]:.2f}      (expected: 0-100)')
print(f'  SMA50:                {nvda["sma_50"]:.2f}')
print(f'  SMA200:               {nvda["sma_200"]:.2f}')
print(f'  RS Rating SPY:        {nvda["rs_rating_spy"]:.2f}    (expected: 1-99, continuous)')
print(f'  RS Line SPY slope60d: {nvda["rs_line_spy_slope_60d"]:.2f}%')
print(f'  RS Line QQQ slope60d: {nvda["rs_line_qqq_slope_60d"]:.2f}%  (context-only)')
# Phase 29: macd_line / atr_14 / rs_line_qqq_slope_20d removed from
# FEATURE_ORDER (zero downstream consumers). Substituted with consumed
# features (macd_posture, adr_pct_20) above.

# Coverage check
print(f'\nTotal tickers with features: {features.index.get_level_values("ticker").nunique()}')
print(f'Total feature columns: {len(features.columns)}')
print(f'Date range: {features.index.get_level_values("date").min()} to {features.index.get_level_values("date").max()}')

# Sanity checks
print('\nSanity checks (non-NaN only):')
print(f'  RSI in [0,100]:           {features["rsi_14"].dropna().between(0, 100).all()}')
print(f'  ADX in [0,100]:           {features["adx_14"].dropna().between(0, 100).all()}')
print(f'  RS Rating SPY in [1,99]:  {features["rs_rating_spy"].dropna().between(1, 99).all()}')
print(f'  No infinite values:       {not np.isinf(features.select_dtypes(include=np.number)).any().any()}')
print(f'  Pct NaN per feature (avg): {features.isna().mean().mean()*100:.2f}%')
