"""
Market Structure Extraction Layer — Spatial State Module (Phase 1)

Extracts Fair Value Gaps (FVGs), Order Blocks (OBs), and structural events
(BoS, CHoCH) from price action into DataFrame columns following the
Universal Zone Contract.

Universal Zone Contract (Base):
  {prefix}_active:     bool     — True while zone exists and is unmitigated
  {prefix}_upper:      float64  — Upper boundary price
  {prefix}_lower:      float64  — Lower boundary price
  {prefix}_created_at: datetime — Candle open_time when zone was formed

Extension columns per zone type:
  FVG:  {prefix}_volume — impulse candle volume
  OB:   {prefix}_volume, {prefix}_direction

CRITICAL DESIGN CHOICES:
  - Chronological Left-to-Right Processing: no future data access
  - Lookahead Bias Prevention: active flag shifted by +1
  - Multi-Zone V2 Contract: tracks up to 5 simultaneous zones
  - S/R zones do NOT use the kill-switch pattern (handled in sr_engine.py)
"""

import warnings
import numpy as np
import pandas as pd
from typing import Optional

from app.core.indicators import compute_atr
from app.strategies.archive.smc_v1.fractals import detect_swing_points_df, build_swing_list, determine_trend_from_swings

# Suppress harmless pandas FutureWarnings from forward-fill / NaT column init
# These fire heavily during live-tick FVG/OB extraction (EMA Cross Alert strategy)
warnings.filterwarnings('ignore', category=FutureWarning,
                        message='.*incompatible dtype.*')
warnings.filterwarnings('ignore', category=FutureWarning,
                        message='.*Downcasting object dtype.*')

MAX_ZONES = 5  # Max simultaneous FVGs/OBs tracked


# ── FVG Extraction ──

def extract_fvgs(
    df: pd.DataFrame,
    mitigation_type: str = 'wick',
    lookback: int = 50,
    max_zones: int = MAX_ZONES,
) -> pd.DataFrame:
    """
    Extract Fair Value Gaps from price action. V2: Multi-zone tracking.

    Uses a left-to-right single-pass state machine. No future data is accessed.

    Tracks up to max_zones simultaneous FVGs. Each zone has its own
    lifecycle (birth → active → mitigated).

    At each candle:
      1. Pending zones from the prior candle become active (shift+1 bias prevention).
      2. Active zones are checked for mitigation by the current candle.
      3. New FVG formations are detected and queued as pending.
      4. If all zone slots are full, the oldest active zone is dropped.

    Contract columns (backward-compatible):
      fvg_active:   bool — True if ANY zone is active
      fvg_upper:    float64 — upper boundary of NEAREST active zone to close
      fvg_lower:    float64 — lower boundary of NEAREST active zone to close
      fvg_volume:   float64 — volume of the nearest zone's impulse candle
      fvg_zone_count: int — number of active zones
      fvg_{N}_{col}: per-zone columns for individual zone inspection

    Args:
        df: DataFrame with [open, high, low, close, volume, open_time]
        mitigation_type: 'wick' (default) or 'body'
        lookback: How many candles to scan backward
        max_zones: How many simultaneous zones to track (default 5)
    """
    df = df.copy()
    n = len(df)

    # Initialize aggregate columns
    df['fvg_active'] = False
    df['fvg_upper'] = np.nan
    df['fvg_lower'] = np.nan
    df['fvg_volume'] = np.nan
    df['fvg_created_at'] = pd.NaT
    df['fvg_zone_count'] = 0

    # Initialize per-zone columns
    for zi in range(max_zones):
        prefix = f'fvg_{zi}_'
        df[f'{prefix}active'] = False
        df[f'{prefix}upper'] = np.nan
        df[f'{prefix}lower'] = np.nan
        df[f'{prefix}volume'] = np.nan
        df[f'{prefix}created_at'] = pd.NaT

    if n < 3:
        return df

    # Pre-extract numpy arrays for speed
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values

    scan_start = max(0, n - lookback)

    # State: list of active zones, each is a dict with slot, upper, lower, volume, created_at, direction
    active_zones = []  # ordered oldest-first
    # Zones formed this candle, become active next candle
    pending_zones = []

    for i in range(scan_start, n):
        # Step 1: Promote pending zones to active
        for pz in pending_zones:
            # Find an available slot
            used_slots = {z['slot'] for z in active_zones}
            slot = None
            for s in range(max_zones):
                if s not in used_slots:
                    slot = s
                    break
            if slot is None:
                # All slots full — drop the oldest active zone
                active_zones.pop(0)
                used_slots = {z['slot'] for z in active_zones}
                for s in range(max_zones):
                    if s not in used_slots:
                        slot = s
                        break
            pz['slot'] = slot
            active_zones.append(pz)
        pending_zones = []

        # Step 2: Check mitigation of active zones by current candle
        surviving = []
        for z in active_zones:
            mitigated = False
            if mitigation_type == 'wick':
                if z['direction'] == 'bullish' and lows[i] <= z['lower']:
                    mitigated = True
                elif z['direction'] == 'bearish' and highs[i] >= z['upper']:
                    mitigated = True
            else:  # body
                if z['direction'] == 'bullish' and closes[i] <= z['lower']:
                    mitigated = True
                elif z['direction'] == 'bearish' and closes[i] >= z['upper']:
                    mitigated = True

            if not mitigated:
                surviving.append(z)
        active_zones = surviving

        # Step 3: Write current state to per-zone columns
        for z in active_zones:
            zi = z['slot']
            prefix = f'fvg_{zi}_'
            df.iloc[i, df.columns.get_loc(f'{prefix}active')] = True
            df.iloc[i, df.columns.get_loc(f'{prefix}upper')] = z['upper']
            df.iloc[i, df.columns.get_loc(f'{prefix}lower')] = z['lower']
            df.iloc[i, df.columns.get_loc(f'{prefix}volume')] = z['volume']
            df.iloc[i, df.columns.get_loc(f'{prefix}created_at')] = z['created_at']

        # Step 4: Write aggregate columns
        if active_zones:
            df.iloc[i, df.columns.get_loc('fvg_zone_count')] = len(active_zones)
            # Pick nearest zone to current close
            nearest = min(active_zones, key=lambda z: abs(closes[i] - (z['upper'] + z['lower']) / 2))
            df.iloc[i, df.columns.get_loc('fvg_active')] = True
            df.iloc[i, df.columns.get_loc('fvg_upper')] = nearest['upper']
            df.iloc[i, df.columns.get_loc('fvg_lower')] = nearest['lower']
            df.iloc[i, df.columns.get_loc('fvg_volume')] = nearest['volume']
            df.iloc[i, df.columns.get_loc('fvg_created_at')] = nearest['created_at']

        # Step 5: Detect new FVG formation at candle i (using i-2, i-1, i)
        if i >= scan_start + 2:
            upper_val = None
            lower_val = None
            direction = None

            if lows[i] > highs[i - 2]:
                # Bullish FVG: gap between C1.high and C3.low
                upper_val, lower_val, direction = lows[i], highs[i - 2], 'bullish'
            elif highs[i] < lows[i - 2]:
                # Bearish FVG: gap between C1.low and C3.high
                upper_val, lower_val, direction = lows[i - 2], highs[i], 'bearish'

            if upper_val is not None:
                pending_zones.append({
                    'slot': None,  # assigned when promoted
                    'upper': upper_val,
                    'lower': lower_val,
                    'volume': df.iloc[i - 1]['volume'],
                    'created_at': df.iloc[i]['open_time'],
                    'direction': direction,
                })

    return df


# ── Order Block Extraction ──

def extract_order_blocks(
    df: pd.DataFrame,
    impulse_min: int = 2,
    impulse_max: int = 5,
    atr_displacement: float = 1.5,
    pivot_bars: int = 3,
) -> pd.DataFrame:
    """
    Extract Institutional Order Blocks from price action.

    Uses a left-to-right scan. No future data is accessed.

    A bullish OB is the last bearish candle before a significant bullish impulse.
    A bearish OB is the last bullish candle before a significant bearish impulse.

    Requirements:
      - Variable-length impulse (impulse_min to impulse_max consecutive candles)
      - ATR-normalized displacement >= atr_displacement
      - Break of Structure (impulse exceeds prior swing)

    Tracks the MOST RECENTLY FORMED unmitigated OB (V1 contract).
    Mitigation: body-close beyond the block boundary (institutional logic).
      Bullish OB mitigated when close < ob_lower
      Bearish OB mitigated when close > ob_upper

    Args:
        df: DataFrame with [open, high, low, close, volume, open_time]
        impulse_min: Minimum consecutive impulse candles
        impulse_max: Maximum consecutive impulse candles
        atr_displacement: Minimum ATR multiplier for impulse displacement
        pivot_bars: Bars for swing detection (BOS validation)

    Returns:
        DataFrame with added columns:
            ob_active:      bool
            ob_upper:       float64
            ob_lower:       float64
            ob_volume:      float64 — OB candle volume
            ob_direction:   str — 'bullish' or 'bearish'
            ob_created_at:  datetime64
    """
    df = df.copy()
    n = len(df)

    # Initialize columns
    df['ob_active'] = False
    df['ob_upper'] = np.nan
    df['ob_lower'] = np.nan
    df['ob_volume'] = np.nan
    df['ob_direction'] = None
    df['ob_created_at'] = pd.NaT

    if n < impulse_min + 2:
        return df

    # Compute ATR for displacement check
    atr_series = compute_atr(df['high'], df['low'], df['close'], 14)

    # Detect swing points for BOS validation
    df = detect_swing_points_df(df, pivot_bars)

    # Pre-extract arrays
    opens = df['open'].values
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values

    # State: the currently active OB (or None)
    active_ob = None
    # Pending OB: formed this candle, becomes active next candle
    pending_ob = None

    for i in range(n):
        # Step 1: Promote pending OB to active (shift+1 bias prevention)
        if pending_ob is not None:
            active_ob = pending_ob
            pending_ob = None

        # Step 2: Check mitigation of active OB
        if active_ob is not None:
            mitigated = False
            if active_ob['direction'] == 'bullish':
                if closes[i] < active_ob['lower']:
                    mitigated = True
            else:
                if closes[i] > active_ob['upper']:
                    mitigated = True
            if mitigated:
                active_ob = None

        # Step 3: Write current state
        if active_ob is not None:
            df.iloc[i, df.columns.get_loc('ob_active')] = True
            df.iloc[i, df.columns.get_loc('ob_upper')] = active_ob['upper']
            df.iloc[i, df.columns.get_loc('ob_lower')] = active_ob['lower']
            df.iloc[i, df.columns.get_loc('ob_volume')] = active_ob['volume']
            df.iloc[i, df.columns.get_loc('ob_direction')] = active_ob['direction']
            df.iloc[i, df.columns.get_loc('ob_created_at')] = active_ob['created_at']

        # Step 4: Try to detect a new OB formation ending at candle i
        # The OB candle is at some index `ob_idx`, followed by impulse candles
        # ending at `i`. We scan backward from `i` to find the impulse.
        if i < impulse_min:
            continue

        atr_val = atr_series.iloc[i]
        if pd.isna(atr_val) or atr_val <= 0:
            continue

        # Try bullish OB: bearish OB candle followed by bullish impulse ending at i
        for impulse_len in range(impulse_min, min(impulse_max, i) + 1):
            ob_idx = i - impulse_len
            if ob_idx < 0:
                break

            ob_open = opens[ob_idx]
            ob_close = closes[ob_idx]

            # OB candle must be bearish for a bullish OB
            if ob_close >= ob_open:
                continue

            # Check all candles from ob_idx+1 to i are bullish
            all_bullish = True
            for j in range(ob_idx + 1, i + 1):
                if closes[j] <= opens[j]:
                    all_bullish = False
                    break
            if not all_bullish:
                continue

            # ATR displacement check
            impulse_size = closes[i] - opens[ob_idx + 1]
            if impulse_size < atr_val * atr_displacement:
                continue

            # BOS validation: impulse must break prior swing high
            if not _has_bos(df, ob_idx, i, 'bullish'):
                continue

            # Valid bullish OB found — queue as pending
            pending_ob = {
                'upper': highs[ob_idx],
                'lower': lows[ob_idx],
                'volume': df.iloc[ob_idx]['volume'],
                'created_at': df.iloc[ob_idx]['open_time'],
                'direction': 'bullish',
            }
            break  # Take the first valid impulse length

        # Try bearish OB: bullish OB candle followed by bearish impulse ending at i
        if pending_ob is None:
            for impulse_len in range(impulse_min, min(impulse_max, i) + 1):
                ob_idx = i - impulse_len
                if ob_idx < 0:
                    break

                ob_open = opens[ob_idx]
                ob_close = closes[ob_idx]

                # OB candle must be bullish for a bearish OB
                if ob_close <= ob_open:
                    continue

                # Check all candles from ob_idx+1 to i are bearish
                all_bearish = True
                for j in range(ob_idx + 1, i + 1):
                    if closes[j] >= opens[j]:
                        all_bearish = False
                        break
                if not all_bearish:
                    continue

                # ATR displacement check
                impulse_size = opens[ob_idx + 1] - closes[i]
                if impulse_size < atr_val * atr_displacement:
                    continue

                # BOS validation
                if not _has_bos(df, ob_idx, i, 'bearish'):
                    continue

                pending_ob = {
                    'upper': highs[ob_idx],
                    'lower': lows[ob_idx],
                    'volume': df.iloc[ob_idx]['volume'],
                    'created_at': df.iloc[ob_idx]['open_time'],
                    'direction': 'bearish',
                }
                break

    return df


def _has_bos(df: pd.DataFrame, ob_idx: int, impulse_end_idx: int, direction: str) -> bool:
    """
    Verify Break of Structure: the impulse breaks the prior swing point.

    Only uses swing points that are confirmed (their index < ob_idx),
    preventing lookahead from pivot confirmation delay.

    If no prior swing points are found (insufficient data), falls back to
    checking against the max/min of all prior candles.
    """
    prior_swing_highs = df.loc[:ob_idx - 1, 'swing_high_price'].dropna()
    prior_swing_lows = df.loc[:ob_idx - 1, 'swing_low_price'].dropna()

    impulse_highs = df.loc[ob_idx + 1:impulse_end_idx, 'high']
    impulse_lows = df.loc[ob_idx + 1:impulse_end_idx, 'low']

    if direction == 'bullish':
        if prior_swing_highs.empty:
            # Fallback: compare against prior candle range
            prior_all_highs = df.loc[:ob_idx - 1, 'high']
            if prior_all_highs.empty or impulse_highs.empty:
                return True  # Not enough data to refute — accept
            return impulse_highs.max() > prior_all_highs.max()
        return impulse_highs.max() > prior_swing_highs.max()
    else:
        if prior_swing_lows.empty:
            prior_all_lows = df.loc[:ob_idx - 1, 'low']
            if prior_all_lows.empty or impulse_lows.empty:
                return True
            return impulse_lows.min() < prior_all_lows.min()
        return impulse_lows.min() < prior_swing_lows.min()


# ── Market Structure Events: BoS & CHoCH ──

def extract_market_structure_events(
    df: pd.DataFrame,
    pivot_bars: int = 3,
) -> pd.DataFrame:
    """
    Detect Break of Structure (BoS) and Change of Character (CHoCH) events
    and track the running structural trend bias.

    Uses confirmed swing points only (a swing at index j is confirmed at
    index j + pivot_bars). Body close is required for both BoS and CHoCH.

    Definitions:
      - BoS (Break of Structure): Trend continuation.
        Bullish BoS: price body-closes above the last confirmed swing high
                     while the structural trend is already bullish.
        Bearish BoS: price body-closes below the last confirmed swing low
                     while the structural trend is already bearish.

      - CHoCH (Change of Character): Trend reversal.
        Bullish CHoCH: price body-closes above the last confirmed swing high
                       while the structural trend was bearish (flips to bullish).
        Bearish CHoCH: price body-closes below the last confirmed swing low
                       while the structural trend was bullish (flips to bearish).

    Args:
        df: DataFrame with [open, high, low, close]
        pivot_bars: Bars on each side for swing point detection

    Returns:
        DataFrame with added columns:
            struct_event:  str — 'BOS_UP', 'BOS_DOWN', 'CHOCH_UP', 'CHOCH_DOWN', or None
            struct_trend:  int — 1 (bullish), -1 (bearish), 0 (neutral/undetermined)
    """
    df = df.copy()
    n = len(df)

    df['struct_event'] = None
    df['struct_trend'] = 0

    if n < pivot_bars * 2 + 4:
        return df

    # Pre-extract arrays
    highs = df['high'].values
    lows = df['low'].values
    opens = df['open'].values
    closes = df['close'].values

    # State tracking
    struct_trend = 0  # 0=neutral, 1=bullish, -1=bearish
    last_confirmed_swing_high = None  # {'price': float, 'index': int}
    last_confirmed_swing_low = None

    # Pre-compute swing points using the existing fractal detector
    df_swings = detect_swing_points_df(df, pivot_bars)
    swing_high_mask = df_swings['swing_high'].values
    swing_high_prices = df_swings['swing_high_price'].values
    swing_low_mask = df_swings['swing_low'].values
    swing_low_prices = df_swings['swing_low_price'].values

    for i in range(n):
        # Step 1: Check if any swing point has become confirmed
        # A swing at index j is confirmed when we reach index j + pivot_bars
        confirmed_idx = i - pivot_bars
        if confirmed_idx >= 0:
            if swing_high_mask[confirmed_idx]:
                last_confirmed_swing_high = {
                    'price': swing_high_prices[confirmed_idx],
                    'index': confirmed_idx,
                }
            if swing_low_mask[confirmed_idx]:
                last_confirmed_swing_low = {
                    'price': swing_low_prices[confirmed_idx],
                    'index': confirmed_idx,
                }

        # Step 2: Check for structural breaks using body close
        if last_confirmed_swing_high is None or last_confirmed_swing_low is None:
            df.iloc[i, df.columns.get_loc('struct_trend')] = struct_trend
            continue

        body_high = max(opens[i], closes[i])
        body_low = min(opens[i], closes[i])

        event = None

        # Check for break above the last confirmed swing high
        if body_high > last_confirmed_swing_high['price']:
            if struct_trend == 1 or struct_trend == 0:
                event = 'BOS_UP'
                struct_trend = 1
            elif struct_trend == -1:
                event = 'CHOCH_UP'
                struct_trend = 1
            # After breaking the swing high, reset it so the same level
            # isn't triggered repeatedly
            last_confirmed_swing_high = None

        # Check for break below the last confirmed swing low
        if body_low < last_confirmed_swing_low['price']:
            if struct_trend == -1 or struct_trend == 0:
                event = 'BOS_DOWN'
                struct_trend = -1
            elif struct_trend == 1:
                event = 'CHOCH_DOWN'
                struct_trend = -1
            last_confirmed_swing_low = None

        if event is not None:
            df.iloc[i, df.columns.get_loc('struct_event')] = event

        df.iloc[i, df.columns.get_loc('struct_trend')] = struct_trend

    return df
