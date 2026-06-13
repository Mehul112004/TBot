"""
Gap Fill Strategy v1.0 — Indian Intraday

Indian stocks often gap up/down at open and fill the gap within the
first hour. This strategy trades the gap-fill direction after confirmation.

Only fires in the first 60 minutes of trading.
"""

import numpy as np
import pandas as pd

from app.core.base_strategy import BaseStrategy, SetupSignal


class IndianGapFillStrategy(BaseStrategy):
    name = "Indian Gap Fill"
    description = (
        "Trades gap fills within the first 60 minutes of Indian market open. "
        "Gap detected from prior day close, confirmed by first 10 min direction. "
        "Skips news-driven gaps (>3%)."
    )
    timeframes = ["5m"]
    version = "1.0"
    min_confidence = 0.55

    allowed_regimes = []
    allowed_market_types = ["INDIAN"]
    require_htf_alignment = False
    sl_atr_mult = 1.0
    tp1_rr = 1.5
    tp2_rr = 2.5

    required_features = ['ema', 'atr', 'volume_ma']

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['signal'] = 0
        df['direction'] = None
        df['confidence'] = 0.0

        n = len(df)
        if n < 15:
            return df

        close = df['close']
        v_ma = df['volume_ma']
        atr = df['atr']

        # Detect day boundaries
        df['_date'] = pd.to_datetime(df['open_time']).dt.date
        df['_first_of_day'] = df['_date'] != df['_date'].shift(1)

        # Prior day's close = last candle's close before first-of-day reset
        prior_close = pd.Series(np.nan, index=df.index)
        for i in range(1, n):
            idx = df.index[i]
            if df.loc[idx, '_first_of_day']:
                prev_idx = df.index[i - 1]
                prior_close.loc[idx] = close.loc[prev_idx]
        prior_close = prior_close.ffill()

        # First candle of the day = the open price
        first_open = pd.Series(np.nan, index=df.index)
        for idx in df.index:
            if df.loc[idx, '_first_of_day']:
                first_open.loc[idx] = df.loc[idx, 'open']
        first_open = first_open.ffill()

        # Gap = open vs prior close as percentage
        gap_pct = ((first_open - prior_close) / prior_close) * 100.0

        # ── Gate 1 (HARD): Gap detected (1-3%) ──
        g1_bull = gap_pct > 1.0   # Gap up
        g1_bear = gap_pct < -1.0  # Gap down
        g1_size_ok = gap_pct.abs() < 3.0  # Not too large (news-driven)
        gate_1 = (g1_bull | g1_bear) & g1_size_ok

        # ── Gate 2 (HARD): Within first 60 min (12 x 5m candles) ──
        candle_of_day = (df['_date'] == df['_date']).astype(int)
        candle_of_day = candle_of_day.groupby(df['_date']).cumsum()
        g2 = candle_of_day <= 12

        # ── Gate 3 (HARD): First 2 candles confirm gap direction ──
        # Gap up + first 2 candles close above open → LONG (gap fill up is less likely, fade)
        # Actually: trade IN the direction of the gap (gap continuation)
        candle_close_vs_open = close > df['open']
        early_direction = (
            candle_close_vs_open.rolling(2, min_periods=2).mean()
        )
        g3_bull = g1_bull & (early_direction >= 0.5)
        g3_bear = g1_bear & (early_direction <= 0.5)
        gate_3 = g3_bull | g3_bear

        hard_passed = gate_1 & g2 & gate_3
        total_hard = 3

        # ── Soft Gate 1: Volume > average ──
        sg1 = v_ma.notna() & (df['volume'] > v_ma)

        # ── Soft Gate 2: ADX confirms momentum (not choppy) ──
        sg2 = df['adx'].notna() & (df['adx'] > 20)

        # ── Soft Gate 3: Close moving further in gap direction ──
        sg3_bull = g1_bull & (close > first_open)
        sg3_bear = g1_bear & (close < first_open)
        sg3 = sg3_bull | sg3_bear

        soft_gates = [sg1, sg2, sg3]
        total_soft = len(soft_gates)
        total_gates = total_hard + total_soft

        soft_passed = sum(sg.astype(float) for sg in soft_gates)
        confidence = np.where(hard_passed, (total_hard + soft_passed) / total_gates, 0.0)

        df['signal'] = np.where(hard_passed & (confidence >= self.min_confidence), 1, 0)
        df['direction'] = None
        df.loc[(df['signal'] == 1) & g3_bull, 'direction'] = 'LONG'
        df.loc[(df['signal'] == 1) & g3_bear, 'direction'] = 'SHORT'
        df['confidence'] = confidence

        df.drop(['_date', '_first_of_day'], axis=1, errors='ignore')
        return df

    def calculate_sl(self, signal: SetupSignal, df: pd.DataFrame,
                     signal_idx: int, atr: float) -> float:
        if signal_idx < 3:
            return None
        window = df.iloc[max(0, signal_idx - 8):signal_idx + 1]
        if signal.direction == 'LONG':
            pivot = window['low'].rolling(3).min().iloc[-1]
            if pd.isna(pivot):
                return None
            return round(pivot - (self.sl_atr_mult * atr), 8)
        else:
            pivot = window['high'].rolling(3).max().iloc[-1]
            if pd.isna(pivot):
                return None
            return round(pivot + (self.sl_atr_mult * atr), 8)

    def calculate_tp(self, signal: SetupSignal, df: pd.DataFrame,
                     signal_idx: int, atr: float) -> tuple:
        if signal.entry is None or signal.sl is None:
            return (None, None)
        risk = abs(signal.entry - signal.sl)
        if risk <= 0:
            risk = atr * 0.2
        if signal.direction == 'LONG':
            return (round(signal.entry + self.tp1_rr * risk, 8),
                    round(signal.entry + self.tp2_rr * risk, 8))
        else:
            return (round(signal.entry - self.tp1_rr * risk, 8),
                    round(signal.entry - self.tp2_rr * risk, 8))
