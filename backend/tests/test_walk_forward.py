"""Walk-forward validation regression and leakage tests."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from app import create_app
from app.core.backtest_engine import BacktestEngine
from app.core.base_strategy import BaseStrategy, SetupSignal
from app.core.strategy_loader import registry
from app.models.db import Candle, ResearchCandidateOutcome, ResearchExperiment, db
from app.research.folds import plan_anchored_folds
from app.research.manifest import WalkForwardManifest
from app.research.metrics import benjamini_hochberg, candidate_metrics
from app.research.walk_forward import WalkForwardService


class RepeatingResearchStrategy(BaseStrategy):
    name = 'Repeating Research Strategy'
    version = 'test-1'
    timeframes = ['1h']
    min_confidence = 0.5

    @classmethod
    def get_required_lookback(cls):
        return 5

    @classmethod
    def get_min_candles(cls):
        return 5

    @classmethod
    def pre_process(cls, df, symbol, timeframe):
        df = df.copy()
        df['atr'] = 1.0
        df['regime'] = 'TRENDING_UP'
        df['volatility_regime'] = 'NORMAL'
        df['structural_bias'] = 'BULLISH'
        df['regime_strength'] = 0.8
        return df

    def generate_signals(self, df):
        df = df.copy()
        df['signal'] = 0
        df.loc[(df.index >= 5) & (df.index % 5 == 0), 'signal'] = 1
        df['direction'] = 'LONG'
        df['confidence'] = 0.8
        return df

    def calculate_sl(self, signal, df, signal_idx, atr):
        return signal.entry - 2.0

    def calculate_tp(self, signal, df, signal_idx, atr):
        return signal.entry + 2.0, signal.entry + 3.0


def _manifest():
    return {
        'name': 'repeating-1h-test',
        'hypothesis': 'A deterministic positive fixture should pass OOS mechanics.',
        'family_id': 'repeating-test-family',
        'variant_id': 'baseline',
        'strategy_name': RepeatingResearchStrategy.name,
        'symbol': 'BTCUSDT',
        'timeframe': '1h',
        'start_date': '2025-01-01T05:00:00Z',
        'end_date': '2025-01-17T16:00:00Z',
        'train_bars': 40,
        'test_bars': 20,
        'step_bars': 20,
        'holdout_bars': 60,
        'min_folds': 2,
        'initial_capital': 10000,
        'risk_pct': 0.01,
        'cost_scenarios': [{'name': 'base', 'bps_per_side': 0}],
        'bootstrap_repetitions': 100,
        'bootstrap_seed': 7,
    }


def test_fold_plan_never_overlaps_oos_or_consumes_holdout():
    plan = plan_anchored_folds(
        total_evaluation_bars=400,
        train_bars=40,
        test_bars=20,
        step_bars=20,
        holdout_bars=60,
        label_span_bars=25,
        min_folds=5,
    )
    owned = set()
    for fold in plan.folds:
        assert fold.train_end_idx <= fold.purge_start_idx < fold.purge_end_idx <= fold.test_start_idx
        assert fold.test_end_idx + plan.label_span_bars <= plan.holdout_start_idx
        for index in range(fold.test_start_idx, fold.test_end_idx):
            assert index not in owned
            owned.add(index)
    assert len(plan.folds) == 5
    assert plan.holdout_end_idx == plan.label_tail_start_idx


def test_manifest_hash_is_stable_and_non_overlapping_steps_are_required():
    manifest = WalkForwardManifest.from_dict(_manifest())
    assert manifest.sha256 == WalkForwardManifest.from_dict(_manifest()).sha256
    invalid = _manifest() | {'step_bars': 10}
    with pytest.raises(ValueError, match='step_bars equal to test_bars'):
        WalkForwardManifest.from_dict(invalid)


def test_candidate_outcomes_reuse_single_trade_execution_semantics():
    candles = pd.DataFrame({
        'open_time': [datetime(2025, 1, 1) + timedelta(hours=index) for index in range(30)],
        'open': [100.0] * 30,
        'high': [100.0, 103.0] + [100.0] * 28,
        'low': [100.0, 99.0] + [100.0] * 28,
        'close': [100.0] * 30,
    })
    signal = SetupSignal(
        strategy_name='Fixture', symbol='BTCUSDT', timeframe='1h', direction='LONG',
        confidence=0.8, entry=100.0, sl=98.0, tp1=102.0, tp2=103.0,
        timestamp=candles['open_time'].iloc[0], regime='TRENDING_UP',
    )
    policy_trade = BacktestEngine.simulate_trades(
        [signal], candles, initial_capital=10000, risk_pct=0.01, slippage_bps=0,
    )[0]
    candidate = BacktestEngine.simulate_candidate_outcomes(
        [signal], candles, initial_capital=10000, risk_pct=0.01, slippage_bps=0,
    )[0]
    assert candidate['status'] == 'EVALUATED'
    assert candidate['outcome'] == policy_trade['outcome']
    assert candidate['entry_price'] == policy_trade['entry_price']
    assert candidate['exit_price'] == policy_trade['exit_price']
    assert candidate['net_r'] == policy_trade['rr_ratio']
    assert candidate['offered_tp1_r'] == pytest.approx(1.0)


def test_candidate_outcome_cannot_read_past_its_label_horizon():
    candles = pd.DataFrame({
        'open_time': [datetime(2025, 1, 1) + timedelta(hours=index) for index in range(35)],
        'open': [100.0] * 35,
        'high': [100.0] * 35,
        'low': [100.0] * 35,
        'close': [100.0] * 35,
    })
    signal = SetupSignal(
        strategy_name='Fixture', symbol='BTCUSDT', timeframe='1h', direction='LONG',
        confidence=0.8, entry=100.0, sl=98.0, tp1=102.0, tp2=103.0,
        timestamp=candles['open_time'].iloc[0],
    )
    baseline = BacktestEngine.simulate_candidate_outcomes(
        [signal], candles, initial_capital=10000, risk_pct=0.01, slippage_bps=0,
    )[0]
    tampered = candles.copy()
    # The terminal candidate window ends at index 24. A large future move must
    # not retrospectively change this candidate's label or excursions.
    tampered.loc[30, ['high', 'low', 'close']] = [10000.0, 1.0, 5000.0]
    replayed = BacktestEngine.simulate_candidate_outcomes(
        [signal], tampered, initial_capital=10000, risk_pct=0.01, slippage_bps=0,
    )[0]
    assert replayed == baseline


def test_candidate_metrics_are_deterministic_and_track_sample_size():
    outcomes = [
        {
            'status': 'EVALUATED', 'signal_time': datetime(2025, 1, 1) + timedelta(days=index),
            'net_r': 1.0 if index % 3 else -0.5, 'outcome': 'HIT_TP1',
            'offered_tp1_r': 1.5, 'offered_tp2_r': 3.0, 'mfe_r': 1.0, 'mae_r': -0.2,
        }
        for index in range(40)
    ]
    first_metrics, first_uncertainty = candidate_metrics(outcomes, bootstrap_repetitions=100, bootstrap_seed=42)
    second_metrics, second_uncertainty = candidate_metrics(outcomes, bootstrap_repetitions=100, bootstrap_seed=42)
    assert first_metrics == second_metrics
    assert first_uncertainty == second_uncertainty
    assert first_metrics['evaluated_candidates'] == 40
    assert first_metrics['net_win_rate'] == 65.0
    assert first_uncertainty['mean_net_r_ci_95'] is not None
    assert benjamini_hochberg([0.01, 0.04, None]) == [0.02, 0.04, None]


@pytest.fixture
def research_app(monkeypatch):
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
    })
    monkeypatch.setattr(registry, 'get_by_name', lambda name: (
        RepeatingResearchStrategy() if name == RepeatingResearchStrategy.name else None
    ))
    with app.app_context():
        base = datetime(2025, 1, 1)
        candles = [
            Candle(
                symbol='BTCUSDT', timeframe='1h', open_time=base + timedelta(hours=index),
                open=100.0, high=103.0, low=99.0, close=100.0,
                volume=1000.0, is_closed=True,
            )
            for index in range(400)
        ]
        db.session.add_all(candles)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


def test_walk_forward_lifecycle_persists_oos_and_seals_holdout(research_app):
    with research_app.app_context():
        preview = WalkForwardService.preview(_manifest())
        assert len(preview['folds']) >= 2
        experiment, created = WalkForwardService.create(_manifest())
        assert created
        assert WalkForwardService.create(_manifest())[1] is False

        completed = WalkForwardService.execute(experiment.id)
        assert completed.status == 'WALK_FORWARD_COMPLETE'
        assert completed.decision == 'PROVISIONAL'
        assert completed.holdout_revealed_at is None
        assert ResearchCandidateOutcome.query.filter_by(experiment_id=experiment.id).count() > 0
        stored = ResearchCandidateOutcome.query.filter_by(experiment_id=experiment.id).first()
        assert stored.regime_strength == pytest.approx(0.8)
        assert stored.atr == pytest.approx(1.0)

        revealed = WalkForwardService.reveal_holdout(experiment.id, revealed_by='test')
        assert revealed.status == 'COMPLETED'
        assert revealed.holdout_revealed_at is not None
        detail = WalkForwardService.detail(experiment.id)
        assert any(fold['kind'] == 'HOLDOUT' for fold in detail['folds'])
        assert db.session.get(ResearchExperiment, experiment.id).decision == 'PROVISIONAL'


def test_research_api_previews_and_creates_sealed_experiment(research_app):
    client = research_app.test_client()
    preview = client.post('/api/research/experiments/preview', json=_manifest())
    assert preview.status_code == 200
    created = client.post('/api/research/experiments', json=_manifest())
    assert created.status_code == 201
    assert created.get_json()['experiment']['status'] == 'SEALED'
