"""
VWAP Mean Reversion Strategy v1.0 — Indian Intraday

Fades extended moves away from VWAP. When price deviates significantly
from the daily VWAP with RSI extreme + exhaustion volume, trade a
reversion back to VWAP.

Designed for Indian indices (NIFTY, BANKNIFTY) and liquid stocks.
"""

import numpy as np
import pandas as pd

from app.core.base_strategy import BaseStrategy, SetupSignal


class IndianVWAPReversalStrategy(BaseStrategy):
    name = "Indian VWAP Reversal"
    description = (
        "Mean reversion from daily VWAP for Indian markets. Trades reversals "
        "when price deviates >2% from VWAP with RSI extremes and declining "
        "volume (exhaustion). Best on NIFTY, BANKNIFTY."
    )
    timeframes = ["5m"]
    version = "1.0"
    min_confidence = 0.65

    allowed_regimes = ["RANGING", "CHOPPY"]
    allowed_market_types = ["INDIAN"]
    require_htf_alignment = False
    sl_atr_mult = 1.0
    tp1_rr = 1.5
    tp2_rr = 2.5

    required_features = ['rsi', 'atr', 'volume_ma', 'vwap']

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['signal'] = 0
        df['direction'] = None
        df['confidence'] = 0.0

        n = len(df)
        if n < 20:
            return df

        vwap = df['vwap']
        close = df['close']
        rsi = df['rsi']
        vol_ma = df['volume_ma']
        atr = df['atr']

        # Deviation from VWAP as percentage
        deviation = ((close - vwap) / vwap) * 100.0

        # ── Gate 1 (HARD): Significant deviation from VWAP ──
        # >2% for stocks, >0.5% for indices (use 1.5% as compromise)
        g1_bull = (vwap > 0) & (deviation < -1.5)  # Undervalued
        g1_bear = (vwap > 0) & (deviation > 1.5)   # Overvalued
        gate_1 = g1_bull | g1_bear

        # ── Gate 2 (HARD): RSI at extreme ──
        g2_bull = rsi.notna() & (rsi < 30)
        g2_bear = rsi.notna() & (rsi > 70)
        gate_2 = (g1_bull & g2_bull) | (g1_bear & g2_bear)

        # ── Gate 3 (HARD): Volume declining (exhaustion, not continuation) ──
        g3 = vol_ma.notna() & (df['volume'] < vol_ma * 0.8)

        hard_passed = gate_1 & gate_2 & g3
        total_hard = 3

        # ── Soft Gate 1: Reversal candle pattern ──
        body = (df['close'] - df['open']).abs()
        lower_wick = np.minimum(df['open'], df['close']) - df['low']
        upper_wick = df['high'] - np.maximum(df['open'], df['close'])
        sg1_bull = (body > 0) & (lower_wick > body * 0.6)
        sg1_bear = (body > 0) & (upper_wick > body * 0.6)
        sg1 = (g1_bull & sg1_bull) | (g1_bear & sg1_bear)

        # ── Soft Gate 2: Deviation not too extreme (< 5%) ──
        sg2 = deviation.abs() < 5.0

        # ── Soft Gate 3: Close moving back toward VWAP ──
        prior_dev = deviation.shift(1)
        sg3_bull = g1_bull & (deviation > prior_dev)
        sg3_bear = g1_bear & (deviation < prior_dev)
        sg3 = sg3_bull | sg3_bear

        soft_gates = [sg1, sg2, sg3]
        total_soft = len(soft_gates)
        total_gates = total_hard + total_soft

        soft_passed = sum(sg.astype(float) for sg in soft_gates)
        confidence = np.where(hard_passed, (total_hard + soft_passed) / total_gates, 0.0)

        df['signal'] = np.where(hard_passed & (confidence >= self.min_confidence), 1, 0)
        df['direction'] = None
        df.loc[(df['signal'] == 1) & g1_bull, 'direction'] = 'LONG'
        df.loc[(df['signal'] == 1) & g1_bear, 'direction'] = 'SHORT'
        df['confidence'] = confidence

        return df

    def calculate_sl(self, signal: SetupSignal, df: pd.DataFrame,
                     signal_idx: int, atr: float) -> float:
        if signal_idx < 5:
            return None
        window = df.iloc[max(0, signal_idx - 15):signal_idx + 1]
        if signal.direction == 'LONG':
            pivot = window['low'].rolling(5).min().iloc[-1]
            if pd.isna(pivot):
                return None
            return round(pivot - (self.sl_atr_mult * atr), 8)
        else:
            pivot = window['high'].rolling(5).max().iloc[-1]
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

        # TP1 = VWAP line itself
        vwap_val = float(df['vwap'].iloc[signal_idx]) if signal_idx < len(df) else 0
        if vwap_val > 0:
            tp1 = round(vwap_val, 8)
        elif signal.direction == 'LONG':
            tp1 = round(signal.entry + self.tp1_rr * risk, 8)
        else:
            tp1 = round(signal.entry - self.tp1_rr * risk, 8)

        if signal.direction == 'LONG':
            tp2 = round(signal.entry + self.tp2_rr * risk, 8)
        else:
            tp2 = round(signal.entry - self.tp2_rr * risk, 8)

        return (tp1, tp2)
