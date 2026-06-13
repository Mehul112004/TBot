"""
Opening Range Breakout (ORB) Strategy v1.0 — Indian Intraday

Detects the first 15-minute candle's range (9:15–9:30 IST) and trades
breakouts above the high or below the low with volume confirmation.

Designed for Indian equity indices and liquid stocks.
Confidence = fraction of gates passed.
"""

import numpy as np
import pandas as pd

from app.core.base_strategy import BaseStrategy, SetupSignal


class IndianORBStrategy(BaseStrategy):
    name = "Indian ORB"
    description = (
        "Opening Range Breakout for Indian markets. Defines range from first "
        "15-min candle, trades breakouts with volume + momentum confirmation. "
        "Best on NIFTY, BANKNIFTY, and high-volume stocks."
    )
    timeframes = ["15m"]
    version = "1.0"
    min_confidence = 0.60

    allowed_regimes = ["TRENDING_UP", "TRENDING_DOWN"]
    allowed_market_types = ["INDIAN"]
    require_htf_alignment = False
    sl_atr_mult = 1.2
    tp1_rr = 2.0
    tp2_rr = 3.5

    required_features = ['ema', 'rsi', 'atr', 'volume_ma']

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['signal'] = 0
        df['direction'] = None
        df['confidence'] = 0.0

        n = len(df)
        if n < 10:
            return df

        # Detect the first 15m candle of each day (the "opening range" candle)
        df['_date'] = pd.to_datetime(df['open_time']).dt.date
        df['_first_of_day'] = df['_date'] != df['_date'].shift(1)
        
        # Opening range high/low — forward filled through the day
        first_high = pd.Series(np.nan, index=df.index)
        first_low = pd.Series(np.nan, index=df.index)
        
        for idx in df.index:
            if df.loc[idx, '_first_of_day']:
                first_high.loc[idx] = df.loc[idx, 'high']
                first_low.loc[idx] = df.loc[idx, 'low']
        first_high = first_high.ffill()
        first_low = first_low.ffill()

        # ── Gate 1 (HARD): Opening range established ──
        g1 = first_high.notna() & first_low.notna() & (first_high > first_low)

        atr = df['atr']
        ema50 = df['ema_50']

        # ── Gate 2 (HARD): Breakout above OR high (LONG) or below OR low (SHORT) ──
        g2_bull = df['close'] > first_high
        g2_bear = df['close'] < first_low
        gate_2 = g2_bull | g2_bear

        # ── Gate 3 (HARD): Volume confirmation (1.5x average) ──
        g3 = df['volume_ma'].notna() & (df['volume'] > df['volume_ma'] * 1.5)

        # Combine hard gates
        hard_passed = g1 & gate_2 & g3
        total_hard = 3

        # ── Soft Gate 1: Breakout direction aligns with EMA 50 ──
        sg1_bull = g2_bull & ema50.notna() & (df['close'] > ema50)
        sg1_bear = g2_bear & ema50.notna() & (df['close'] < ema50)
        sg1 = sg1_bull | sg1_bear

        # ── Soft Gate 2: RSI confirms momentum (not overbought/oversold) ──
        rsi = df['rsi']
        sg2_bull = g2_bull & rsi.notna() & (rsi > 45) & (rsi < 75)
        sg2_bear = g2_bear & rsi.notna() & (rsi < 55) & (rsi > 25)
        sg2 = sg2_bull | sg2_bear

        # ── Soft Gate 3: Not first breakout candle of day (wait for confirmation) ──
        breakout_started = (g2_bull | g2_bear).astype(int)
        breakout_ongoing = breakout_started.groupby(df['_date']).cumsum() > 1
        sg3 = breakout_ongoing

        # ── Soft Gate 4: Price not too far from OR (within 2x ATR) ──
        atr_val = atr.fillna(0)
        range_size = first_high - first_low
        sg4_bull = (df['close'] - first_high) < (2.0 * atr_val)
        sg4_bear = (first_low - df['close']) < (2.0 * atr_val)
        sg4 = (g2_bull & sg4_bull) | (g2_bear & sg4_bear)

        soft_gates = [sg1, sg2, sg3, sg4]
        total_soft = len(soft_gates)
        total_gates = total_hard + total_soft

        soft_passed = sum(sg.astype(float) for sg in soft_gates)
        confidence = np.where(hard_passed, (total_hard + soft_passed) / total_gates, 0.0)

        df['signal'] = np.where(hard_passed & (confidence >= self.min_confidence), 1, 0)
        df['direction'] = None
        df.loc[(df['signal'] == 1) & g2_bull, 'direction'] = 'LONG'
        df.loc[(df['signal'] == 1) & g2_bear, 'direction'] = 'SHORT'
        df['confidence'] = confidence

        df.drop(['_date', '_first_of_day'], axis=1, errors='ignore')
        return df

    def calculate_sl(self, signal: SetupSignal, df: pd.DataFrame,
                     signal_idx: int, atr: float) -> float:
        if signal_idx < 3:
            return None
        window = df.iloc[max(0, signal_idx - 10):signal_idx + 1]
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
