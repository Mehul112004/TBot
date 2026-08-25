"""Persisted anchored walk-forward execution for frozen TBot strategies."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid

import pandas as pd

from app.core.backtest_engine import BacktestEngine
from app.core.data_utils import TIMEFRAME_MS
from app.core.strategy_loader import registry
from app.core.strategy_runner import StrategyRunner
from app.models.db import (
    db,
    Candle,
    ResearchCandidateOutcome,
    ResearchEvaluationRun,
    ResearchExperiment,
    ResearchFold,
    ResearchMetricSlice,
    ResearchTrial,
)
from app.research.folds import FoldPlan, FoldSpec, plan_anchored_folds
from app.research.manifest import WalkForwardManifest
from app.research.metrics import (
    benjamini_hochberg,
    candidate_metrics,
    final_holdout_decision,
    preliminary_decision,
)


class WalkForwardService:
    """Owns research lifecycle state above the atomic backtest engine."""

    LABEL_SPAN_BARS = 1 + max(8, 24)  # next-open delay + current longest expiry
    METRIC_SCHEMA_VERSION = 'candidate-quality-metrics-v1'

    @classmethod
    def _strategy_for_manifest(cls, manifest: WalkForwardManifest):
        strategy = registry.get_by_name(manifest.strategy_name)
        if strategy is None:
            raise ValueError(f"Strategy not found: {manifest.strategy_name}")
        if manifest.timeframe not in strategy.timeframes:
            raise ValueError(
                f"{manifest.strategy_name} does not support {manifest.timeframe}"
            )
        if not strategy.supports_historical_backtest:
            raise ValueError(
                f"{manifest.strategy_name} is live-alert-only and cannot be walk-forward tested"
            )
        if 'sr' in strategy.required_features:
            raise ValueError(
                f"{manifest.strategy_name} requires S/R features whose batch historical "
                "pipeline is not yet prefix-causal"
            )
        return strategy

    @classmethod
    def _load_data(cls, manifest: WalkForwardManifest, strategy):
        timeframe_ms = TIMEFRAME_MS.get(manifest.timeframe)
        if timeframe_ms is None:
            raise ValueError(f"Unknown timeframe: {manifest.timeframe}")
        warmup_bars = strategy.get_required_lookback()
        warmup_start = manifest.start_date - timedelta(milliseconds=timeframe_ms * warmup_bars)
        candles = (
            Candle.query
            .filter_by(symbol=manifest.symbol, timeframe=manifest.timeframe)
            .filter(Candle.is_closed.is_(True))
            .filter(Candle.open_time >= warmup_start)
            .filter(Candle.open_time <= manifest.end_date)
            .order_by(Candle.open_time.asc())
            .all()
        )
        if not candles:
            raise ValueError('No closed candle data found for the requested experiment')

        frame = pd.DataFrame([candle.to_dict() for candle in candles])
        frame['open_time'] = pd.to_datetime(frame['open_time'], errors='coerce', utc=True).dt.tz_localize(None)
        end_timestamp = BacktestEngine._utc_naive_timestamp(manifest.end_date)
        frame = frame[
            frame['open_time'] + pd.Timedelta(milliseconds=timeframe_ms) <= end_timestamp
        ]
        frame = BacktestEngine.validate_candle_data(
            frame,
            timeframe=manifest.timeframe,
            require_volume=True,
            check_gaps=True,
        )
        start_timestamp = BacktestEngine._utc_naive_timestamp(manifest.start_date)
        warmup = frame[frame['open_time'] < start_timestamp]
        evaluation = frame[frame['open_time'] >= start_timestamp].reset_index(drop=True)
        if len(warmup) < warmup_bars:
            raise ValueError(
                f"Insufficient warm-up data: {len(warmup)} closed candles before "
                f"start_date (need {warmup_bars})"
            )
        if len(evaluation) <= cls.LABEL_SPAN_BARS:
            raise ValueError('Insufficient evaluation data after reserving the label horizon')

        analysis = pd.concat([warmup.tail(warmup_bars), evaluation], ignore_index=True)
        fingerprint_cols = ['open_time', 'open', 'high', 'low', 'close', 'volume']
        fingerprints = pd.util.hash_pandas_object(analysis[fingerprint_cols], index=False).values
        fingerprint = hashlib.sha256(fingerprints.tobytes()).hexdigest()
        return analysis, evaluation, warmup_bars, fingerprint

    @classmethod
    def _plan(cls, manifest: WalkForwardManifest, evaluation: pd.DataFrame) -> FoldPlan:
        return plan_anchored_folds(
            total_evaluation_bars=len(evaluation),
            train_bars=manifest.train_bars,
            test_bars=manifest.test_bars,
            step_bars=manifest.step_bars,
            holdout_bars=manifest.holdout_bars,
            label_span_bars=cls.LABEL_SPAN_BARS,
            min_folds=manifest.min_folds,
        )

    @staticmethod
    def _date_at(evaluation: pd.DataFrame, index: int) -> datetime:
        return pd.Timestamp(evaluation.iloc[index]['open_time']).to_pydatetime()

    @classmethod
    def preview(cls, raw_manifest: dict) -> dict:
        """Validate scope/data and return folds without calculating outcomes."""
        manifest = WalkForwardManifest.from_dict(raw_manifest)
        strategy = cls._strategy_for_manifest(manifest)
        _, evaluation, warmup_bars, fingerprint = cls._load_data(manifest, strategy)
        plan = cls._plan(manifest, evaluation)
        return cls._preview_payload(manifest, strategy, evaluation, plan, warmup_bars, fingerprint)

    @classmethod
    def _preview_payload(
        cls,
        manifest: WalkForwardManifest,
        strategy,
        evaluation: pd.DataFrame,
        plan: FoldPlan,
        warmup_bars: int,
        fingerprint: str,
    ) -> dict:
        folds = []
        for fold in plan.folds:
            folds.append({
                'fold_number': fold.fold_number,
                'train_start': cls._date_at(evaluation, fold.train_start_idx).isoformat() + 'Z',
                'train_end': cls._date_at(evaluation, fold.train_end_idx).isoformat() + 'Z',
                'purge_start': cls._date_at(evaluation, fold.purge_start_idx).isoformat() + 'Z',
                'purge_end': cls._date_at(evaluation, fold.purge_end_idx).isoformat() + 'Z',
                'test_start': cls._date_at(evaluation, fold.test_start_idx).isoformat() + 'Z',
                'test_end': cls._date_at(evaluation, fold.test_end_idx).isoformat() + 'Z',
            })
        return {
            'manifest': manifest.to_dict(),
            'manifest_sha256': manifest.sha256,
            'strategy_version': strategy.version,
            'engine_version': BacktestEngine.ENGINE_VERSION,
            'evaluation_candle_count': len(evaluation),
            'warmup_bars': warmup_bars,
            'label_span_bars': cls.LABEL_SPAN_BARS,
            'data_fingerprint_sha256': fingerprint,
            'folds': folds,
            'holdout': {
                'start': cls._date_at(evaluation, plan.holdout_start_idx).isoformat() + 'Z',
                'end': cls._date_at(evaluation, plan.holdout_end_idx).isoformat() + 'Z',
                'label_tail_start': cls._date_at(evaluation, plan.label_tail_start_idx).isoformat() + 'Z',
                'status': 'SEALED',
            },
        }

    @classmethod
    def create(cls, raw_manifest: dict) -> tuple[ResearchExperiment, bool]:
        manifest = WalkForwardManifest.from_dict(raw_manifest)
        existing = ResearchExperiment.query.filter_by(manifest_sha256=manifest.sha256).first()
        if existing is not None:
            return existing, False

        strategy = cls._strategy_for_manifest(manifest)
        _, evaluation, warmup_bars, fingerprint = cls._load_data(manifest, strategy)
        plan = cls._plan(manifest, evaluation)
        experiment = ResearchExperiment(
            id=str(uuid.uuid4()),
            name=manifest.name,
            hypothesis=manifest.hypothesis,
            family_id=manifest.family_id,
            variant_id=manifest.variant_id,
            manifest_json=json.dumps(manifest.to_dict(), sort_keys=True),
            manifest_sha256=manifest.sha256,
            status='SEALED',
            engine_version=BacktestEngine.ENGINE_VERSION,
            strategy_version=strategy.version,
            data_fingerprint_sha256=fingerprint,
            summary_json=json.dumps({
                'preview': cls._preview_payload(
                    manifest, strategy, evaluation, plan, warmup_bars, fingerprint,
                ),
                'metric_schema_version': cls.METRIC_SCHEMA_VERSION,
            }, sort_keys=True),
        )
        db.session.add(experiment)
        db.session.add(ResearchTrial(
            id=str(uuid.uuid4()),
            experiment_id=experiment.id,
            family_id=manifest.family_id,
            variant_id=manifest.variant_id,
            hypothesis=manifest.hypothesis,
        ))
        db.session.commit()
        return experiment, True

    @classmethod
    def _get_experiment(cls, experiment_id: str) -> ResearchExperiment:
        experiment = db.session.get(ResearchExperiment, experiment_id)
        if experiment is None:
            raise ValueError('Research experiment not found')
        return experiment

    @classmethod
    def _fold_model(cls, experiment: ResearchExperiment, kind: str, fold: FoldSpec, evaluation: pd.DataFrame, fingerprint: str):
        model = (
            ResearchFold.query
            .filter_by(experiment_id=experiment.id, kind=kind, fold_number=fold.fold_number)
            .first()
        )
        if model is not None:
            return model
        model = ResearchFold(
            id=str(uuid.uuid4()),
            experiment_id=experiment.id,
            fold_number=fold.fold_number,
            kind=kind,
            train_start=cls._date_at(evaluation, fold.train_start_idx) if fold.train_start_idx >= 0 else None,
            train_end=cls._date_at(evaluation, fold.train_end_idx) if fold.train_end_idx >= 0 else None,
            purge_start=cls._date_at(evaluation, fold.purge_start_idx) if fold.purge_start_idx >= 0 else None,
            purge_end=cls._date_at(evaluation, fold.purge_end_idx) if fold.purge_end_idx >= 0 else None,
            test_start=cls._date_at(evaluation, fold.test_start_idx),
            test_end=cls._date_at(evaluation, fold.test_end_idx),
            status='QUEUED',
            data_fingerprint_sha256=fingerprint,
            configuration_json=json.dumps(fold.to_dict(), sort_keys=True),
        )
        db.session.add(model)
        db.session.commit()
        return model

    @classmethod
    def _signals_for_fold(
        cls,
        strategy,
        manifest: WalkForwardManifest,
        analysis: pd.DataFrame,
        evaluation: pd.DataFrame,
        warmup_bars: int,
        fold: FoldSpec,
    ) -> tuple[list, pd.DataFrame]:
        # The signal calculation stops at test_end. Label-tail candles are only
        # passed to the outcome replay after detection; they never become input
        # to feature calculation for the fold's test candidates.
        scan_frame = analysis.iloc[:warmup_bars + fold.test_end_idx].copy()
        signals = StrategyRunner.scan_historical(
            strategies=[strategy],
            symbol=manifest.symbol,
            timeframe=manifest.timeframe,
            candle_df=scan_frame,
            strict=True,
        )
        test_start = BacktestEngine._utc_naive_timestamp(evaluation.iloc[fold.test_start_idx]['open_time'])
        test_end = BacktestEngine._utc_naive_timestamp(evaluation.iloc[fold.test_end_idx]['open_time'])
        test_signals = [
            signal for signal in signals
            if signal.timestamp is not None
            and test_start <= BacktestEngine._utc_naive_timestamp(signal.timestamp) < test_end
        ]
        replay_end = fold.test_end_idx + cls.LABEL_SPAN_BARS
        replay_frame = evaluation.iloc[fold.test_start_idx:replay_end].reset_index(drop=True)
        if len(replay_frame) <= cls.LABEL_SPAN_BARS:
            raise ValueError('Fold has no complete label tail')
        return test_signals, replay_frame

    @staticmethod
    def _fingerprint(value: dict) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, default=str, separators=(',', ':')).encode('utf-8')
        ).hexdigest()

    @classmethod
    def _replace_evaluation(cls, fold_model: ResearchFold, track: str, cost_scenario: str):
        existing = (
            ResearchEvaluationRun.query
            .filter_by(fold_id=fold_model.id, track=track, cost_scenario=cost_scenario)
            .first()
        )
        if existing is not None and existing.status == 'COMPLETED':
            return existing, False
        if existing is not None:
            ResearchCandidateOutcome.query.filter_by(evaluation_run_id=existing.id).delete(synchronize_session=False)
            db.session.delete(existing)
            db.session.flush()
        return None, True

    @classmethod
    def _store_candidate_outcomes(cls, experiment_id: str, fold_id: str, evaluation_run_id: str, outcomes: list[dict]):
        for outcome in outcomes:
            db.session.add(ResearchCandidateOutcome(
                experiment_id=experiment_id,
                fold_id=fold_id,
                evaluation_run_id=evaluation_run_id,
                candidate_number=outcome['candidate_number'],
                status=outcome['status'],
                skip_reason=outcome.get('skip_reason'),
                signal_time=outcome['signal_time'],
                entry_time=outcome.get('entry_time'),
                exit_time=outcome.get('exit_time'),
                symbol=outcome['symbol'],
                timeframe=outcome['timeframe'],
                strategy_name=outcome['strategy_name'],
                direction=outcome['direction'],
                confidence=outcome['confidence'],
                regime=outcome.get('regime'),
                volatility_regime=outcome.get('volatility_regime'),
                structural_bias=outcome.get('structural_bias'),
                regime_strength=outcome.get('regime_strength'),
                atr=outcome.get('atr'),
                entry_price=outcome.get('entry_price'),
                sl_price=outcome.get('sl_price'),
                tp1_price=outcome.get('tp1_price'),
                tp2_price=outcome.get('tp2_price'),
                exit_price=outcome.get('exit_price'),
                outcome=outcome.get('outcome'),
                net_r=outcome.get('net_r'),
                pnl=outcome.get('pnl'),
                duration_mins=outcome.get('duration_mins'),
                offered_tp1_r=outcome.get('offered_tp1_r'),
                offered_tp2_r=outcome.get('offered_tp2_r'),
                mfe_r=outcome.get('mfe_r'),
                mae_r=outcome.get('mae_r'),
                details_json=json.dumps(outcome.get('details', {}), sort_keys=True, default=str),
            ))

    @classmethod
    def _run_fold(
        cls,
        experiment: ResearchExperiment,
        manifest: WalkForwardManifest,
        strategy,
        analysis: pd.DataFrame,
        evaluation: pd.DataFrame,
        warmup_bars: int,
        fold_spec: FoldSpec,
        fold_model: ResearchFold,
    ):
        expected_runs = len(manifest.cost_scenarios) * 2
        completed_runs = fold_model.evaluations.filter_by(status='COMPLETED').count()
        if fold_model.status == 'COMPLETED' and completed_runs == expected_runs:
            return

        fold_model.status = 'RUNNING'
        fold_model.started_at = datetime.now(timezone.utc)
        fold_model.error_message = None
        db.session.commit()
        try:
            signals, replay_frame = cls._signals_for_fold(
                strategy, manifest, analysis, evaluation, warmup_bars, fold_spec,
            )
            for scenario_index, scenario in enumerate(manifest.cost_scenarios):
                candidate_existing, should_run = cls._replace_evaluation(
                    fold_model, 'candidate_quality', scenario.name,
                )
                if should_run:
                    outcomes = BacktestEngine.simulate_candidate_outcomes(
                        signals=signals,
                        candle_df=replay_frame,
                        initial_capital=manifest.initial_capital,
                        risk_pct=manifest.risk_pct,
                        slippage_bps=scenario.bps_per_side,
                    )
                    metrics, uncertainty = candidate_metrics(
                        outcomes,
                        bootstrap_repetitions=manifest.bootstrap_repetitions,
                        bootstrap_seed=manifest.bootstrap_seed + fold_spec.fold_number * 100 + scenario_index,
                    )
                    audit = {
                        'signal_count': len(signals),
                        'metric_schema_version': cls.METRIC_SCHEMA_VERSION,
                        'candidate_policy': 'independent-outcomes-v1',
                    }
                    evaluation_run = ResearchEvaluationRun(
                        id=str(uuid.uuid4()),
                        experiment_id=experiment.id,
                        fold_id=fold_model.id,
                        track='candidate_quality',
                        cost_scenario=scenario.name,
                        cost_bps_per_side=scenario.bps_per_side,
                        status='COMPLETED',
                        metrics_json=json.dumps(metrics, sort_keys=True),
                        uncertainty_json=json.dumps(uncertainty, sort_keys=True),
                        audit_json=json.dumps(audit, sort_keys=True),
                        result_fingerprint_sha256=cls._fingerprint({
                            'metrics': metrics, 'uncertainty': uncertainty, 'audit': audit,
                        }),
                        completed_at=datetime.now(timezone.utc),
                    )
                    db.session.add(evaluation_run)
                    db.session.flush()
                    cls._store_candidate_outcomes(experiment.id, fold_model.id, evaluation_run.id, outcomes)
                    db.session.commit()

                policy_existing, should_run_policy = cls._replace_evaluation(
                    fold_model, 'alert_policy', scenario.name,
                )
                if should_run_policy:
                    audit = {}
                    trades = BacktestEngine.simulate_trades(
                        signals=signals,
                        candle_df=replay_frame,
                        initial_capital=manifest.initial_capital,
                        risk_pct=manifest.risk_pct,
                        slippage_bps=scenario.bps_per_side,
                        audit=audit,
                    )
                    curve = BacktestEngine.build_equity_curve(
                        trades=trades,
                        initial_capital=manifest.initial_capital,
                        candle_df=replay_frame,
                    )
                    metrics = BacktestEngine.compute_metrics(
                        trades=trades,
                        initial_capital=manifest.initial_capital,
                        equity_curve=curve,
                    )
                    metrics.update({
                        'input_signals': len(signals),
                        'accepted_trades': len(trades),
                        'mean_net_r': round(
                            float(pd.Series([trade['rr_ratio'] for trade in trades]).mean()), 6,
                        ) if trades else 0.0,
                    })
                    audit['equity_curve'] = curve
                    evaluation_run = ResearchEvaluationRun(
                        id=str(uuid.uuid4()),
                        experiment_id=experiment.id,
                        fold_id=fold_model.id,
                        track='alert_policy',
                        cost_scenario=scenario.name,
                        cost_bps_per_side=scenario.bps_per_side,
                        status='COMPLETED',
                        metrics_json=json.dumps(metrics, sort_keys=True),
                        uncertainty_json=json.dumps({
                            'method': 'not_applicable_for_single-fold-policy-track',
                        }),
                        audit_json=json.dumps(audit, sort_keys=True, default=str),
                        result_fingerprint_sha256=cls._fingerprint({
                            'metrics': metrics, 'audit': audit,
                        }),
                        completed_at=datetime.now(timezone.utc),
                    )
                    db.session.add(evaluation_run)
                    db.session.commit()

            fold_model.status = 'COMPLETED'
            fold_model.completed_at = datetime.now(timezone.utc)
            db.session.commit()
        except Exception as exc:
            fold_model.status = 'FAILED'
            fold_model.error_message = str(exc)
            fold_model.completed_at = datetime.now(timezone.utc)
            db.session.commit()
            raise

    @classmethod
    def _base_candidate_records(cls, experiment_id: str, kinds: tuple[str, ...] = ('OOS',)) -> list[dict]:
        records = (
            ResearchCandidateOutcome.query
            .join(ResearchEvaluationRun, ResearchCandidateOutcome.evaluation_run_id == ResearchEvaluationRun.id)
            .join(ResearchFold, ResearchCandidateOutcome.fold_id == ResearchFold.id)
            .filter(ResearchCandidateOutcome.experiment_id == experiment_id)
            .filter(ResearchEvaluationRun.track == 'candidate_quality')
            .filter(ResearchEvaluationRun.cost_scenario == 'base')
            .filter(ResearchEvaluationRun.status == 'COMPLETED')
            .filter(ResearchFold.kind.in_(kinds))
            .order_by(ResearchCandidateOutcome.signal_time.asc(), ResearchCandidateOutcome.candidate_number.asc())
            .all()
        )
        return [record.to_dict() for record in records]

    @classmethod
    def _base_fold_metrics(cls, experiment_id: str, kind: str = 'OOS') -> list[dict]:
        rows = (
            ResearchEvaluationRun.query
            .join(ResearchFold, ResearchEvaluationRun.fold_id == ResearchFold.id)
            .filter(ResearchEvaluationRun.experiment_id == experiment_id)
            .filter(ResearchEvaluationRun.track == 'candidate_quality')
            .filter(ResearchEvaluationRun.cost_scenario == 'base')
            .filter(ResearchFold.kind == kind)
            .filter(ResearchEvaluationRun.status == 'COMPLETED')
            .order_by(ResearchFold.fold_number.asc())
            .all()
        )
        return [evaluation.to_dict()['metrics'] for evaluation in rows]

    @classmethod
    def _persist_slices(cls, experiment_id: str, outcomes: list[dict], manifest: WalkForwardManifest):
        ResearchMetricSlice.query.filter_by(experiment_id=experiment_id, evaluation_run_id=None).delete(
            synchronize_session=False,
        )
        groups: dict[tuple[str, str], list[dict]] = {('overall', 'ALL'): outcomes}
        for field in ('direction', 'regime', 'volatility_regime'):
            grouped: dict[str, list[dict]] = defaultdict(list)
            for outcome in outcomes:
                grouped[str(outcome.get(field) or 'UNKNOWN')].append(outcome)
            groups.update({(field, key): value for key, value in grouped.items()})

        def confidence_bucket(value: float) -> str:
            if value >= 0.8:
                return 'high_0.80_1.00'
            if value >= 0.6:
                return 'medium_0.60_0.79'
            return 'low_below_0.60'

        confidence_groups: dict[str, list[dict]] = defaultdict(list)
        for outcome in outcomes:
            confidence_groups[confidence_bucket(float(outcome.get('confidence') or 0.0))].append(outcome)
        groups.update({('confidence_bucket', key): value for key, value in confidence_groups.items()})

        for index, ((slice_type, slice_key), records) in enumerate(groups.items()):
            metrics, uncertainty = candidate_metrics(
                records,
                bootstrap_repetitions=manifest.bootstrap_repetitions if slice_type == 'overall' else 100,
                bootstrap_seed=manifest.bootstrap_seed + index,
                include_uncertainty=slice_type == 'overall',
            )
            db.session.add(ResearchMetricSlice(
                experiment_id=experiment_id,
                evaluation_run_id=None,
                slice_type=slice_type,
                slice_key=slice_key,
                is_primary=True,
                sample_size=metrics['evaluated_candidates'],
                independent_block_count=uncertainty.get('independent_block_count', 0),
                status='INSUFFICIENT' if metrics['evaluated_candidates'] < 30 else 'COMPLETE',
                metrics_json=json.dumps(metrics, sort_keys=True),
                uncertainty_json=json.dumps(uncertainty, sort_keys=True),
            ))
        db.session.commit()

    @classmethod
    def _update_trial_adjustment(cls, experiment: ResearchExperiment, raw_p_value: float | None):
        trials = (
            ResearchTrial.query
            .filter_by(family_id=experiment.family_id)
            .order_by(ResearchTrial.created_at.asc(), ResearchTrial.id.asc())
            .all()
        )
        current = next((trial for trial in trials if trial.experiment_id == experiment.id), None)
        if current is not None:
            current.raw_p_value = raw_p_value
        adjusted = benjamini_hochberg([trial.raw_p_value for trial in trials])
        for trial, adjusted_value in zip(trials, adjusted):
            trial.adjusted_p_value = adjusted_value
            trial.family_size = len(trials)
        db.session.commit()

    @classmethod
    def _refresh_walk_forward_summary(cls, experiment: ResearchExperiment, manifest: WalkForwardManifest):
        outcomes = cls._base_candidate_records(experiment.id, ('OOS',))
        metrics, uncertainty = candidate_metrics(
            outcomes,
            bootstrap_repetitions=manifest.bootstrap_repetitions,
            bootstrap_seed=manifest.bootstrap_seed,
        )
        fold_metrics = cls._base_fold_metrics(experiment.id, 'OOS')
        decision, grade, reasons = preliminary_decision(
            metrics, uncertainty, fold_metrics, min_folds=manifest.min_folds,
        )
        cls._persist_slices(experiment.id, outcomes, manifest)
        cls._update_trial_adjustment(experiment, uncertainty.get('p_value_mean_net_r'))
        existing_summary = json.loads(experiment.summary_json or '{}')
        existing_summary.update({
            'walk_forward': {
                'metrics': metrics,
                'uncertainty': uncertainty,
                'fold_metrics': fold_metrics,
                'fold_count': len(fold_metrics),
            },
            'metric_schema_version': cls.METRIC_SCHEMA_VERSION,
        })
        experiment.status = 'WALK_FORWARD_COMPLETE'
        experiment.decision = decision
        experiment.evidence_grade = grade
        experiment.decision_reasons_json = json.dumps(reasons)
        experiment.summary_json = json.dumps(existing_summary, sort_keys=True)
        experiment.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        return decision, grade, reasons

    @classmethod
    def execute(cls, experiment_id: str) -> ResearchExperiment:
        experiment = cls._get_experiment(experiment_id)
        if experiment.status == 'FAILED':
            experiment.status = 'SEALED'
            experiment.error_message = None
        if experiment.holdout_revealed_at is not None:
            raise ValueError('Holdout has been revealed; use the completed experiment report')
        manifest = WalkForwardManifest.from_dict(json.loads(experiment.manifest_json))
        strategy = cls._strategy_for_manifest(manifest)
        analysis, evaluation, warmup_bars, fingerprint = cls._load_data(manifest, strategy)
        if experiment.data_fingerprint_sha256 != fingerprint:
            raise ValueError('Stored candle data fingerprint changed after experiment seal')
        plan = cls._plan(manifest, evaluation)

        experiment.status = 'WALK_FORWARD_RUNNING'
        experiment.started_at = experiment.started_at or datetime.now(timezone.utc)
        db.session.commit()
        try:
            for fold_spec in plan.folds:
                fold_model = cls._fold_model(experiment, 'OOS', fold_spec, evaluation, fingerprint)
                cls._run_fold(
                    experiment, manifest, strategy, analysis, evaluation, warmup_bars, fold_spec, fold_model,
                )
            cls._refresh_walk_forward_summary(experiment, manifest)
            return experiment
        except Exception as exc:
            experiment.status = 'FAILED'
            experiment.error_message = str(exc)
            experiment.completed_at = datetime.now(timezone.utc)
            db.session.commit()
            raise

    @classmethod
    def reveal_holdout(cls, experiment_id: str, revealed_by: str = 'api') -> ResearchExperiment:
        experiment = cls._get_experiment(experiment_id)
        if experiment.status != 'WALK_FORWARD_COMPLETE':
            raise ValueError('Complete walk-forward execution before revealing the final holdout')
        if experiment.decision == 'REJECT':
            raise ValueError('A rejected walk-forward result cannot be promoted by opening the holdout')
        if experiment.holdout_revealed_at is not None:
            return experiment

        manifest = WalkForwardManifest.from_dict(json.loads(experiment.manifest_json))
        strategy = cls._strategy_for_manifest(manifest)
        analysis, evaluation, warmup_bars, fingerprint = cls._load_data(manifest, strategy)
        if experiment.data_fingerprint_sha256 != fingerprint:
            raise ValueError('Stored candle data fingerprint changed after experiment seal')
        plan = cls._plan(manifest, evaluation)
        holdout = FoldSpec(
            fold_number=0,
            train_start_idx=0,
            train_end_idx=plan.holdout_start_idx,
            purge_start_idx=plan.holdout_start_idx,
            purge_end_idx=plan.holdout_start_idx,
            test_start_idx=plan.holdout_start_idx,
            test_end_idx=plan.holdout_end_idx,
        )
        fold_model = cls._fold_model(experiment, 'HOLDOUT', holdout, evaluation, fingerprint)
        cls._run_fold(
            experiment, manifest, strategy, analysis, evaluation, warmup_bars, holdout, fold_model,
        )

        oos_outcomes = cls._base_candidate_records(experiment.id, ('OOS',))
        holdout_outcomes = cls._base_candidate_records(experiment.id, ('HOLDOUT',))
        holdout_metrics, _ = candidate_metrics(
            holdout_outcomes,
            bootstrap_repetitions=manifest.bootstrap_repetitions,
            bootstrap_seed=manifest.bootstrap_seed + 1,
        )
        combined_metrics, combined_uncertainty = candidate_metrics(
            oos_outcomes + holdout_outcomes,
            bootstrap_repetitions=manifest.bootstrap_repetitions,
            bootstrap_seed=manifest.bootstrap_seed + 2,
        )
        summary = json.loads(experiment.summary_json or '{}')
        walk_forward = summary.get('walk_forward', {})
        preliminary = (
            experiment.decision or 'PROVISIONAL',
            experiment.evidence_grade or 'C',
            json.loads(experiment.decision_reasons_json or '[]'),
        )
        decision, grade, reasons = final_holdout_decision(
            preliminary,
            holdout_metrics,
            combined_metrics,
            combined_uncertainty,
        )
        summary['holdout'] = {
            'metrics': holdout_metrics,
            'combined_metrics': combined_metrics,
            'combined_uncertainty': combined_uncertainty,
            'walk_forward_fold_count': walk_forward.get('fold_count', 0),
        }
        experiment.status = 'COMPLETED'
        experiment.decision = decision
        experiment.evidence_grade = grade
        experiment.decision_reasons_json = json.dumps(reasons)
        experiment.summary_json = json.dumps(summary, sort_keys=True)
        experiment.holdout_revealed_at = datetime.now(timezone.utc)
        experiment.holdout_revealed_by = revealed_by
        experiment.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        return experiment

    @classmethod
    def detail(cls, experiment_id: str) -> dict:
        experiment = cls._get_experiment(experiment_id)
        folds = (
            ResearchFold.query
            .filter_by(experiment_id=experiment.id)
            .order_by(ResearchFold.kind.asc(), ResearchFold.fold_number.asc())
            .all()
        )
        evaluations = (
            ResearchEvaluationRun.query
            .filter_by(experiment_id=experiment.id)
            .order_by(ResearchEvaluationRun.created_at.asc())
            .all()
        )
        slices = (
            ResearchMetricSlice.query
            .filter_by(experiment_id=experiment.id)
            .order_by(ResearchMetricSlice.slice_type.asc(), ResearchMetricSlice.slice_key.asc())
            .all()
        )
        trial = ResearchTrial.query.filter_by(experiment_id=experiment.id).first()
        return {
            'experiment': experiment.to_dict(),
            'folds': [fold.to_dict() for fold in folds],
            'evaluations': [evaluation.to_dict() for evaluation in evaluations],
            'slices': [slice_.to_dict() for slice_ in slices],
            'trial': trial.to_dict() if trial else None,
        }
