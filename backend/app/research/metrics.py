"""Signal-quality metrics, dependence-aware uncertainty, and research gates."""

from __future__ import annotations

from collections import Counter, defaultdict
from math import sqrt
from typing import Iterable

import numpy as np
import pandas as pd


def _finite(value) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def evaluated_outcomes(outcomes: Iterable[dict]) -> list[dict]:
    return [
        outcome for outcome in outcomes
        if outcome.get('status') == 'EVALUATED' and _finite(outcome.get('net_r'))
    ]


def _outcome_r_values(outcomes: Iterable[dict]) -> np.ndarray:
    return np.asarray([float(outcome['net_r']) for outcome in evaluated_outcomes(outcomes)], dtype=float)


def _daily_clusters(outcomes: Iterable[dict]) -> list[np.ndarray]:
    grouped: dict[pd.Timestamp, list[float]] = defaultdict(list)
    for outcome in evaluated_outcomes(outcomes):
        signal_time = pd.Timestamp(outcome['signal_time'])
        if signal_time.tzinfo is not None:
            signal_time = signal_time.tz_convert('UTC').tz_localize(None)
        grouped[signal_time.normalize()].append(float(outcome['net_r']))
    return [np.asarray(grouped[key], dtype=float) for key in sorted(grouped)]


def moving_block_bootstrap(
    outcomes: Iterable[dict],
    repetitions: int,
    seed: int,
    block_days: int = 1,
) -> dict:
    """Bootstrap mean net R by chronological detection-day clusters.

    Resampling clusters instead of individual trades avoids pretending that a
    burst of nearby signals is a collection of independent observations. The
    routine is deterministic for a sealed manifest seed.
    """
    clusters = _daily_clusters(outcomes)
    if not clusters:
        return {
            'method': 'moving-block-detection-day-v1',
            'independent_block_count': 0,
            'mean_net_r_ci_95': None,
            'p_value_mean_net_r': None,
        }

    block_days = max(1, int(block_days))
    repetitions = max(100, int(repetitions))
    all_values = np.concatenate(clusters)
    observed = float(np.mean(all_values))
    cluster_count = len(clusters)
    rng = np.random.default_rng(seed)

    def sample_mean(source_clusters: list[np.ndarray]) -> float:
        selected: list[np.ndarray] = []
        day_count = 0
        while day_count < cluster_count:
            start = int(rng.integers(0, cluster_count))
            indices = [(start + offset) % cluster_count for offset in range(block_days)]
            selected.extend(source_clusters[index] for index in indices)
            day_count += len(indices)
        return float(np.mean(np.concatenate(selected)))

    samples = np.asarray([sample_mean(clusters) for _ in range(repetitions)], dtype=float)
    interval = np.quantile(samples, [0.025, 0.975]).tolist()

    # One-sided null bootstrap for H0: mean net R <= 0. Centering creates the
    # no-edge null; using an ordinary bootstrap distribution here would turn a
    # confidence interval into an invalid p-value.
    centered_clusters = [cluster - observed for cluster in clusters]
    null_samples = np.asarray(
        [sample_mean(centered_clusters) for _ in range(repetitions)], dtype=float,
    )
    p_value = float((np.sum(null_samples >= observed) + 1) / (repetitions + 1))

    return {
        'method': 'moving-block-detection-day-v1',
        'block_days': block_days,
        'bootstrap_repetitions': repetitions,
        'independent_block_count': cluster_count,
        'mean_net_r_ci_95': [round(float(interval[0]), 6), round(float(interval[1]), 6)],
        'p_value_mean_net_r': round(p_value, 6),
    }


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    if total <= 0:
        return None
    p = successes / total
    denominator = 1 + z ** 2 / total
    centre = (p + z ** 2 / (2 * total)) / denominator
    margin = z * sqrt((p * (1 - p) + z ** 2 / (4 * total)) / total) / denominator
    return [round((centre - margin) * 100, 4), round((centre + margin) * 100, 4)]


def candidate_metrics(
    outcomes: Iterable[dict],
    *,
    bootstrap_repetitions: int = 1000,
    bootstrap_seed: int = 20260825,
    include_uncertainty: bool = True,
) -> tuple[dict, dict]:
    """Calculate candidate-quality metrics without constructing an equity curve."""
    all_outcomes = list(outcomes)
    evaluated = evaluated_outcomes(all_outcomes)
    values = _outcome_r_values(evaluated)
    skip_reasons = Counter(
        outcome.get('skip_reason', 'not_evaluated')
        for outcome in all_outcomes if outcome.get('status') != 'EVALUATED'
    )
    terminal_counts = Counter(outcome.get('outcome', 'UNKNOWN') for outcome in evaluated)
    total = len(evaluated)

    if total == 0:
        return ({
            'input_candidates': len(all_outcomes),
            'evaluated_candidates': 0,
            'skipped_candidates': len(all_outcomes),
            'skip_reasons': dict(skip_reasons),
            'outcome_counts': {},
            'net_win_rate': 0.0,
            'mean_net_r': 0.0,
            'median_net_r': 0.0,
            'expectancy_r': 0.0,
            'payoff_ratio': None,
            'break_even_win_rate': None,
            'tp1_before_stop_rate': 0.0,
            'mean_offered_tp1_r': None,
            'mean_offered_tp2_r': None,
            'mean_mfe_r': None,
            'mean_mae_r': None,
            'expiry_rate': 0.0,
        }, moving_block_bootstrap([], bootstrap_repetitions, bootstrap_seed))

    winners = values[values > 0]
    losers = values[values < 0]
    mean_win = float(np.mean(winners)) if len(winners) else 0.0
    mean_loss = float(np.mean(losers)) if len(losers) else 0.0
    payoff_ratio = mean_win / abs(mean_loss) if mean_win > 0 and mean_loss < 0 else None
    break_even = abs(mean_loss) / (mean_win + abs(mean_loss)) if mean_win > 0 and mean_loss < 0 else None
    tp_hits = sum(outcome.get('outcome') in ('HIT_TP1', 'HIT_TP2') for outcome in evaluated)

    def average_field(name: str):
        fields = [float(outcome[name]) for outcome in evaluated if _finite(outcome.get(name))]
        return round(float(np.mean(fields)), 6) if fields else None

    metrics = {
        'input_candidates': len(all_outcomes),
        'evaluated_candidates': total,
        'skipped_candidates': len(all_outcomes) - total,
        'skip_reasons': dict(sorted(skip_reasons.items())),
        'outcome_counts': dict(sorted(terminal_counts.items())),
        'net_win_rate': round(float(np.mean(values > 0) * 100), 4),
        'net_win_rate_wilson_ci_95': wilson_interval(int(np.sum(values > 0)), total),
        'mean_net_r': round(float(np.mean(values)), 6),
        'median_net_r': round(float(np.median(values)), 6),
        'expectancy_r': round(float(np.mean(values)), 6),
        'mean_winning_r': round(mean_win, 6),
        'mean_losing_r': round(mean_loss, 6),
        'payoff_ratio': round(payoff_ratio, 6) if payoff_ratio is not None else None,
        'break_even_win_rate': round(break_even * 100, 6) if break_even is not None else None,
        'tp1_before_stop_rate': round(tp_hits / total * 100, 4),
        'mean_offered_tp1_r': average_field('offered_tp1_r'),
        'mean_offered_tp2_r': average_field('offered_tp2_r'),
        'mean_mfe_r': average_field('mfe_r'),
        'mean_mae_r': average_field('mae_r'),
        'expiry_rate': round(terminal_counts.get('EXPIRED', 0) / total * 100, 4),
    }
    uncertainty = moving_block_bootstrap(
        evaluated,
        bootstrap_repetitions,
        bootstrap_seed,
    ) if include_uncertainty else {
        'method': 'not_computed_for_slice',
        'independent_block_count': len(_daily_clusters(evaluated)),
        'mean_net_r_ci_95': None,
        'p_value_mean_net_r': None,
    }
    return metrics, uncertainty


def benjamini_hochberg(p_values: list[float | None]) -> list[float | None]:
    """Return monotonic BH-adjusted p-values while preserving input order."""
    result: list[float | None] = [None] * len(p_values)
    valid = [(index, float(value)) for index, value in enumerate(p_values) if _finite(value)]
    if not valid:
        return result
    valid.sort(key=lambda item: item[1])
    m = len(valid)
    adjusted = [min(1.0, value * m / (rank + 1)) for rank, (_, value) in enumerate(valid)]
    for index in range(m - 2, -1, -1):
        adjusted[index] = min(adjusted[index], adjusted[index + 1])
    for (original_index, _), value in zip(valid, adjusted):
        result[original_index] = round(float(value), 6)
    return result


def preliminary_decision(
    pooled_metrics: dict,
    pooled_uncertainty: dict,
    fold_metrics: Iterable[dict],
    *,
    min_folds: int,
) -> tuple[str, str, list[str]]:
    """Apply the v1 pre-holdout promotion gate to frozen-strategy OOS data."""
    reasons: list[str] = []
    sample_size = int(pooled_metrics.get('evaluated_candidates', 0) or 0)
    if sample_size < 30:
        return 'PROVISIONAL', 'Insufficient', ['insufficient_oos_candidates']

    mean_net_r = float(pooled_metrics.get('mean_net_r', 0) or 0)
    if mean_net_r <= 0:
        return 'REJECT', 'Rejected', ['non_positive_oos_expectancy']

    fold_metrics = list(fold_metrics)
    sampled_folds = [metric for metric in fold_metrics if metric.get('evaluated_candidates', 0) >= 1]
    positive_folds = sum(metric.get('mean_net_r', 0) > 0 for metric in sampled_folds)
    if sampled_folds and positive_folds / len(sampled_folds) < 0.60:
        return 'REJECT', 'Rejected', ['insufficient_profitable_fold_stability']

    if len(fold_metrics) < min_folds:
        reasons.append('insufficient_completed_folds')
    if sample_size < 100:
        reasons.append('below_pass_sample_size')
    interval = pooled_uncertainty.get('mean_net_r_ci_95')
    if not interval:
        reasons.append('insufficient_independent_history')
    elif interval[0] <= 0:
        reasons.append('mean_net_r_ci_crosses_zero')

    if reasons:
        return 'PROVISIONAL', 'C', reasons
    return 'PROVISIONAL', 'B', ['final_holdout_sealed']


def final_holdout_decision(
    preliminary: tuple[str, str, list[str]],
    holdout_metrics: dict,
    combined_metrics: dict,
    combined_uncertainty: dict,
) -> tuple[str, str, list[str]]:
    """Confirm or reject only after an explicit final-holdout reveal."""
    pre_status, _, pre_reasons = preliminary
    if pre_status == 'REJECT':
        return pre_status, 'Rejected', pre_reasons

    # A final holdout can add evidence, but it cannot turn an OOS result that
    # was too small, too dependent, or too unstable into a full promotion.
    # Otherwise a strong last window could mask the very walk-forward weakness
    # the procedure was built to expose.
    unresolved_oos_reasons = [
        reason for reason in pre_reasons
        if reason != 'final_holdout_sealed'
    ]

    reasons: list[str] = []
    if int(holdout_metrics.get('evaluated_candidates', 0) or 0) < 30:
        reasons.append('insufficient_holdout_candidates')
    if float(holdout_metrics.get('mean_net_r', 0) or 0) <= 0:
        reasons.append('non_positive_holdout_expectancy')
    break_even = holdout_metrics.get('break_even_win_rate')
    if break_even is not None and holdout_metrics.get('net_win_rate', 0) <= break_even:
        reasons.append('holdout_win_rate_not_above_break_even')
    combined_interval = combined_uncertainty.get('mean_net_r_ci_95')
    if not combined_interval or combined_interval[0] <= 0:
        reasons.append('combined_mean_net_r_ci_crosses_zero')

    if unresolved_oos_reasons:
        return 'PROVISIONAL', 'C', sorted(set(unresolved_oos_reasons + reasons))
    if reasons:
        status = 'PROVISIONAL' if reasons == ['insufficient_holdout_candidates'] else 'REJECT'
        return status, 'C' if status == 'PROVISIONAL' else 'Rejected', reasons
    return 'PASS', 'A', ['walk_forward_and_holdout_passed']
