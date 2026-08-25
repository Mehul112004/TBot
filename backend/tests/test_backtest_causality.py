"""Regression tests for feature-level lookahead defenses used by backtests."""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.strategies.burner_9_20 import Burner920Strategy
from app.strategies.breakout_retest import BreakoutRetestStrategy
from app.strategies.key_level_reversal import KeyLevelReversalStrategy
from app.strategies.liquidity_sweep import LiquiditySweepStrategy
from app.strategies.trend_following import TrendFollowingStrategy


def test_burner_hidden_divergence_is_not_backdated():
    n = 40
    low = np.linspace(100.0, 104.0, n)
    low[10] = 90.0
    low[20] = 92.0
    high = low + 5.0
    close = np.full(n, 100.0)
    rsi = np.full(n, 55.0)
    rsi[10] = 45.0
    rsi[20] = 35.0

    df = pd.DataFrame({
        'open_time': [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(n)],
        'open': close - 0.2,
        'high': high,
        'low': low,
        'close': close,
        'volume': np.full(n, 1200.0),
        'volume_ma': np.full(n, 1000.0),
        'rsi': rsi,
        'atr': np.full(n, 2.0),
        'adx': np.full(n, 30.0),
        'ema_9': np.full(n, 101.0),
        'ema_20': np.full(n, 99.0),
        'ema_50': np.full(n, 98.0),
        'ema_200': np.full(n, 95.0),
        'regime': ['TRENDING_UP'] * n,
    })

    strategy = Burner920Strategy()
    full = strategy.generate_signals(df)
    prefix = strategy.generate_signals(df.iloc[:26].copy())

    # Pivot 20 requires bars 21..25, so it is unknowable before index 25.
    assert not full.loc[:24, 'hidden_divergence_bullish'].any()
    assert full.loc[25, 'hidden_divergence_bullish']
    assert prefix.iloc[-1]['hidden_divergence_bullish']
    assert full.loc[25, 'confidence'] == prefix.iloc[-1]['confidence']


@pytest.mark.parametrize('strategy', [
    TrendFollowingStrategy(),
    Burner920Strategy(),
    BreakoutRetestStrategy(),
    LiquiditySweepStrategy(),
    KeyLevelReversalStrategy(),
], ids=lambda strategy: strategy.name)
def test_active_historical_strategy_outputs_are_prefix_invariant(strategy):
    """Future candles cannot rewrite a prior signal, score, or regime label."""
    rng = np.random.default_rng(20260822)
    n = 360
    close = 100 + np.cumsum(rng.normal(0, 0.8, n))
    open_ = close + rng.normal(0, 0.3, n)
    df = pd.DataFrame({
        'open_time': [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(n)],
        'open': open_,
        'high': np.maximum(open_, close) + rng.uniform(0.1, 1.5, n),
        'low': np.minimum(open_, close) - rng.uniform(0.1, 1.5, n),
        'close': close,
        'volume': rng.uniform(500, 2000, n),
    })
    timeframe = strategy.timeframes[0]
    full = strategy.generate_signals(
        strategy.pre_process(df, 'BTCUSDT', timeframe)
    )

    for end in range(80, n + 1, 20):
        prefix = strategy.generate_signals(
            strategy.pre_process(df.iloc[:end].copy(), 'BTCUSDT', timeframe)
        )
        assert full.iloc[end - 1]['signal'] == prefix.iloc[-1]['signal']
        assert full.iloc[end - 1]['direction'] == prefix.iloc[-1]['direction']
        assert full.iloc[end - 1]['regime'] == prefix.iloc[-1]['regime']
        assert full.iloc[end - 1]['confidence'] == pytest.approx(
            prefix.iloc[-1]['confidence']
        )
