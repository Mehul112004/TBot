"""Unit tests for the current DataFrame-based StrategyRunner contract."""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.core.base_strategy import BaseStrategy
from app.core.strategy_runner import StrategyRunner


def _make_df(n: int = 320) -> pd.DataFrame:
    np.random.seed(42)
    closes = 100.0 + np.cumsum(np.random.uniform(-0.5, 0.5, n))
    return pd.DataFrame({
        'open_time': [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(n)],
        'open': closes - 0.2,
        'high': closes + 1.0,
        'low': closes - 1.0,
        'close': closes,
        'volume': np.full(n, 1000.0),
    })


class AlwaysSignalStrategy(BaseStrategy):
    name = "Always Signal"
    timeframes = ["1h", "4h"]
    min_confidence = 0.5

    def generate_signals(self, df):
        df = df.copy()
        df['signal'] = 0
        df.loc[df.index >= 50, 'signal'] = 1
        df['direction'] = 'LONG'
        df['confidence'] = 0.7
        return df

    def calculate_sl(self, signal, df, signal_idx, atr):
        return round(signal.entry - 10.0, 8)

    def calculate_tp(self, signal, df, signal_idx, atr):
        return round(signal.entry + 15.0, 8), round(signal.entry + 30.0, 8)


class NeverSignalStrategy(AlwaysSignalStrategy):
    name = "Never Signal"

    def generate_signals(self, df):
        df = super().generate_signals(df)
        df['signal'] = 0
        return df


class CrashingStrategy(AlwaysSignalStrategy):
    name = "Crasher"

    def generate_signals(self, df):
        raise RuntimeError("Intentional crash for testing")


class LowConfidenceStrategy(AlwaysSignalStrategy):
    name = "Low Confidence"
    min_confidence = 0.7

    def generate_signals(self, df):
        df = super().generate_signals(df)
        df['confidence'] = 0.4
        return df


class LiveOnlyStrategy(AlwaysSignalStrategy):
    name = "Live Only"
    supports_historical_backtest = False


class UnsafeSRStrategy(AlwaysSignalStrategy):
    name = "Unsafe S/R"
    required_features = ['sr']


class TestRunSingleScan:
    def test_populates_entry_and_levels(self, monkeypatch):
        df = _make_df()
        monkeypatch.setattr(
            'app.core.data_utils.get_finalized_candles',
            lambda *args, **kwargs: df,
        )
        signal, processed = StrategyRunner.run_single_scan(
            AlwaysSignalStrategy(), "BTCUSDT", "1h"
        )
        assert signal is not None
        assert processed is not None
        assert signal.entry == pytest.approx(df['close'].iloc[-1])
        assert signal.sl == pytest.approx(signal.entry - 10.0)
        assert signal.tp1 == pytest.approx(signal.entry + 15.0)
        assert signal.tp2 == pytest.approx(signal.entry + 30.0)

    def test_catches_live_strategy_exception(self, monkeypatch):
        monkeypatch.setattr(
            'app.core.data_utils.get_finalized_candles',
            lambda *args, **kwargs: _make_df(),
        )
        assert StrategyRunner.run_single_scan(
            CrashingStrategy(), "BTCUSDT", "1h"
        ) == (None, None)

    def test_none_signal_passes_through(self, monkeypatch):
        monkeypatch.setattr(
            'app.core.data_utils.get_finalized_candles',
            lambda *args, **kwargs: _make_df(),
        )
        assert StrategyRunner.run_single_scan(
            NeverSignalStrategy(), "BTCUSDT", "1h"
        ) == (None, None)

    def test_min_confidence_override(self, monkeypatch):
        monkeypatch.setattr(
            'app.core.data_utils.get_finalized_candles',
            lambda *args, **kwargs: _make_df(),
        )
        filtered, _ = StrategyRunner.run_single_scan(
            LowConfidenceStrategy(), "BTCUSDT", "1h"
        )
        accepted, _ = StrategyRunner.run_single_scan(
            LowConfidenceStrategy(), "BTCUSDT", "1h",
            min_confidence_override=0.3,
        )
        assert filtered is None
        assert accepted is not None


class TestScanHistorical:
    def test_produces_timestamped_signals(self):
        df = _make_df(100)
        signals = StrategyRunner.scan_historical(
            [AlwaysSignalStrategy()], "BTCUSDT", "1h", df
        )
        assert len(signals) == 50
        assert all(signal.timestamp in set(df['open_time']) for signal in signals)

    def test_respects_timeframe_filter(self):
        signals = StrategyRunner.scan_historical(
            [AlwaysSignalStrategy()], "BTCUSDT", "1d", _make_df(100)
        )
        assert signals == []

    def test_strategy_error_fails_closed_by_default(self):
        with pytest.raises(RuntimeError, match="Historical scan failed for Crasher"):
            StrategyRunner.scan_historical(
                [CrashingStrategy(), AlwaysSignalStrategy()],
                "BTCUSDT", "1h", _make_df(100),
            )

    def test_non_strict_mode_is_explicit(self):
        signals = StrategyRunner.scan_historical(
            [CrashingStrategy(), AlwaysSignalStrategy()],
            "BTCUSDT", "1h", _make_df(100), strict=False,
        )
        assert len(signals) == 50

    @pytest.mark.parametrize(
        'strategy,error',
        [
            (LiveOnlyStrategy(), 'live-alert-only'),
            (UnsafeSRStrategy(), 'not yet prefix-causal'),
        ],
    )
    def test_non_causal_strategy_modes_are_rejected(self, strategy, error):
        with pytest.raises(RuntimeError, match=error):
            StrategyRunner.scan_historical(
                [strategy], "BTCUSDT", "1h", _make_df(100)
            )
