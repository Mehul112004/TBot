import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from app.core.backtest_engine import BacktestEngine
from app.core.base_strategy import BaseStrategy, SetupSignal
from app.models.db import db, Candle, BacktestRun

class MockStrategy(BaseStrategy):
    name = "Mock Strategy"
    timeframes = ["1h"]
    
    def generate_signals(self, df):
        df = df.copy()
        df['signal'] = 0
        if len(df) > 200:
            df.loc[df.index[200], 'signal'] = 1
        df['direction'] = 'LONG'
        df['confidence'] = 1.0
        return df

    def calculate_sl(self, signal, df, signal_idx, atr):
        return signal.entry - 10

    def calculate_tp(self, signal, df, signal_idx, atr):
        return signal.entry + 15, signal.entry + 30


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
    # Trade entry at candle 0; a continuous intrabar move reaches TP1 first.
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
    
    assert trade['outcome'] == 'HIT_TP1'
    assert trade['exit_price'] == 110.0
    # position_size = (1000*0.01) / 10 = 1.0
    # gross_pnl = 10, cost = 0.21, net pnl = 9.79, net R = 0.979
    assert trade['pnl'] == pytest.approx(9.79, abs=0.01)
    assert trade['rr_ratio'] == pytest.approx(0.979, abs=1e-6)


def test_simulate_trades_short_hit_sl():
    # Trade entry at candle 0, SL hit at candle 2.
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


def test_entry_candle_is_evaluated():
    """A stop hit after the next-open fill on that same candle cannot be ignored."""
    candle_df = pd.DataFrame({
        'open_time': [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(3)],
        'open': [100, 100, 100],
        'high': [100, 105, 100],
        'low': [100, 85, 100],
        'close': [100, 95, 100],
    })
    signal = SetupSignal(
        strategy_name="Mock", symbol="BTCUSDT", timeframe="1h",
        direction="LONG", confidence=1.0, entry=100.0,
        sl=90.0, tp1=110.0, tp2=120.0,
        timestamp=candle_df['open_time'].iloc[0],
    )
    trade = BacktestEngine.simulate_trades(
        [signal], candle_df, initial_capital=1000, risk_pct=0.01,
    )[0]
    assert trade['outcome'] == 'HIT_SL'
    assert trade['exit_time'] == candle_df['open_time'].iloc[1]


def test_open_position_and_post_exit_cooldown_prevent_equity_time_travel():
    times = [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(14)]
    candle_df = pd.DataFrame({
        'open_time': times,
        'open': [100.0] * 14,
        'high': [101.0] * 4 + [111.0] + [101.0] * 5 + [111.0] + [101.0] * 3,
        'low': [99.0] * 14,
        'close': [100.0] * 14,
    })

    def signal_at(index):
        return SetupSignal(
            strategy_name="Mock", symbol="BTCUSDT", timeframe="1h",
            direction="LONG", confidence=1.0, entry=100.0,
            sl=90.0, tp1=110.0, tp2=120.0, timestamp=times[index],
        )

    audit = {}
    trades = BacktestEngine.simulate_trades(
        [signal_at(0), signal_at(1), signal_at(9)],
        candle_df, initial_capital=1000, risk_pct=0.01, audit=audit,
    )
    assert len(trades) == 2
    assert trades[0]['exit_time'] == times[4]
    assert trades[1]['entry_time'] == times[10]
    assert trades[1]['equity_at_entry'] == pytest.approx(1009.79)
    assert [trade['trade_number'] for trade in trades] == [1, 2]
    assert audit == {
        'input_signals': 3,
        'accepted_trades': 2,
        'rejections': {'position_open_or_post_exit_cooldown': 1},
    }


def test_signal_timestamp_must_match_exact_candle():
    candle_df = pd.DataFrame({
        'open_time': [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(3)],
        'open': [100] * 3, 'high': [101] * 3, 'low': [99] * 3, 'close': [100] * 3,
    })
    signal = SetupSignal(
        strategy_name="Mock", symbol="BTCUSDT", timeframe="1h",
        direction="LONG", confidence=1.0, entry=100.0,
        sl=90.0, tp1=110.0, tp2=120.0,
        timestamp=datetime(2025, 1, 1, 0, 30),
    )
    with pytest.raises(ValueError, match="does not match a candle exactly"):
        BacktestEngine.simulate_trades(
            [signal], candle_df, initial_capital=1000, risk_pct=0.01,
        )


def test_invalid_directional_levels_fail_closed():
    candle_df = pd.DataFrame({
        'open_time': [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(3)],
        'open': [100] * 3, 'high': [101] * 3, 'low': [99] * 3, 'close': [100] * 3,
    })
    signal = SetupSignal(
        strategy_name="Mock", symbol="BTCUSDT", timeframe="1h",
        direction="LONG", confidence=1.0, entry=100.0,
        sl=105.0, tp1=110.0, tp2=120.0,
        timestamp=candle_df['open_time'].iloc[0],
    )
    with pytest.raises(ValueError, match="Invalid LONG level ordering"):
        BacktestEngine.simulate_trades(
            [signal], candle_df, initial_capital=1000, risk_pct=0.01,
        )


def test_next_open_gap_does_not_move_structural_levels():
    candle_df = pd.DataFrame({
        'open_time': [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(3)],
        'open': [100, 105, 105],
        'high': [101, 106, 106],
        'low': [99, 104, 104],
        'close': [100, 105, 105],
    })
    signal = SetupSignal(
        strategy_name="Mock", symbol="BTCUSDT", timeframe="1h",
        direction="LONG", confidence=1.0, entry=100.0,
        sl=90.0, tp1=110.0, tp2=120.0,
        timestamp=candle_df['open_time'].iloc[0],
    )

    # At a 105 fill the fixed levels offer only 5 reward for 15 risk, so the
    # 1R gate rejects it. Shifting SL/TP by +5 would fabricate a valid trade.
    assert BacktestEngine.simulate_trades(
        [signal], candle_df, initial_capital=1000, risk_pct=0.01,
    ) == []


def test_candle_validation_rejects_gaps_and_unclosed_rows():
    df = pd.DataFrame({
        'open_time': [datetime(2025, 1, 1), datetime(2025, 1, 1, 2)],
        'open': [100, 100], 'high': [101, 101], 'low': [99, 99],
        'close': [100, 100], 'volume': [10, 10], 'is_closed': [True, True],
    })
    with pytest.raises(ValueError, match="Candle gap detected"):
        BacktestEngine.validate_candle_data(df, timeframe='1h')

    df.loc[1, 'open_time'] = datetime(2025, 1, 1, 1)
    df.loc[1, 'is_closed'] = False
    with pytest.raises(ValueError, match="not marked closed"):
        BacktestEngine.validate_candle_data(df, timeframe='1h')


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
    assert metrics['max_drawdown_pct'] == pytest.approx(0.98, abs=0.01)


def test_metrics_use_net_profitability_and_pointwise_drawdown_percentage():
    trades = [
        {'outcome': 'HIT_TP1', 'pnl': -0.25, 'rr_ratio': -0.025, 'duration_mins': 60},
        {'outcome': 'EXPIRED', 'pnl': 2.0, 'rr_ratio': 0.2, 'duration_mins': 60},
    ]
    curve = [
        {'value': 100.0}, {'value': 80.0}, {'value': 1000.0}, {'value': 950.0},
    ]
    metrics = BacktestEngine.compute_metrics(trades, 100.0, curve)
    assert metrics['win_rate'] == 50.0
    assert metrics['avg_rr'] == pytest.approx(0.2)
    assert metrics['max_drawdown'] == 50.0
    assert metrics['max_drawdown_pct'] == 20.0


def test_full_run_uses_warmup_and_persists_reproducibility_manifest():
    from app import create_app

    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
    })
    with app.app_context():
        base = datetime(2025, 1, 1)
        candles = []
        for i in range(251):
            candles.append(Candle(
                symbol='BTCUSDT', timeframe='1h',
                open_time=base + timedelta(hours=i),
                open=100, high=101, low=99, close=100,
                volume=1000, is_closed=True,
            ))
        db.session.add_all(candles)
        db.session.commit()

        result = BacktestEngine.run(
            symbol='BTCUSDT', timeframe='1h',
            start_date=base + timedelta(hours=200),
            end_date=base + timedelta(hours=250),
            strategies=[MockStrategy()], strategy_names=['Mock Strategy'],
        )

        assert result['status'] == 'COMPLETED'
        assert result['warmup_candle_count'] == 200
        assert result['candle_count'] == 50
        assert result['simulation_audit']['input_signals'] == 1
        assert len(result['configuration']['data_fingerprint_sha256']) == 64
        stored = db.session.get(BacktestRun, result['run_id'])
        assert stored.to_dict()['configuration']['engine_version'] == '4.0.0'


def test_full_run_fails_when_closed_candle_history_has_a_gap():
    from app import create_app

    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
    })
    with app.app_context():
        base = datetime(2025, 1, 1)
        for i in range(251):
            db.session.add(Candle(
                symbol='BTCUSDT', timeframe='1h',
                open_time=base + timedelta(hours=i),
                open=100, high=101, low=99, close=100,
                volume=1000, is_closed=(i != 220),
            ))
        db.session.commit()

        result = BacktestEngine.run(
            symbol='BTCUSDT', timeframe='1h',
            start_date=base + timedelta(hours=200),
            end_date=base + timedelta(hours=250),
            strategies=[MockStrategy()], strategy_names=['Mock Strategy'],
        )
        assert result['status'] == 'FAILED'
        assert 'Candle gap detected' in result['error']
