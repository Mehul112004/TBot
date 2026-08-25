"""
Strategy Runner v3.0

Orchestrates running strategies against candle data and collecting signals.
Unified DataFrame-based execution for all strategies.

Two modes:
  - Live: run_single_scan() — checks the latest candle for signals
  - Backtest: scan_historical() — walks through all bars collecting signals
"""

import pandas as pd
from typing import Optional, List

from app.core.base_strategy import BaseStrategy, SetupSignal


class StrategyRunner:
    """Executes strategies and collects SetupSignal results."""

    @staticmethod
    def run_single_scan(
        strategy: BaseStrategy,
        symbol: str,
        timeframe: str,
        min_confidence_override: Optional[float] = None,
    ) -> Optional[tuple]:
        """
        Live mode: Execute strategy on the latest candle data.
        Fetches candles from DB, pre-processes, runs generate_signals(),
        extracts the last bar's signal.

        Returns:
            Tuple of (SetupSignal, pre_processed_df) or (None, None).
            The DataFrame is returned for context serialization.
        """
        from app.core.data_utils import get_finalized_candles

        try:
            lookback = strategy.get_required_lookback()
            df = get_finalized_candles(symbol, timeframe, limit=lookback)

            if len(df) < strategy.get_min_candles():
                return None, None

            df = strategy.pre_process(df, symbol=symbol, timeframe=timeframe)
            df = strategy.generate_signals(df)

            last = df.iloc[-1]
            if last.get('signal', 0) != 1:
                return None, None

            confidence = last.get('confidence', 0)
            threshold = min_confidence_override or strategy.min_confidence
            if confidence < threshold:
                return None, None

            direction = last.get('direction', None)
            if direction not in ('LONG', 'SHORT'):
                return None, None

            # Entry at next bar's open (realistic) — for live, use current close
            # (the signal just fired, user can enter at market)
            entry = float(last['close'])
            atr_val = float(last['atr']) if 'atr' in df.columns and pd.notna(last.get('atr')) else 0.0

            signal_idx = len(df) - 1

            regime_strength_value = last.get('regime_strength')
            regime_strength = (
                float(regime_strength_value)
                if pd.notna(regime_strength_value) else None
            )

            signal = SetupSignal(
                strategy_name=strategy.name,
                symbol=symbol,
                timeframe=timeframe,
                direction=direction,
                confidence=round(float(confidence), 4),
                entry=entry,
                regime=str(last.get('regime', 'UNKNOWN')),
                volatility_regime=str(last.get('volatility_regime', 'UNKNOWN')),
                structural_bias=str(last.get('structural_bias', 'UNKNOWN')),
                regime_strength=regime_strength,
                atr=atr_val if atr_val > 0 else None,
            )

            if atr_val > 0 and signal_idx >= 5:
                signal.sl = strategy.calculate_sl(signal, df, signal_idx, atr_val)
                tp1, tp2 = strategy.calculate_tp(signal, df, signal_idx, atr_val)
                signal.tp1 = tp1
                signal.tp2 = tp2

            # Build notes from gates
            gates_passed = []
            gates_failed = []
            signal.gates_passed = gates_passed
            signal.gates_failed = gates_failed
            signal.notes = (
                f"{signal.direction} signal. "
                f"Confidence: {confidence:.0%}. "
                f"Regime: {signal.regime}."
            )

            return signal, df

        except Exception as e:
            print(f"[StrategyRunner] Error in {strategy.name}: {e}")
            import traceback
            traceback.print_exc()
            return None, None

    @classmethod
    def scan_historical(
        cls,
        strategies: List[BaseStrategy],
        symbol: str,
        timeframe: str,
        candle_df: pd.DataFrame,
        min_confidence_override: Optional[float] = None,
        strict: bool = True,
    ) -> List[SetupSignal]:
        """
        Backtest mode: Walk through the full candle dataset, running each
        strategy once. Pre-processes the DataFrame, runs generate_signals()
        across ALL rows, and extracts SetupSignal objects for every row
        where signal == 1.

        All strategies use the new v3 framework (generate_signals + gate-based).
        Strict mode is the reliable default: a selected strategy either runs in
        full or the backtest fails. Partial strategy sets must never be reported
        as a successful experiment.
        """
        signals = []

        for strategy in strategies:
            if timeframe not in strategy.timeframes:
                continue

            try:
                if not strategy.supports_historical_backtest:
                    raise ValueError(
                        f"{strategy.name} is live-alert-only and does not support "
                        "historical backtesting"
                    )
                if 'sr' in strategy.required_features:
                    raise ValueError(
                        f"{strategy.name} requires S/R features whose batch "
                        "historical pipeline is not yet prefix-causal"
                    )

                df = candle_df.copy()
                df = strategy.pre_process(df, symbol=symbol, timeframe=timeframe)

                df = strategy.generate_signals(df)

                # Extract signals from all rows
                signal_rows = df[df['signal'] == 1]

                for idx, row in signal_rows.iterrows():
                    confidence = row.get('confidence', 0)
                    threshold = min_confidence_override or strategy.min_confidence
                    if confidence < threshold:
                        continue

                    direction = row.get('direction', None)
                    if direction not in ('LONG', 'SHORT'):
                        continue

                    # Find integer position of this row in the DataFrame
                    pos_idx = df.index.get_loc(idx)

                    # Entry at next bar's open (handled by BacktestEngine now)
                    # Here we set the signal's entry to the signal bar's close
                    # and BacktestEngine adjusts it to next bar's open
                    entry = float(row['close'])
                    atr_val = float(row['atr']) if 'atr' in df.columns and pd.notna(row.get('atr')) else 0.0

                    regime = str(row.get('regime', 'UNKNOWN'))
                    signal_time = df.iloc[pos_idx]['open_time']

                    regime_strength_value = row.get('regime_strength')
                    regime_strength = (
                        float(regime_strength_value)
                        if pd.notna(regime_strength_value) else None
                    )

                    signal = SetupSignal(
                        strategy_name=strategy.name,
                        symbol=symbol,
                        timeframe=timeframe,
                        direction=direction,
                        confidence=round(float(confidence), 4),
                        entry=entry,
                        timestamp=signal_time,
                        regime=regime,
                        volatility_regime=str(row.get('volatility_regime', 'UNKNOWN')),
                        structural_bias=str(row.get('structural_bias', 'UNKNOWN')),
                        regime_strength=regime_strength,
                        atr=atr_val if atr_val > 0 else None,
                    )

                    if atr_val > 0 and pos_idx >= 5:
                        signal.sl = strategy.calculate_sl(signal, df, pos_idx, atr_val)
                        tp1, tp2 = strategy.calculate_tp(signal, df, pos_idx, atr_val)
                        signal.tp1 = tp1
                        signal.tp2 = tp2

                    if (signal.sl is not None and signal.tp1 is not None
                            and signal.tp2 is not None):
                        signals.append(signal)

            except Exception as e:
                if strict:
                    raise RuntimeError(
                        f"Historical scan failed for {strategy.name}: {e}"
                    ) from e
                print(f"[StrategyRunner] Error in historical scan for {strategy.name}: {e}")
                continue

        return signals
