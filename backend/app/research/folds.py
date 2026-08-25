"""Chronological, non-overlapping walk-forward fold planning."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FoldSpec:
    fold_number: int
    train_start_idx: int
    train_end_idx: int
    purge_start_idx: int
    purge_end_idx: int
    test_start_idx: int
    test_end_idx: int

    def to_dict(self) -> dict:
        return {
            'fold_number': self.fold_number,
            'train_start_idx': self.train_start_idx,
            'train_end_idx': self.train_end_idx,
            'purge_start_idx': self.purge_start_idx,
            'purge_end_idx': self.purge_end_idx,
            'test_start_idx': self.test_start_idx,
            'test_end_idx': self.test_end_idx,
        }


@dataclass(frozen=True)
class FoldPlan:
    folds: tuple[FoldSpec, ...]
    holdout_start_idx: int
    holdout_end_idx: int
    label_tail_start_idx: int
    label_span_bars: int
    total_evaluation_bars: int

    def to_dict(self) -> dict:
        return {
            'folds': [fold.to_dict() for fold in self.folds],
            'holdout_start_idx': self.holdout_start_idx,
            'holdout_end_idx': self.holdout_end_idx,
            'label_tail_start_idx': self.label_tail_start_idx,
            'label_span_bars': self.label_span_bars,
            'total_evaluation_bars': self.total_evaluation_bars,
        }


def plan_anchored_folds(
    *,
    total_evaluation_bars: int,
    train_bars: int,
    test_bars: int,
    step_bars: int,
    holdout_bars: int,
    label_span_bars: int,
    min_folds: int,
) -> FoldPlan:
    """Plan anchored OOS folds without test overlap or holdout leakage.

    ``total_evaluation_bars`` includes a final label tail. The tail contains
    candles that may resolve the last holdout candidates, but no candidates may
    be detected there. The final OOS fold must also leave a full label horizon
    before the sealed holdout starts.
    """
    values = {
        'total_evaluation_bars': total_evaluation_bars,
        'train_bars': train_bars,
        'test_bars': test_bars,
        'step_bars': step_bars,
        'holdout_bars': holdout_bars,
        'label_span_bars': label_span_bars,
        'min_folds': min_folds,
    }
    for name, value in values.items():
        if not isinstance(value, int) or value < 1:
            raise ValueError(f'{name} must be a positive integer')
    if step_bars != test_bars:
        raise ValueError('Non-overlapping OOS aggregation requires step_bars == test_bars')

    label_tail_start = total_evaluation_bars - label_span_bars
    holdout_start = label_tail_start - holdout_bars
    holdout_end = label_tail_start
    if holdout_start <= 0:
        raise ValueError('Not enough evaluation candles after reserving holdout and label tail')

    folds: list[FoldSpec] = []
    train_end = train_bars
    fold_number = 1
    while True:
        purge_start = train_end
        purge_end = purge_start + label_span_bars
        test_start = purge_end
        test_end = test_start + test_bars

        # Test candidates need a complete label span before the next sealed
        # region. This prevents a pre-holdout candidate from observing holdout
        # prices merely to resolve its terminal label.
        if test_end + label_span_bars > holdout_start:
            break

        folds.append(FoldSpec(
            fold_number=fold_number,
            train_start_idx=0,
            train_end_idx=train_end,
            purge_start_idx=purge_start,
            purge_end_idx=purge_end,
            test_start_idx=test_start,
            test_end_idx=test_end,
        ))
        fold_number += 1
        train_end = test_end

    if len(folds) < min_folds:
        raise ValueError(
            f'Insufficient history for {min_folds} non-overlapping OOS folds; '
            f'only {len(folds)} fit after purge, holdout, and label-tail reservations'
        )

    seen = set()
    for fold in folds:
        if fold.test_start_idx < fold.purge_end_idx:
            raise AssertionError('Fold test begins before its purge ends')
        for index in range(fold.test_start_idx, fold.test_end_idx):
            if index in seen:
                raise AssertionError('Duplicate OOS candle ownership detected')
            seen.add(index)

    return FoldPlan(
        folds=tuple(folds),
        holdout_start_idx=holdout_start,
        holdout_end_idx=holdout_end,
        label_tail_start_idx=label_tail_start,
        label_span_bars=label_span_bars,
        total_evaluation_bars=total_evaluation_bars,
    )
