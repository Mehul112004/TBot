"""
S/R Zone Detection Engine
Detects Support/Resistance zones from candle data using multiple methods:
- Swing high/low detection (configurable lookback, default 12 = structural)
- Round psychological numbers (large grain only by default — sparse)
- Zone merging (0.75 × ATR threshold), strength scoring (post-formation
  touches, touch-gated, recency-decayed) and DB persistence.

Previous day/week H/L is no longer emitted here — that role is filled by the
richer Pivot Points layer (see app.core.pivot_engine).
"""

import threading
import pandas as pd
import numpy as np
import math
from datetime import datetime, timedelta
from app.models.db import db, Candle, SRZone
from app.core.indicator_service import IndicatorService
from app.core.indicators import compute_atr
from app.core.config import SUPPORTED_SYMBOLS


# Timeframe weights for strength scoring
# Higher timeframe zones carry more weight
TIMEFRAME_WEIGHTS = {
    '1w':  0.50,
    '1d':  0.40,
    '12h': 0.35,
    '8h':  0.32,
    '6h':  0.30,
    '4h':  0.28,
    '2h':  0.22,
    '1h':  0.20,
    '30m': 0.15,
    '15m': 0.10,
    '5m':  0.07,
    '3m':  0.05,
    '1m':  0.03,
}

# Round number increments per symbol for psychological levels.
# Only the core supported symbols are listed here — any other symbol falls
# through to the dynamic get_round_grains() helper which derives sensible
# grains from the current price (~1% small, ~5% large), so unknown assets
# still render psychological levels on the chart.
ROUND_NUMBER_CONFIG = {
    'BTCUSDT':  {'small': 1000, 'large': 5000},
    'ETHUSDT':  {'small': 100,  'large': 500},
    'SOLUSDT':  {'small': 10,   'large': 50},
}


def _auto_grain(price: float, pct: float) -> float:
    """
    Snap ``price * pct`` to the nearest "nice" increment (1, 2, 5 × 10^k).
    Used as the fallback when a symbol isn't in ROUND_NUMBER_CONFIG so any
    unknown asset still gets sensible psychological levels instead of a fixed
    grain that may be larger than its price (e.g. $500 grain for a $200 coin).

    Examples:
        _auto_grain(204,    0.05) → 10      (BCH large)
        _auto_grain(204,    0.01) → 2       (BCH small)
        _auto_grain(67000,  0.05) → 5000    (BTC large, matches config)
    """
    if price <= 0:
        return 1.0
    target = max(price * pct, 1e-9)
    # Magnitude is the power of 10 spanning the target (works for sub-1 prices
    # too, e.g. $0.65 → magnitude 0.01).
    magnitude = 10 ** math.floor(math.log10(target))
    normalized = target / magnitude
    if normalized < 1.5:
        nice = 1
    elif normalized < 3.5:
        nice = 2
    else:
        nice = 5
    return nice * magnitude


def get_round_grains(symbol: str, current_price: float) -> dict:
    """
    Return {'small':..., 'large':...} round-number grains for a symbol.
    Uses ROUND_NUMBER_CONFIG when available; otherwise derives grains from the
    current price (~1% small, ~5% large) so unknown symbols still render.
    """
    cfg = ROUND_NUMBER_CONFIG.get(symbol)
    if cfg:
        return cfg
    return {
        'small': _auto_grain(current_price, 0.01),
        'large': _auto_grain(current_price, 0.05),
    }


class SREngine:
    """Detects and manages S/R zones for the platform."""

    # --- Per-symbol refresh locks (FIX-SCH-3) ---
    _refresh_locks: dict[str, threading.Lock] = {}
    _refresh_locks_meta = threading.Lock()

    @classmethod
    def get_refresh_lock(cls, symbol: str) -> threading.Lock:
        """Get or create a per-symbol lock for coordinating zone refresh/read."""
        with cls._refresh_locks_meta:
            if symbol not in cls._refresh_locks:
                cls._refresh_locks[symbol] = threading.Lock()
            return cls._refresh_locks[symbol]

    # ---------- Detection Methods ----------

    @staticmethod
    def detect_swing_points(df: pd.DataFrame, lookback: int = 5) -> list[dict]:
        """
        Detect swing highs and swing lows from candle data.

        A swing high: candle high is the highest high in a window of ±lookback candles.
        A swing low: candle low is the lowest low in a window of ±lookback candles.

        Args:
            df: DataFrame with columns ['open_time', 'high', 'low', 'close']
            lookback: Number of candles on each side to check (default 5)

        Returns:
            List of zone dicts with keys: price_level, zone_type, detection_method, timestamp
        """
        zones = []
        highs = df['high'].values
        lows = df['low'].values
        times = df['open_time'].values

        for i in range(lookback, len(df) - lookback):
            # Check for swing high — only flag the first occurrence of the max (FIX-SR-8)
            window_highs = highs[i - lookback: i + lookback + 1]
            max_val = window_highs.max()
            if highs[i] == max_val and np.argmax(window_highs) == lookback:
                zones.append({
                    'price_level': float(highs[i]),
                    'zone_type': 'resistance',
                    'detection_method': 'swing',
                    'timestamp': pd.Timestamp(times[i]).to_pydatetime().replace(tzinfo=None),
                    '_formation_idx': i,  # consumed by score_zone, not persisted (FIX-SR-4)
                })

            # Check for swing low — only flag the first occurrence of the min (FIX-SR-8)
            window_lows = lows[i - lookback: i + lookback + 1]
            min_val = window_lows.min()
            if lows[i] == min_val and np.argmin(window_lows) == lookback:
                zones.append({
                    'price_level': float(lows[i]),
                    'zone_type': 'support',
                    'detection_method': 'swing',
                    'timestamp': pd.Timestamp(times[i]).to_pydatetime().replace(tzinfo=None),
                    '_formation_idx': i,  # consumed by score_zone, not persisted (FIX-SR-4)
                })

        return zones

    @staticmethod
    def detect_round_numbers(
        symbol: str,
        current_price: float,
        range_pct: float = 0.15,
        price_range: tuple[float, float] | None = None,
        grain: str = 'large',
    ) -> list[dict]:
        """
        Generate zones at psychologically significant round numbers near current price.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            current_price: Latest price to anchor the round number search
            range_pct: How far above/below current price to generate levels (default ±15%)
            price_range: Optional (min_price, max_price) to override range_pct.
                         Used by backtests to cover the full historical price range
                         without anchoring to the last bar's price.
            grain: Which round-number increments to emit — 'large' (default, sparse,
                   recommended for chart clarity), 'small' (dense), or 'both'.

        Returns:
            List of zone dicts for round number levels
        """
        config = get_round_grains(symbol, current_price)
        zones = []

        if price_range is not None:
            price_lower = price_range[0] * 0.95   # small buffer below min
            price_upper = price_range[1] * 1.05   # small buffer above max
        else:
            price_lower = current_price * (1 - range_pct)
            price_upper = current_price * (1 + range_pct)

        increment_keys = ['small', 'large'] if grain == 'both' else [grain]
        for increment_key in increment_keys:
            increment = config[increment_key]

            # Start from the nearest round number at or below price_lower
            # Use integer step counter to avoid floating-point drift (FIX-SR-7)
            start = round((price_lower // increment) * increment, 10)
            n = 0

            while True:
                level = round(start + n * increment, 10)
                if level > price_upper:
                    break
                # Only include levels within the actual range bounds
                if level > 0 and level >= price_lower:
                    # When using full range, zone_type is 'both' since
                    # support/resistance is relative to where price is at
                    # any given time, not a single anchor price.
                    if price_range is not None:
                        zone_type = 'both'
                    elif level < current_price:
                        zone_type = 'support'
                    elif level > current_price:
                        zone_type = 'resistance'
                    else:
                        zone_type = 'both'

                    zones.append({
                        'price_level': round(float(level), 10),
                        'zone_type': zone_type,
                        'detection_method': 'round_number',
                        'timestamp': datetime.utcnow().replace(tzinfo=None),
                    })
                n += 1

        # Deduplicate (large increments are subsets of small ones)
        seen = set()
        unique_zones = []
        for z in zones:
            key = round(z['price_level'], 8)
            if key not in seen:
                seen.add(key)
                unique_zones.append(z)

        return unique_zones

    @staticmethod
    def detect_prev_period_hl(symbol: str) -> list[dict]:
        """
        Detect previous day and previous ISO calendar week high/low levels.
        These are strong institutional levels — uses 1D candles regardless of analysis timeframe.

        Args:
            symbol: Trading pair

        Returns:
            List of zone dicts for previous period H/L levels
        """
        zones = []

        # Fetch recent 1D candles (enough to cover a full previous week)
        candles_1d = (
            Candle.query
            .filter_by(symbol=symbol, timeframe='1d')
            .order_by(Candle.open_time.desc())
            .limit(14)
            .all()
        )

        if len(candles_1d) >= 2:
            # Previous day high/low (second most recent 1D candle)
            prev_day = candles_1d[1]
            prev_day_ts = prev_day.open_time
            if hasattr(prev_day_ts, 'tzinfo') and prev_day_ts.tzinfo is not None:
                prev_day_ts = prev_day_ts.replace(tzinfo=None)
            zones.append({
                'price_level': float(prev_day.high),
                'zone_type': 'resistance',
                'detection_method': 'prev_day_hl',
                'timestamp': prev_day_ts,
            })
            zones.append({
                'price_level': float(prev_day.low),
                'zone_type': 'support',
                'detection_method': 'prev_day_hl',
                'timestamp': prev_day_ts,
            })

        # Determine the previous ISO week (Monday–Sunday) (FIX-SR-2)
        today = datetime.utcnow().date()
        current_iso_week = today.isocalendar()[1]
        current_iso_year = today.isocalendar()[0]

        prev_week_candles = [
            c for c in candles_1d
            if c.open_time.isocalendar()[1] != current_iso_week
            or c.open_time.isocalendar()[0] != current_iso_year
        ]

        if prev_week_candles:
            # Filter to only the immediately previous week
            prev_week_num = prev_week_candles[0].open_time.isocalendar()[1]
            prev_week_year = prev_week_candles[0].open_time.isocalendar()[0]
            prev_week_candles = [
                c for c in prev_week_candles
                if c.open_time.isocalendar()[1] == prev_week_num
                and c.open_time.isocalendar()[0] == prev_week_year
            ]

            if prev_week_candles:
                week_high = max(c.high for c in prev_week_candles)
                week_low = min(c.low for c in prev_week_candles)
                week_first_ts = prev_week_candles[0].open_time
                week_last_ts = prev_week_candles[-1].open_time
                if hasattr(week_first_ts, 'tzinfo') and week_first_ts.tzinfo is not None:
                    week_first_ts = week_first_ts.replace(tzinfo=None)
                if hasattr(week_last_ts, 'tzinfo') and week_last_ts.tzinfo is not None:
                    week_last_ts = week_last_ts.replace(tzinfo=None)
                zones.append({
                    'price_level': float(week_high),
                    'zone_type': 'resistance',
                    'detection_method': 'prev_week_hl',
                    'timestamp': week_first_ts,
                })
                zones.append({
                    'price_level': float(week_low),
                    'zone_type': 'support',
                    'detection_method': 'prev_week_hl',
                    'timestamp': week_last_ts,
                })

        return zones

    # ---------- Zone Processing ----------

    @staticmethod
    def calculate_zone_width(price_level: float, atr: float) -> tuple[float, float]:
        """
        Calculate zone upper and lower bounds based on ATR.
        Zone width = price_level ± (0.25 × ATR)

        Args:
            price_level: Center of the zone
            atr: Current ATR value

        Returns:
            Tuple of (zone_upper, zone_lower)
        """
        half_width = 0.25 * atr
        return (price_level + half_width, price_level - half_width)

    @staticmethod
    def merge_zones(zones: list[dict], atr: float) -> list[dict]:
        """
        Merge overlapping zones that are within 0.75 × ATR of each other.
        A wider threshold than the historical 0.5×ATR collapses more near-equal
        levels into single bands — essential for a de-cluttered chart.
        Iterates until output stabilises to catch cascading overlaps (FIX-SR-6).

        Args:
            zones: List of candidate zone dicts
            atr: Current ATR value for determining merge threshold

        Returns:
            Merged list of unique zones
        """
        if not zones or atr <= 0:
            return zones

        merge_threshold = 0.75 * atr

        def _single_pass(zs: list[dict]) -> list[dict]:
            sorted_zs = sorted(zs, key=lambda z: z['price_level'])
            merged = []
            for zone in sorted_zs:
                if not merged:
                    merged.append(zone)
                    continue
                last = merged[-1]
                if abs(zone['price_level'] - last['price_level']) <= merge_threshold:
                    last['price_level'] = (last['price_level'] + zone['price_level']) / 2.0
                    if last['zone_type'] != zone['zone_type']:
                        last['zone_type'] = 'both'
                    if zone.get('timestamp') and last.get('timestamp'):
                        if zone['timestamp'] > last['timestamp']:
                            last['timestamp'] = zone['timestamp']
                    # Keep higher touch count on merge
                    last['touch_count'] = max(
                        last.get('touch_count', 0), zone.get('touch_count', 0)
                    )
                else:
                    merged.append(zone)
            return merged

        prev = zones
        for _ in range(10):  # Safety cap — converges in 2–3 passes in practice
            result = _single_pass(prev)
            if len(result) == len(prev):
                break
            prev = result

        return result

    @staticmethod
    def score_zone(zone: dict, df: pd.DataFrame, timeframe: str,
                   formation_idx: int = None, max_bar: int = None) -> dict:
        """
        Assign a strength score to a zone based on historical touches and timeframe weight.

        Touch semantics (FIX-SR-LOOK): a touch = any candle *after* the zone
        formed whose high/low range intersects the zone band. Counting only
        post-formation touches is both semantically correct (a zone can only be
        "tested" once it exists) and consistent across the DB and DataFrame
        detection paths. The previous DB path counted all candles and the DF
        path counted pre-formation candles — an inconsistency that inflated
        strengths and bloated the chart.

        Strength formula (touch-gated + recency-decayed):
            if touches < 2:  strength = 0          (a single touch is not S/R)
            else:            base = min(1.0, (touches-1)*0.12 + tf_weight*0.5)
                              strength = base * exp(-age / 150)
            where age = bars since the zone was last tested.

        Args:
            zone: Zone dict with price_level, zone_upper, zone_lower
            df: DataFrame of candles for touch counting
            timeframe: Origin timeframe of this zone
            formation_idx: Index of the candle that formed this zone. Touches
                           are counted from formation_idx+1 onward. None for
                           zones that exist from the earliest data (round
                           numbers / prev-period levels).
            max_bar: If set, only count touches in df[formation_idx+1 : max_bar].
                     Defaults to None (= end of df). Backtests can pass their
                     current bar to avoid lookahead.

        Returns:
            Updated zone dict with strength_score and touch_count
        """
        upper = zone.get('zone_upper', zone['price_level'])
        lower = zone.get('zone_lower', zone['price_level'])

        end = max_bar if max_bar is not None else len(df)
        last_bar_index = end - 1

        # Touch window: bars AFTER formation (a zone can only be tested once
        # it exists). Round numbers / prev-period levels (formation_idx None)
        # exist from the earliest data, so count from the start.
        start = formation_idx + 1 if formation_idx is not None else 0
        if start < 0:
            start = 0

        scoring_df = df.iloc[start:end]
        if len(scoring_df) == 0:
            touch_count = 0
            last_tested = None
            last_tested_idx = None
        else:
            touch_mask = (scoring_df['high'] >= lower) & (scoring_df['low'] <= upper)
            touch_count = int(touch_mask.sum())

            last_tested = None
            last_tested_idx = None
            if touch_mask.any():
                # Position within the full df (offset by start)
                last_tested_idx = int(np.where(touch_mask.values)[0][-1]) + start
                last_tested = scoring_df.loc[touch_mask, 'open_time'].iloc[-1]
                if isinstance(last_tested, pd.Timestamp):
                    last_tested = last_tested.to_pydatetime()
                if hasattr(last_tested, 'tzinfo') and last_tested.tzinfo is not None:
                    last_tested = last_tested.replace(tzinfo=None)

        tf_weight = TIMEFRAME_WEIGHTS.get(timeframe, 0.10)

        # Touch-gated strength: zones with <2 touches are not real S/R.
        MIN_TOUCHES_SCORE = 2
        if touch_count < MIN_TOUCHES_SCORE:
            strength = 0.0
        else:
            base = min(1.0, (touch_count - 1) * 0.12 + tf_weight * 0.5)
            # Recency decay: zones untested for a long time weaken.
            if last_tested_idx is not None:
                age = max(0, last_bar_index - last_tested_idx)
            elif formation_idx is not None:
                age = max(0, last_bar_index - formation_idx)
            else:
                age = 0
            strength = base * float(np.exp(-age / 150.0))

        zone['strength_score'] = round(strength, 4)
        zone['touch_count'] = touch_count
        zone['last_tested'] = last_tested

        return zone

    # ---------- Full Zone Detection Pipeline ----------

    @classmethod
    def detect_zones(cls, symbol: str, timeframe: str, swing_lookback: int = 12) -> list[dict]:
        """
        Full S/R zone detection pipeline for a symbol/timeframe:
        1. Fetch candles from DB
        2. Run detection methods (swings + round numbers)
        3. Calculate zone widths using ATR
        4. Merge nearby zones
        5. Score zones for strength
        6. Drop zones with fewer than 2 touches (not real S/R)

        Previous day/week H/L is no longer emitted here — it is subsumed by
        the richer Pivot Points layer (see pivot_engine). Round numbers use the
        sparse 'large' grain only to avoid chart clutter.

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            swing_lookback: Lookback period for swing detection (default 12 —
                            a wider window flags structural pivots, not micro-noise)

        Returns:
            List of fully processed zone dicts ready for DB insertion
        """
        # Fetch candle data
        candles = (
            Candle.query
            .filter_by(symbol=symbol, timeframe=timeframe)
            .order_by(Candle.open_time.desc())
            .limit(500)
            .all()
        )

        if len(candles) < swing_lookback * 2 + 1:
            print(f"[SREngine] Insufficient data for {symbol}/{timeframe}: "
                  f"{len(candles)} candles (need at least {swing_lookback * 2 + 1})")
            return []

        data = [c.to_dict() for c in candles]
        df = pd.DataFrame(data)
        df['open_time'] = pd.to_datetime(df['open_time'])
        df = df.sort_values('open_time').reset_index(drop=True)

        # Compute ATR for zone width calculations
        atr_series = compute_atr(df['high'], df['low'], df['close'], 14)
        current_atr = float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else 0
        current_price = float(df['close'].iloc[-1])

        if current_atr <= 0:
            # Fallback: use 1% of current price as ATR proxy
            current_atr = current_price * 0.01

        # ---------- Run detection methods ----------
        all_zones = []

        # 1. Swing highs/lows
        swing_zones = cls.detect_swing_points(df, lookback=swing_lookback)
        all_zones.extend(swing_zones)

        # 2. Round psychological numbers (sparse large grain only)
        round_zones = cls.detect_round_numbers(symbol, current_price, grain='large')
        all_zones.extend(round_zones)

        # Previous day/week H/L is handled by the Pivot Points layer now.

        if not all_zones:
            return []

        # ---------- Calculate zone widths ----------
        for zone in all_zones:
            upper, lower = cls.calculate_zone_width(zone['price_level'], current_atr)
            zone['zone_upper'] = upper
            zone['zone_lower'] = lower

        # ---------- Merge nearby zones ----------
        merged_zones = cls.merge_zones(all_zones, current_atr)

        # Recalculate widths after merging (price_levels may have changed)
        for zone in merged_zones:
            upper, lower = cls.calculate_zone_width(zone['price_level'], current_atr)
            zone['zone_upper'] = upper
            zone['zone_lower'] = lower

        # ---------- Score zones ----------
        for zone in merged_zones:
            cls.score_zone(zone, df, timeframe,
                           formation_idx=zone.pop('_formation_idx', None))

        # Add symbol and timeframe metadata
        for zone in merged_zones:
            zone['symbol'] = symbol
            zone['timeframe'] = timeframe

        # Drop zones that are not real S/R (< 2 post-formation touches).
        # These never reach the chart and keep the DB lean.
        merged_zones = [z for z in merged_zones if z.get('touch_count', 0) >= 2]

        return merged_zones

    @classmethod
    def detect_zones_df(cls, df: pd.DataFrame, symbol: str,
                        timeframe: str, swing_lookback: int = 12,
                        max_bar: int = None) -> pd.DataFrame:
        """
        Run the full S/R detection pipeline on a DataFrame and append zone columns.

        S/R zones do NOT use the masked ffill + mitigation kill-switch pattern
        (unlike FVGs/OBs). S/R zones persist — a broken resistance flips to
        support, not to NaN.

        Touch counting uses post-formation bars up to `max_bar` (or end of df)
        — consistent with detect_zones() and free of lookahead when a backtest
        passes its current bar as max_bar.

        Appends columns:
            sr_active:        bool — True where zones exist (all rows after detection)
            sr_support_upper: float64 — upper bound of strongest support
            sr_support_lower: float64 — lower bound of strongest support
            sr_support_strength: float64
            sr_resistance_upper: float64 — upper bound of strongest resistance
            sr_resistance_lower: float64 — lower bound of strongest resistance
            sr_resistance_strength: float64

        Args:
            df: DataFrame with [open_time, open, high, low, close]
            symbol: Trading pair
            timeframe: Candle timeframe
            swing_lookback: Lookback for swing detection (default 12)
            max_bar: Upper bound (exclusive) for touch scoring. Defaults to None
                     (= end of df, live snapshot). Backtests pass their current
                     bar index to avoid lookahead.

        Returns:
            DataFrame with sr_* columns appended
        """
        df = df.copy()
        n = len(df)

        # Initialize columns
        df['sr_active'] = False
        df['sr_support_upper'] = np.nan
        df['sr_support_lower'] = np.nan
        df['sr_support_strength'] = np.nan
        df['sr_resistance_upper'] = np.nan
        df['sr_resistance_lower'] = np.nan
        df['sr_resistance_strength'] = np.nan

        if n < swing_lookback * 2 + 1:
            return df

        # Compute ATR
        atr_series = compute_atr(df['high'], df['low'], df['close'], 14)
        current_atr = float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else 0
        current_price = float(df['close'].iloc[-1])

        if current_atr <= 0:
            current_atr = current_price * 0.01

        # Run all detection methods
        all_zones = []

        swing_zones = cls.detect_swing_points(df, lookback=swing_lookback)
        all_zones.extend(swing_zones)

        # Use full price range for round numbers to avoid anchoring
        # to a single price point (prevents lookahead in backtests).
        # Sparse large grain only to avoid chart clutter.
        price_min = float(df['close'].min())
        price_max = float(df['close'].max())
        round_zones = cls.detect_round_numbers(
            symbol, current_price, price_range=(price_min, price_max), grain='large',
        )
        all_zones.extend(round_zones)

        # Previous day/week H/L is handled by the Pivot Points layer now.

        if not all_zones:
            return df

        # Calculate zone widths
        for zone in all_zones:
            upper, lower = cls.calculate_zone_width(zone['price_level'], current_atr)
            zone['zone_upper'] = upper
            zone['zone_lower'] = lower

        # Merge and score
        merged_zones = cls.merge_zones(all_zones, current_atr)

        # Capture formation indices BEFORE score_zone pops _formation_idx.
        # Swing zones have _formation_idx (candle index). Round numbers and
        # prev-period levels don't — they exist from the earliest data.
        zone_form_idx = {}
        for i, zone in enumerate(merged_zones):
            zone_form_idx[i] = zone.get('_formation_idx', None)

        for i, zone in enumerate(merged_zones):
            upper, lower = cls.calculate_zone_width(zone['price_level'], current_atr)
            zone['zone_upper'] = upper
            zone['zone_lower'] = lower
            form_idx = zone.pop('_formation_idx', None)
            # Score using post-formation touches up to max_bar (or end of df).
            # Consistent with detect_zones(); no lookahead when a backtest
            # bounds max_bar to its current simulation bar.
            cls.score_zone(zone, df, timeframe,
                           formation_idx=form_idx,
                           max_bar=max_bar)
            # Restore the formation index for temporal masking
            saved_idx = zone_form_idx.get(i)
            if saved_idx is not None:
                zone['_formation_idx'] = saved_idx

        # Separate into support and resistance
        supports = [z for z in merged_zones if z['zone_type'] in ('support', 'both')]
        resistances = [z for z in merged_zones if z['zone_type'] in ('resistance', 'both')]

        # Pick strongest support and resistance
        best_support = max(supports, key=lambda z: z.get('strength_score', 0), default=None)
        best_resistance = max(resistances, key=lambda z: z.get('strength_score', 0), default=None)

        # ── Temporally-safe zone assignment ──
        # Zones must only exist AFTER the candle that formed them.
        # Round numbers and prev-period levels have no _formation_idx
        # and exist from the earliest valid data point onward.
        if best_support:
            form_idx = best_support.get('_formation_idx', swing_lookback * 2)
            df.loc[df.index[form_idx:], 'sr_active'] = True
            df.loc[df.index[form_idx:], 'sr_support_upper'] = best_support['zone_upper']
            df.loc[df.index[form_idx:], 'sr_support_lower'] = best_support['zone_lower']
            df.loc[df.index[form_idx:], 'sr_support_strength'] = best_support.get('strength_score', 0)

        if best_resistance:
            form_idx = best_resistance.get('_formation_idx', swing_lookback * 2)
            df.loc[df.index[form_idx:], 'sr_active'] = True
            df.loc[df.index[form_idx:], 'sr_resistance_upper'] = best_resistance['zone_upper']
            df.loc[df.index[form_idx:], 'sr_resistance_lower'] = best_resistance['zone_lower']
            df.loc[df.index[form_idx:], 'sr_resistance_strength'] = best_resistance.get('strength_score', 0)

        return df

    # ---------- Database Persistence ----------

    @classmethod
    def persist_zones(cls, symbol: str, timeframe: str, zones: list[dict],
                      prune_stale: bool = False):
        """
        Persist detected zones to the database.
        Uses upsert logic: update existing zones, insert new ones.
        Falls back to generic SQLAlchemy ORM if PostgreSQL dialect is unavailable (FIX-SR-3).

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            zones: List of zone dicts from detect_zones()
            prune_stale: If True (used by full_refresh), wipe ALL existing rows
                         for this symbol/timeframe before persisting, so every
                         row in the table reflects the CURRENT scoring — no
                         leftovers from older scoring regimes survive. minor_update
                         keeps this False so it never wipes incremental state.
        """
        # If there are no zones AND we are not pruning, there's nothing to do.
        # An empty `zones` with prune_stale=True still triggers the wipe below
        # (and inserts nothing) — leaving the table clean for that symbol/tf,
        # which is the correct full_refresh-empty result.
        if not zones and not prune_stale:
            return

        # Defensive: never persist zones that are not real S/R (< 2 touches).
        # detect_zones / minor_update already filter, but guard here too so any
        # future caller cannot re-bloat the table.
        zones = [z for z in zones if z.get('touch_count', 0) >= 2]

        try:
            # Full-wipe stale-row cleanup. On full_refresh the new detection
            # window (lookback=12) often won't re-flag a former swing point, so
            # that row's upsert would never fire and its old strength/score would
            # stay frozen at the previous regime's value. Wiping ALL existing
            # rows for this symbol/tf and persisting only the freshly-detected set
            # guarantees every row reflects CURRENT scoring.
            if prune_stale:
                SRZone.query.filter(
                    SRZone.symbol == symbol,
                    SRZone.timeframe == timeframe,
                ).delete(synchronize_session=False)
                db.session.commit()

            if not zones:
                return
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            for zone in zones:
                zone_record = cls._build_zone_record(zone)
                stmt = pg_insert(SRZone).values(**zone_record)
                do_upsert = stmt.on_conflict_do_update(
                    constraint='uq_sr_zone',
                    set_={
                        'zone_upper': stmt.excluded.zone_upper,
                        'zone_lower': stmt.excluded.zone_lower,
                        'zone_type': stmt.excluded.zone_type,
                        'strength_score': stmt.excluded.strength_score,
                        'touch_count': stmt.excluded.touch_count,
                        'last_tested': stmt.excluded.last_tested,
                        'updated_at': db.func.now(),
                    }
                )
                db.session.execute(do_upsert)

        except Exception:
            # SQLite / generic fallback (test environment)
            db.session.rollback()
            for zone in zones:
                zone_record = cls._build_zone_record(zone)
                existing = SRZone.query.filter_by(
                    symbol=zone_record['symbol'],
                    timeframe=zone_record['timeframe'],
                    price_level=zone_record['price_level'],
                ).first()
                if existing:
                    for key, val in zone_record.items():
                        setattr(existing, key, val)
                else:
                    db.session.add(SRZone(**zone_record))

        db.session.commit()
        print(f"[SREngine] Persisted {len(zones)} zones for {symbol}/{timeframe}")

    @staticmethod
    def _build_zone_record(zone: dict) -> dict:
        """Extract and round zone fields for DB insertion."""
        return {
            'symbol': zone['symbol'],
            'timeframe': zone['timeframe'],
            'price_level': round(zone['price_level'], 8),
            'zone_upper': round(zone['zone_upper'], 8),
            'zone_lower': round(zone['zone_lower'], 8),
            'zone_type': zone['zone_type'],
            'detection_method': zone['detection_method'],
            'strength_score': zone.get('strength_score', 0.0),
            'touch_count': zone.get('touch_count', 0),
            'last_tested': zone.get('last_tested'),
        }

    @classmethod
    def full_refresh(cls, symbol: str, timeframe: str):
        """
        Full S/R zone refresh: detect all zones and persist to DB.
        Called on 4h candle close. Uses per-symbol lock to avoid races (FIX-SCH-3).
        """
        print(f"[SREngine] Full refresh for {symbol}/{timeframe}...")
        with cls.get_refresh_lock(symbol):
            zones = cls.detect_zones(symbol, timeframe)
            if zones:
                cls.persist_zones(symbol, timeframe, zones, prune_stale=True)
            else:
                # Nothing detected, but still clean up stale rows so a fresh
                # full refresh leaves the table tidy.
                cls.persist_zones(symbol, timeframe, [], prune_stale=True)
                print(f"[SREngine] No zones detected for {symbol}/{timeframe}")

    @classmethod
    def minor_update(cls, symbol: str, timeframe: str):
        """
        Minor zone update: only swing point detection on latest data window.
        Called on 1h candle close. Adds new swing points without full recalculation.
        Uses per-symbol lock to avoid races (FIX-SCH-3).
        """
        print(f"[SREngine] Minor update for {symbol}/{timeframe}...")

        with cls.get_refresh_lock(symbol):
            candles = (
                Candle.query
                .filter_by(symbol=symbol, timeframe=timeframe)
                .order_by(Candle.open_time.desc())
                .limit(50)  # Only recent window
                .all()
            )

            if len(candles) < 11:  # Need at least 2*lookback+1 candles
                return

            data = [c.to_dict() for c in candles]
            df = pd.DataFrame(data)
            df['open_time'] = pd.to_datetime(df['open_time'])
            df = df.sort_values('open_time').reset_index(drop=True)

            # Detect new swing points
            swing_zones = cls.detect_swing_points(df, lookback=12)

            if not swing_zones:
                return

            # Calculate ATR for zone widths
            atr_series = compute_atr(df['high'], df['low'], df['close'], 14)
            current_atr = float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else 0
            current_price = float(df['close'].iloc[-1])

            if current_atr <= 0:
                current_atr = current_price * 0.01

            for zone in swing_zones:
                upper, lower = cls.calculate_zone_width(zone['price_level'], current_atr)
                zone['zone_upper'] = upper
                zone['zone_lower'] = lower
                zone['symbol'] = symbol
                zone['timeframe'] = timeframe
                cls.score_zone(zone, df, timeframe,
                               formation_idx=zone.pop('_formation_idx', None))

            # Only persist zones that are real S/R (>= 2 post-formation touches)
            swing_zones = [z for z in swing_zones if z.get('touch_count', 0) >= 2]
            if not swing_zones:
                return

            cls.persist_zones(symbol, timeframe, swing_zones)

        # Invalidate indicator cache after zone changes (FIX-SCH-4)
        IndicatorService.invalidate_cache(symbol, timeframe)
