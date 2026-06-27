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


def detect_trend_exhaustion(df: pd.DataFrame, cooldown_bars: int = 6) -> pd.Series:
    """
    Detect when an active trend is showing signs of exhaustion or reversal.

    Checks 5 independent conditions — if 2+ fire simultaneously, the trend
    is considered exhausting and trend-continuation strategies should pause.

    Conditions (mirrored for bull/bear):
      1. RSI recovering: RSI making higher lows while in downtrend
      2. ADX declining:  ADX dropped ≥5 pts from its 10-bar peak
      3. EMA 9 reclaim:  price closed on the wrong side of EMA 9 (2 of 3 bars)
      4. MACD decel:     |MACD histogram| shrinking for 3+ consecutive bars
      5. Volume exhaust: trend-direction candles have below-avg volume

    Cooldown: once triggered, stays True for at least ``cooldown_bars``
    candles so the strategy doesn't whipsaw back in immediately.  When the
    conditions genuinely clear AND the cooldown has elapsed, signals resume.

    Args:
        df: DataFrame with columns: regime, close, open, rsi, adx, ema_9,
            volume, volume_ma.  macd_histogram is used if present.
        cooldown_bars: minimum bars to stay suppressed after triggering.

    Returns:
        pd.Series[bool] aligned to df.index.  True = trend is exhausting.
    """
    n = len(df)
    exhausted = pd.Series(False, index=df.index)

    if n < 30 or 'regime' not in df.columns:
        return exhausted

    regime = df['regime']
    is_down = regime == 'TRENDING_DOWN'
    is_up = regime == 'TRENDING_UP'
    is_trending_mask = is_down | is_up

    # If nothing is trending, nothing to exhaust
    if not is_trending_mask.any():
        return exhausted

    close = df['close']

    # ── Condition 1: RSI momentum recovery ──────────────────────────
    cond1 = pd.Series(False, index=df.index)
    if 'rsi' in df.columns:
        rsi = df['rsi']
        rsi_10_low = rsi.rolling(10).min()
        rsi_30_low = rsi.rolling(30).min()
        price_10_low = close.rolling(10).min()
        price_30_low = close.rolling(30).min()

        rsi_10_high = rsi.rolling(10).max()
        rsi_30_high = rsi.rolling(30).max()
        price_10_high = close.rolling(10).max()
        price_30_high = close.rolling(30).max()

        # Bearish exhaustion: higher lows in both price and RSI (momentum recovering)
        bear_c1 = (is_down
                   & (price_10_low > price_30_low.shift(10))
                   & (rsi_10_low > rsi_30_low.shift(10)))
        # Bullish exhaustion: lower highs in both price and RSI
        bull_c1 = (is_up
                   & (price_10_high < price_30_high.shift(10))
                   & (rsi_10_high < rsi_30_high.shift(10)))
        cond1 = bear_c1.fillna(False) | bull_c1.fillna(False)

    # ── Condition 2: ADX declining from peak ────────────────────────
    cond2 = pd.Series(False, index=df.index)
    if 'adx' in df.columns:
        adx = df['adx']
        adx_peak_10 = adx.rolling(10).max()
        cond2 = is_trending_mask & ((adx_peak_10 - adx) >= 5).fillna(False)

    # ── Condition 3: Price reclaimed EMA 9 against trend ────────────
    cond3 = pd.Series(False, index=df.index)
    if 'ema_9' in df.columns:
        ema9 = df['ema_9']
        above_ema9 = (close > ema9).astype(float)
        below_ema9 = (close < ema9).astype(float)
        # Bearish exhaustion: closed above EMA 9 in ≥2 of last 3 bars
        bear_c3 = is_down & (above_ema9.rolling(3).sum() >= 2)
        # Bullish exhaustion: closed below EMA 9 in ≥2 of last 3 bars
        bull_c3 = is_up & (below_ema9.rolling(3).sum() >= 2)
        cond3 = bear_c3.fillna(False) | bull_c3.fillna(False)

    # ── Condition 4: MACD histogram decelerating ────────────────────
    cond4 = pd.Series(False, index=df.index)
    if 'macd_histogram' in df.columns:
        hist_abs = df['macd_histogram'].abs()
        # 3 consecutive bars of shrinking |histogram|
        shrinking = ((hist_abs < hist_abs.shift(1))
                     & (hist_abs.shift(1) < hist_abs.shift(2))
                     & (hist_abs.shift(2) < hist_abs.shift(3)))
        cond4 = is_trending_mask & shrinking.fillna(False)
    else:
        # Compute MACD on the fly if not present
        from app.core.indicators import compute_macd
        macd_res = compute_macd(close)
        hist_abs = macd_res['macd_histogram'].abs()
        shrinking = ((hist_abs < hist_abs.shift(1))
                     & (hist_abs.shift(1) < hist_abs.shift(2))
                     & (hist_abs.shift(2) < hist_abs.shift(3)))
        cond4 = is_trending_mask & shrinking.fillna(False)

    # ── Condition 5: Trend-direction candles on weak volume ─────────
    cond5 = pd.Series(False, index=df.index)
    if 'volume_ma' in df.columns:
        vol = df['volume']
        vol_ma = df['volume_ma']
        is_bear_candle = close < df['open']
        is_bull_candle = close > df['open']

        # Average volume of bearish candles over a 10-bar window
        bear_vol = vol.where(is_bear_candle, np.nan)
        bull_vol = vol.where(is_bull_candle, np.nan)
        bear_vol_avg = bear_vol.rolling(10, min_periods=3).mean()
        bull_vol_avg = bull_vol.rolling(10, min_periods=3).mean()

        bear_c5 = is_down & bear_vol_avg.notna() & (bear_vol_avg < vol_ma * 0.7)
        bull_c5 = is_up & bull_vol_avg.notna() & (bull_vol_avg < vol_ma * 0.7)
        cond5 = bear_c5.fillna(False) | bull_c5.fillna(False)

    # ── Combine: 2+ conditions → exhausted ──────────────────────────
    score = (cond1.astype(int) + cond2.astype(int) + cond3.astype(int)
             + cond4.astype(int) + cond5.astype(int))
    raw_exhaustion = score >= 2

    # ── Cooldown: once triggered, persist for cooldown_bars ─────────
    # rolling(N).max() looks at the current + previous N-1 bars, so if
    # bar K triggers, bars K through K+N-1 will all see that trigger
    # and remain True.  This gives a natural cooldown.
    if cooldown_bars > 1:
        exhausted = (raw_exhaustion.astype(int)
                     .rolling(cooldown_bars, min_periods=1)
                     .max()
                     .astype(bool))
    else:
        exhausted = raw_exhaustion

    return exhausted
