"""
Market Regime Detection Module

Determines the current market state (trending/ranging, volatility regime, structural bias)
and adds regime columns to DataFrames so strategies can gate themselves by market context.

Regime definitions:
  - TRENDING_UP:   ADX >= 25, EMAs stacked bullishly, HH + HL structure
  - TRENDING_DOWN: ADX >= 25, EMAs stacked bearishly, LH + LL structure
  - RANGING:       ADX < 20 or no clear structure
  - CHOPPY:        ADX 20-25, mixed signals

Regime hysteresis:
  Once a trend is confirmed, it persists until a stronger exit condition fires
  (price crosses EMA 100 or ADX drops below 15). This prevents pullbacks to
  the 50 EMA from falsely dropping the regime to CHOPPY.

Volatility regime (percentile-based):
  - LOW:     BB width below 20th percentile of last 100 bars
  - NORMAL:  BB width between 20th and 80th percentile
  - HIGH:    BB width above 80th percentile of last 100 bars
"""

import numpy as np
import pandas as pd


def detect_market_regime(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add market regime columns to the DataFrame.

    Required columns: close, high, low, ema_50, ema_100, ema_200, adx, bb_width
    (All must be computed beforehand via pre_process)

    Adds:
      regime:           str — 'TRENDING_UP', 'TRENDING_DOWN', 'RANGING', 'CHOPPY'
      regime_strength:  float — 0.0 to 1.0, how strong the regime signal is
      volatility_regime: str — 'LOW', 'NORMAL', 'HIGH'
      structural_bias:  str — 'BULLISH', 'BEARISH', 'NEUTRAL'
    """
    df = df.copy()
    n = len(df)

    df['regime'] = 'RANGING'
    df['regime_strength'] = 0.0
    df['volatility_regime'] = 'NORMAL'
    df['structural_bias'] = 'NEUTRAL'

    if n < 30:
        return df

    # ── ADX-based trend strength ──
    adx_ok = df['adx'].notna() & (df['adx'] >= 20)
    strong_trend = df['adx'].notna() & (df['adx'] >= 25)

    # ── EMA stack alignment ──
    emas_ok = (
        df['ema_50'].notna() & df['ema_100'].notna() & df['ema_200'].notna()
    )
    bullish_stack = emas_ok & (df['ema_50'] > df['ema_100']) & (df['ema_100'] > df['ema_200'])
    bearish_stack = emas_ok & (df['ema_50'] < df['ema_100']) & (df['ema_100'] < df['ema_200'])

    # ── Price vs EMAs ──
    price_above_50 = df['close'] > df['ema_50']
    price_below_50 = df['close'] < df['ema_50']
    price_above_100 = df['close'] > df['ema_100']
    price_below_100 = df['close'] < df['ema_100']

    # ── Classify regime with hysteresis ──
    # Use a state machine: once a trend is confirmed, it persists until
    # a strong exit condition fires, not just a pullback to EMA 50.
    regimes = np.full(n, 'RANGING', dtype=object)
    prev_regime = 'RANGING'

    for i in range(n):
        if not emas_ok.iloc[i]:
            regimes[i] = prev_regime if prev_regime != 'RANGING' else 'RANGING'
            continue

        is_strong = strong_trend.iloc[i] if adx_ok.iloc[i] else False
        is_adx_ok = adx_ok.iloc[i]
        is_bull_stack = bullish_stack.iloc[i]
        is_bear_stack = bearish_stack.iloc[i]
        is_above_50 = price_above_50.iloc[i]
        is_below_50 = price_below_50.iloc[i]
        is_above_100 = price_above_100.iloc[i]
        is_below_100 = price_below_100.iloc[i]

        # ── Entry conditions (strict) ──
        if is_strong and is_bull_stack and is_above_50:
            regimes[i] = 'TRENDING_UP'
        elif is_strong and is_bear_stack and is_below_50:
            regimes[i] = 'TRENDING_DOWN'
        elif is_adx_ok and is_bull_stack and is_above_50:
            regimes[i] = 'TRENDING_UP'
        elif is_adx_ok and is_bear_stack and is_below_50:
            regimes[i] = 'TRENDING_DOWN'

        # ── Hysteresis: maintain trend during pullbacks ──
        elif prev_regime == 'TRENDING_UP' and is_bull_stack and is_above_100:
            # Price pulled back below EMA 50 but is still above EMA 100
            # and ADX hasn't collapsed — maintain the trend
            adx_val = df['adx'].iloc[i]
            if pd.notna(adx_val) and adx_val >= 15:
                regimes[i] = 'TRENDING_UP'
            else:
                regimes[i] = 'CHOPPY'
        elif prev_regime == 'TRENDING_DOWN' and is_bear_stack and is_below_100:
            adx_val = df['adx'].iloc[i]
            if pd.notna(adx_val) and adx_val >= 15:
                regimes[i] = 'TRENDING_DOWN'
            else:
                regimes[i] = 'CHOPPY'

        # ── Choppy: ADX in range but no clear alignment ──
        elif is_adx_ok:
            regimes[i] = 'CHOPPY'
        else:
            regimes[i] = 'RANGING'

        prev_regime = regimes[i]

    df['regime'] = regimes

    # ── Regime strength (0-1) ──
    # Based on ADX normalized + EMA stack conviction
    adx_norm = df['adx'].clip(0, 50) / 50.0  # ADX capped at 50
    df['regime_strength'] = np.where(
        df['regime'].isin(['TRENDING_UP', 'TRENDING_DOWN']),
        (adx_norm * 0.6 + 0.4).clip(0, 1),  # Base 0.4 + ADX contribution
        0.2  # Low strength for ranging/choppy
    )

    # ── Volatility regime (percentile-based) ──
    vol_lookback = 100
    if 'bb_width' in df.columns and df['bb_width'].notna().sum() >= 20:
        vol_regimes = np.full(n, 'NORMAL', dtype=object)
        bb_vals = df['bb_width'].values

        for i in range(n):
            if pd.isna(bb_vals[i]):
                continue
            # Use the last `vol_lookback` bars (or all available)
            start = max(0, i - vol_lookback + 1)
            window = bb_vals[start:i + 1]
            valid = window[~np.isnan(window)]
            if len(valid) < 20:
                continue

            pct = np.sum(valid < bb_vals[i]) / len(valid)
            if pct >= 0.80:
                vol_regimes[i] = 'HIGH'
            elif pct <= 0.20:
                vol_regimes[i] = 'LOW'
            else:
                vol_regimes[i] = 'NORMAL'

        df['volatility_regime'] = vol_regimes

    # ── Structural bias (from price vs EMAs) ──
    df.loc[bullish_stack & price_above_50, 'structural_bias'] = 'BULLISH'
    df.loc[bearish_stack & price_below_50, 'structural_bias'] = 'BEARISH'

    return df


def is_trending(df: pd.DataFrame, idx: int = -1) -> bool:
    """Check if the current bar is in a trending regime."""
    if 'regime' not in df.columns:
        return False
    regime = df.iloc[idx].get('regime', 'RANGING')
    return regime in ('TRENDING_UP', 'TRENDING_DOWN')


def is_ranging(df: pd.DataFrame, idx: int = -1) -> bool:
    """Check if the current bar is in a ranging regime."""
    if 'regime' not in df.columns:
        return False
    return df.iloc[idx].get('regime', 'RANGING') in ('RANGING', 'CHOPPY')


def get_trend_direction(df: pd.DataFrame, idx: int = -1) -> str:
    """Get the trend direction ('UP', 'DOWN', 'NEUTRAL') for the current bar."""
    if 'regime' not in df.columns:
        return 'NEUTRAL'
    regime = df.iloc[idx].get('regime', 'RANGING')
    if regime == 'TRENDING_UP':
        return 'UP'
    if regime == 'TRENDING_DOWN':
        return 'DOWN'
    return 'NEUTRAL'
