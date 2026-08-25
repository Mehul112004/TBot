"""Immutable, normalized manifest used by a walk-forward experiment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any

import pandas as pd


def _utc_naive_datetime(value: Any, field_name: str) -> datetime:
    try:
        timestamp = pd.Timestamp(value)
    except Exception as exc:  # pragma: no cover - pandas exception shape varies
        raise ValueError(f"{field_name} must be an ISO datetime") from exc
    if pd.isna(timestamp):
        raise ValueError(f"{field_name} must be an ISO datetime")
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert('UTC').tz_localize(None)
    return timestamp.to_pydatetime()


def _as_positive_int(value: Any, field_name: str, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if parsed < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return parsed


def _as_finite_float(value: Any, field_name: str, minimum: float | None = None) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    if not pd.notna(parsed) or not float('-inf') < parsed < float('inf'):
        raise ValueError(f"{field_name} must be finite")
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return parsed


@dataclass(frozen=True)
class CostScenario:
    name: str
    bps_per_side: float

    def to_dict(self) -> dict:
        return {'name': self.name, 'bps_per_side': self.bps_per_side}


@dataclass(frozen=True)
class WalkForwardManifest:
    """A sealed description of one frozen-strategy research experiment.

    Windows are intentionally expressed in bars. This avoids mixing calendar
    assumptions across 5m, 1h, and daily data and makes label-horizon purging
    mechanically verifiable.
    """

    name: str
    hypothesis: str
    family_id: str
    variant_id: str
    strategy_name: str
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    train_bars: int
    test_bars: int
    holdout_bars: int
    min_folds: int
    step_bars: int
    initial_capital: float
    risk_pct: float
    cost_scenarios: tuple[CostScenario, ...]
    bootstrap_repetitions: int
    bootstrap_seed: int
    source_commit: str = ''
    schema_version: str = 'walk-forward-manifest-v1'
    promotion_policy_version: str = 'signal-quality-gate-v1'

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'WalkForwardManifest':
        if not isinstance(data, dict):
            raise ValueError('Experiment manifest must be a JSON object')

        def required_text(key: str) -> str:
            value = str(data.get(key, '')).strip()
            if not value:
                raise ValueError(f"{key} is required")
            return value

        start_date = _utc_naive_datetime(data.get('start_date'), 'start_date')
        end_date = _utc_naive_datetime(data.get('end_date'), 'end_date')
        if start_date >= end_date:
            raise ValueError('start_date must be before end_date')

        train_bars = _as_positive_int(data.get('train_bars'), 'train_bars')
        test_bars = _as_positive_int(data.get('test_bars'), 'test_bars')
        holdout_bars = _as_positive_int(data.get('holdout_bars'), 'holdout_bars')
        step_bars = _as_positive_int(data.get('step_bars', test_bars), 'step_bars')
        if step_bars != test_bars:
            raise ValueError(
                'walk-forward v1 requires step_bars equal to test_bars so '
                'aggregate OOS windows cannot overlap'
            )

        risk_pct = _as_finite_float(data.get('risk_pct', 0.01), 'risk_pct')
        if not 0 < risk_pct <= 1:
            raise ValueError('risk_pct must be greater than 0 and at most 1')

        default_bps = _as_finite_float(data.get('slippage_bps', 10.0), 'slippage_bps', 0.0)
        raw_scenarios = data.get('cost_scenarios')
        if raw_scenarios is None:
            raw_scenarios = [
                {'name': 'base', 'bps_per_side': default_bps},
                {'name': 'moderate', 'bps_per_side': default_bps + 10.0},
                {'name': 'severe', 'bps_per_side': default_bps + 25.0},
            ]
        if not isinstance(raw_scenarios, list) or not raw_scenarios:
            raise ValueError('cost_scenarios must be a non-empty array')
        scenarios: list[CostScenario] = []
        names: set[str] = set()
        for item in raw_scenarios:
            if not isinstance(item, dict):
                raise ValueError('Each cost scenario must be an object')
            name = str(item.get('name', '')).strip().lower()
            if not name:
                raise ValueError('Each cost scenario needs a name')
            if name in names:
                raise ValueError(f"Duplicate cost scenario: {name}")
            names.add(name)
            scenarios.append(CostScenario(
                name=name,
                bps_per_side=_as_finite_float(
                    item.get('bps_per_side'), f'cost_scenarios.{name}.bps_per_side', 0.0,
                ),
            ))
        if 'base' not in names:
            raise ValueError('cost_scenarios must include a base scenario')

        name = required_text('name')
        strategy_name = required_text('strategy_name')
        symbol = required_text('symbol').upper()
        timeframe = required_text('timeframe')
        family_id = str(data.get('family_id') or strategy_name).strip()
        variant_id = str(data.get('variant_id') or strategy_name).strip()
        hypothesis = str(data.get('hypothesis') or f'{strategy_name} has positive net OOS expectancy.').strip()

        return cls(
            name=name,
            hypothesis=hypothesis,
            family_id=family_id,
            variant_id=variant_id,
            strategy_name=strategy_name,
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            train_bars=train_bars,
            test_bars=test_bars,
            holdout_bars=holdout_bars,
            min_folds=_as_positive_int(data.get('min_folds', 5), 'min_folds'),
            step_bars=step_bars,
            initial_capital=_as_finite_float(data.get('initial_capital', 10000.0), 'initial_capital', 0.0000001),
            risk_pct=risk_pct,
            cost_scenarios=tuple(scenarios),
            bootstrap_repetitions=_as_positive_int(
                data.get('bootstrap_repetitions', 1000), 'bootstrap_repetitions', 100,
            ),
            bootstrap_seed=_as_positive_int(data.get('bootstrap_seed', 20260825), 'bootstrap_seed', 0),
            source_commit=str(data.get('source_commit', '')).strip(),
            schema_version=str(data.get('schema_version', 'walk-forward-manifest-v1')).strip(),
            promotion_policy_version=str(data.get('promotion_policy_version', 'signal-quality-gate-v1')).strip(),
        )

    def to_dict(self) -> dict:
        return {
            'schema_version': self.schema_version,
            'name': self.name,
            'hypothesis': self.hypothesis,
            'family_id': self.family_id,
            'variant_id': self.variant_id,
            'strategy_name': self.strategy_name,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'start_date': self.start_date.isoformat() + 'Z',
            'end_date': self.end_date.isoformat() + 'Z',
            'train_bars': self.train_bars,
            'test_bars': self.test_bars,
            'holdout_bars': self.holdout_bars,
            'min_folds': self.min_folds,
            'step_bars': self.step_bars,
            'initial_capital': self.initial_capital,
            'risk_pct': self.risk_pct,
            'cost_scenarios': [scenario.to_dict() for scenario in self.cost_scenarios],
            'bootstrap_repetitions': self.bootstrap_repetitions,
            'bootstrap_seed': self.bootstrap_seed,
            'source_commit': self.source_commit,
            'promotion_policy_version': self.promotion_policy_version,
        }

    @property
    def sha256(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
