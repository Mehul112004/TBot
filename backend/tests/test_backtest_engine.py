import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from app.core.backtest_engine import BacktestEngine
from app.core.base_strategy import BaseStrategy, SetupSignal
from app.models.db import db, Candle

class MockStrategy(BaseStrategy):
    name = "Mock Strategy"
    timeframes = ["1h"]
    
    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        # We don't actually run this in the vectorized tests below, 
        # but needed to satisfy the type hits if we test full run()
        pass


@pytest.fixture
def sample_candle_df():
    # 5 candles, 1h interval
    times = [datetime(2025, 1, 1, 0) + timedelta(hours=i) for i in range(5)]
    data = {
        'open_time': times,
        'open': [100, 105, 110, 108, 112],
        'high': [106, 112, 115, 114, 120],
        'low': [98, 104, 107, 105, 110],
        'close': [105, 110, 108, 112, 118],
        'volume': [10, 15, 12, 20, 25]
    }
    return pd.DataFrame(data)


def test_simulate_trades_long_hit_tp():
    # Trade entry at candle 0; TP2 wins over TP1 on same bar (momentum carry-through).
    # With 10 bps slippage, pnl = gross_pnl - slippage_cost.
    candle_df = pd.DataFrame({
        'open_time': [datetime(2025, 1, 1, 0, 0) + timedelta(hours=i) for i in range(4)],
        'open': [100, 100, 100, 100],
        'high': [100, 105, 120, 110],  # Bar 2 high=120 hits both TP1(110) and TP2(115)
        'low': [100, 95, 95, 95],
        'close': [100, 100, 100, 100],
    })
    
    signals = [
        SetupSignal(
            strategy_name="Mock", symbol="BTCUSDT", timeframe="1h",
            direction="LONG", confidence=1.0, entry=100.0,
            sl=90.0, tp1=110.0, tp2=115.0,
            timestamp=candle_df['open_time'].iloc[0]
        )
    ]
    
    trades = BacktestEngine.simulate_trades(signals, candle_df, initial_capital=1000, risk_pct=0.01)
    assert len(trades) == 1
    trade = trades[0]
    
    # TP2 wins — both hit on same bar, TP2 has higher priority (strong momentum)
    assert trade['outcome'] == 'HIT_TP2'
    assert trade['exit_price'] == 115.0
    # gross_rr = (115-100) / (100-90) = 1.5
    assert trade['rr_ratio'] == pytest.approx(1.5, abs=1e-6)
    # position_size = (1000*0.01) / 10 = 1.0
    # gross_pnl = 1.0 * (115-100) = 15.0
    # slippage = 1.0 * 0.001 * (100 + 115) = 0.215
    # net pnl = 15.0 - 0.215 = 14.785
    assert trade['pnl'] == pytest.approx(14.79, abs=0.01)


def test_simulate_trades_short_hit_sl():
    # Trade entry at candle 0, SL hit at candle 2 (entry bar is 1, forward from bar 2).
    # With 10 bps slippage, pnl = gross_pnl - slippage_cost.
    candle_df = pd.DataFrame({
        'open_time': [datetime(2025, 1, 1, 0, 0) + timedelta(hours=i) for i in range(3)],
        'open': [100, 100, 100],
        'high': [100, 100, 115],  # Bar 2 high=115 hits SHORT SL (110)
        'low': [100, 95, 95],
        'close': [100, 100, 100],
    })
    
    signals = [
        SetupSignal(
            strategy_name="Mock", symbol="BTCUSDT", timeframe="1h",
            direction="SHORT", confidence=1.0, entry=100.0,
            sl=110.0, tp1=90.0, tp2=85.0,
            timestamp=candle_df['open_time'].iloc[0]
        )
    ]
    
    trades = BacktestEngine.simulate_trades(signals, candle_df, initial_capital=1000, risk_pct=0.01)
    trade = trades[0]
    
    assert trade['outcome'] == 'HIT_SL'
    assert trade['exit_price'] == 110.0
    # position_size = 10/10 = 1.0, gross_pnl = 1.0*(100-110) = -10
    # slippage = 1.0 * 0.001 * (100+110) = 0.21
    # net pnl = -10 - 0.21 = -10.21
    assert trade['pnl'] == pytest.approx(-10.21, abs=0.01)


def test_simulate_trades_same_bar_conflict():
    # Both SL and TP breached on the exact same forward bar.
    # SL always wins (conservative rule).
    candle_df = pd.DataFrame({
        'open_time': [datetime(2025, 1, 1), datetime(2025, 1, 2), datetime(2025, 1, 3)],
        'open': [100, 100, 100],
        'high': [100, 100, 120],  # Bar 2 hits TP (115)
        'low': [100, 100, 80],    # Bar 2 hits SL (90)
        'close': [100, 100, 100],
    })
    
    signals = [
        SetupSignal(
            strategy_name="Mock", symbol="BTCUSDT", timeframe="1h",
            direction="LONG", confidence=1.0, entry=100.0,
            sl=90.0, tp1=110.0, tp2=115.0,
            timestamp=candle_df['open_time'].iloc[0]
        )
    ]
    
    trades = BacktestEngine.simulate_trades(signals, candle_df, initial_capital=1000, risk_pct=0.01)
    trade = trades[0]
    
    # SL wins on same-bar conflict
    assert trade['outcome'] == 'HIT_SL'


def test_compute_metrics():
    trades = [
        {'outcome': 'HIT_TP1', 'pnl': 20.0, 'rr_ratio': 2.0, 'duration_mins': 60},
        {'outcome': 'HIT_SL', 'pnl': -10.0, 'rr_ratio': 0.0, 'duration_mins': 30},
        {'outcome': 'HIT_TP2', 'pnl': 30.0, 'rr_ratio': 3.0, 'duration_mins': 120},
        {'outcome': 'EXPIRED', 'pnl': -5.0, 'rr_ratio': 0.0, 'duration_mins': 240},
    ]
    
    # Equity curve is just roughly simulated
    eq_curve = [
        {'value': 1000},
        {'value': 1020},
        {'value': 1010},
        {'value': 1040},
        {'value': 1035},
    ]
    
    metrics = BacktestEngine.compute_metrics(trades, initial_capital=1000, equity_curve=eq_curve)
    
    assert metrics['total_trades'] == 4
    assert metrics['win_rate'] == 50.0  # (2 / 4) * 100
    assert metrics['total_pnl'] == 35.0 # 20 - 10 + 30 - 5
    assert metrics['profit_factor'] == pytest.approx(50.0 / 15.0, rel=1e-3)  # Gross win / gross loss
    assert metrics['avg_rr'] == 2.5     # (2.0 + 3.0) / 2
    assert metrics['max_drawdown'] == 10.0 # From 1020 down to 1010
