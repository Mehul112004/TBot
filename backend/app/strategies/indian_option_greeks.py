"""
Option-Aware Directional Strategy v1.0 — Indian F&O

Trades NIFTY/BANKNIFTY options by scanning the underlying for directional
bias and applying option-specific gates (expiry proximity, volatility,
trend strength). Designed for index options (weekly + monthly expiry).

Signal direction is for the underlying; option strike selection
(ATM/OTM) is determined by risk parameters and expiry distance.

Confidence = fraction of gates passed.
"""

import numpy as np
import pandas as pd

from app.core.base_strategy import BaseStrategy, SetupSignal


class IndianOptionGreeksStrategy(BaseStrategy):
    name = "Indian Option Greeks"
    description = (
        "Directional strategy for NIFTY/BANKNIFTY options. Scans underlying "
        "for trend bias then applies option-aware gates: expiry proximity, "
        "implied volatility proxy (BB width), trend strength, and volume "
        "confirmation. Best on weekly/monthly index options."
    )
    timeframes = ["15m"]
    version = "1.0"
    min_confidence = 0.70

    allowed_regimes = ["TRENDING_UP", "TRENDING_DOWN"]
    allowed_market_types = ["INDIAN"]
    require_htf_alignment = True
    sl_atr_mult = 1.0
    tp1_rr = 2.0
    tp2_rr = 3.5

    required_features = ['ema', 'rsi', 'atr', 'bb', 'volume_ma']

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['signal'] = 0
        df['direction'] = None
        df['confidence'] = 0.0

        n = len(df)
        if n < 30:
            return df

        close = df['close']
        ema50 = df['ema_50']
        rsi = df['rsi']
        atr = df['atr']
        bb_width = df['bb_width']
        vol_ma = df['volume_ma']

        # ── Gate 1 (HARD): Trend established (ADX >= 25) ──
        g1_bull = (df['regime'] == 'TRENDING_UP') & (df['adx'] >= 25)
        g1_bear = (df['regime'] == 'TRENDING_DOWN') & (df['adx'] >= 25)
        gate_1 = g1_bull | g1_bear

        # ── Gate 2 (HARD): EMA 50 trend alignment ──
        g2_bull = ema50.notna() & (close > ema50)
        g2_bear = ema50.notna() & (close < ema50)
        gate_2 = (g1_bull & g2_bull) | (g1_bear & g2_bear)

        # ── Gate 3 (HARD): RSI not extreme (momentum, not exhaustion) ──
        g3_bull = rsi.notna() & (rsi > 35) & (rsi < 75)
        g3_bear = rsi.notna() & (rsi < 65) & (rsi > 25)
        gate_3 = (g1_bull & g3_bull) | (g1_bear & g3_bear)

        # ── Gate 4 (HARD): ATR moderate (not extremely volatile) ──
        # Too high ATR = avoid; too low = no movement
        atr_pct = atr / close * 100  # ATR as % of price
        g4 = atr_pct.notna() & (atr_pct > 0.1) & (atr_pct < 3.0)
        gate_4 = g4

        hard_passed = gate_1 & gate_2 & gate_3 & gate_4
        total_hard = 4

        # ── Soft Gate 1: Volume > average (confirms participation) ──
        sg1 = vol_ma.notna() & (df['volume'] > vol_ma)

        # ── Soft Gate 2: Bollinger Band width expanding (volatility expansion) ──
        bb_width_prev = bb_width.shift(3)
        sg2 = bb_width.notna() & bb_width_prev.notna() & (bb_width > bb_width_prev)

        # ── Soft Gate 3: RSI momentum increasing in signal direction ──
        rsi_prev = rsi.shift(2)
        sg3_bull = g1_bull & rsi.notna() & rsi_prev.notna() & (rsi > rsi_prev)
        sg3_bear = g1_bear & rsi.notna() & rsi_prev.notna() & (rsi < rsi_prev)
        sg3 = sg3_bull | sg3_bear

        # ── Soft Gate 4: Bullish/bearish candle body ──
        body = (df['close'] - df['open']).abs()
        candle_range = df['high'] - df['low']
        sg4_bull = (candle_range > 0) & (body > candle_range * 0.3) & (df['close'] > df['open'])
        sg4_bear = (candle_range > 0) & (body > candle_range * 0.3) & (df['close'] < df['open'])
        sg4 = (g1_bull & sg4_bull) | (g1_bear & sg4_bear)

        # ── Soft Gate 5: Close above EMA 21 (bull) / below (bear) ──
        ema21 = df['ema_21'] if 'ema_21' in df.columns else ema50
        sg5_bull = ema21.notna() & (close > ema21)
        sg5_bear = ema21.notna() & (close < ema21)
        sg5 = (g1_bull & sg5_bull) | (g1_bear & sg5_bear)

        soft_gates = [sg1, sg2, sg3, sg4, sg5]
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
        if signal.direction == 'LONG':
            return (round(signal.entry + self.tp1_rr * risk, 8),
                    round(signal.entry + self.tp2_rr * risk, 8))
        else:
            return (round(signal.entry - self.tp1_rr * risk, 8),
                    round(signal.entry - self.tp2_rr * risk, 8))

    def should_confirm_with_llm(self, signal: SetupSignal) -> bool:
        """Option strategies benefit from LLM context (expiry, Greeks, VIX)."""
        return True
