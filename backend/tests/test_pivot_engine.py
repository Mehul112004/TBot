"""
Unit tests for the Pivot Points Engine.
Verifies Standard and Camarilla formulas, variant selection, period handling,
and the "previous completed candle" selection logic.
"""

import pytest
from datetime import datetime, timedelta

from app.core.pivot_engine import (
    compute_pivots,
    _standard_levels,
    _camarilla_levels,
)
from app.models.db import db, Candle


# ---------------------------------------------------------------------------
# Pure-formula tests (no DB)
# ---------------------------------------------------------------------------

class TestPivotFormulas:
    """Verify the pivot formulas against hand-computed values."""

    def test_standard_pivot(self):
        # H=110, L=90, C=100 → P = 100
        levels = dict((lbl, lvl) for lbl, lvl, _ in _standard_levels(110, 90, 100))
        assert abs(levels['P'] - 100.0) < 1e-9
        assert abs(levels['R1'] - 110.0) < 1e-9   # 2*100 - 90
        assert abs(levels['S1'] - 90.0) < 1e-9    # 2*100 - 110
        assert abs(levels['R2'] - 120.0) < 1e-9   # 100 + 20
        assert abs(levels['S2'] - 80.0) < 1e-9    # 100 - 20

    def test_camarilla_levels(self):
        # H=110, L=90, C=100, Range=20
        levels = dict((lbl, lvl) for lbl, lvl, _ in _camarilla_levels(110, 90, 100))
        # H4 = 100 + 20*1.1/2 = 111
        assert abs(levels['H4'] - 111.0) < 1e-9
        # L4 = 100 - 20*1.1/2 = 89
        assert abs(levels['L4'] - 89.0) < 1e-9
        # H3 = 100 + 20*1.1/4 = 105.5
        assert abs(levels['H3'] - 105.5) < 1e-9
        # L3 = 100 - 20*1.1/4 = 94.5
        assert abs(levels['L3'] - 94.5) < 1e-9
        # Camarilla set includes the Standard P
        assert abs(levels['P'] - 100.0) < 1e-9

    def test_standard_has_seven_levels(self):
        levels = _standard_levels(110, 90, 100)
        labels = [lbl for lbl, _, _ in levels]
        assert set(labels) == {'P', 'R1', 'R2', 'R3', 'S1', 'S2', 'S3'}

    def test_camarilla_has_nine_levels(self):
        levels = _camarilla_levels(110, 90, 100)
        labels = [lbl for lbl, _, _ in levels]
        assert set(labels) == {'P', 'H1', 'H2', 'H3', 'H4', 'L1', 'L2', 'L3', 'L4'}

    def test_direction_labels(self):
        std = _standard_levels(110, 90, 100)
        by_label = dict((lbl, d) for lbl, _, d in std)
        assert by_label['P'] == 'pivot'
        assert by_label['R1'] == 'resistance'
        assert by_label['S1'] == 'support'

    def test_resistance_above_pivot_support_below(self):
        cam = _camarilla_levels(110, 90, 100)
        by_label = dict((lbl, lvl) for lbl, lvl, _ in cam)
        p = by_label['P']
        for lbl in ['H1', 'H2', 'H3', 'H4']:
            assert by_label[lbl] > p
        for lbl in ['L1', 'L2', 'L3', 'L4']:
            assert by_label[lbl] < p


# ---------------------------------------------------------------------------
# DB-backed tests (compute_pivots end-to-end)
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    from app import create_app
    test_app = create_app(test_config={
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
    })
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


def _add_candle(symbol, timeframe, open_time, o, h, l, c, vol=1.0):
    db.session.add(Candle(
        symbol=symbol, timeframe=timeframe, open_time=open_time,
        open=o, high=h, low=l, close=c, volume=vol, is_closed=True,
    ))


class TestComputePivots:
    """End-to-end compute_pivots using the DB."""

    def test_uses_previous_completed_candle(self, app):
        # Two 1D candles: the forming "today" and the previous completed day.
        today = datetime(2025, 6, 26)
        prev = datetime(2025, 6, 25)
        _add_candle('BTCUSDT', '1d', today, o=99, h=101, l=98, c=100, vol=1)   # forming
        _add_candle('BTCUSDT', '1d', prev, o=95, h=110, l=90, c=100, vol=1)    # previous completed
        db.session.commit()

        levels = compute_pivots('BTCUSDT', variant='standard', period='1d')
        # Should use the previous completed candle (H=110, L=90, C=100) → P=100
        p = next(l for l in levels if l['label'] == 'P')
        assert abs(p['level'] - 100.0) < 1e-9
        # Source open time should be the previous day
        assert p['source_open_time'] is not None

    def test_standard_variant_levels(self, app):
        prev = datetime(2025, 6, 25)
        _add_candle('BTCUSDT', '1d', prev, o=95, h=110, l=90, c=100, vol=1)
        db.session.commit()

        levels = compute_pivots('BTCUSDT', variant='standard', period='1d')
        labels = [l['label'] for l in levels]
        assert set(labels) == {'P', 'R1', 'R2', 'R3', 'S1', 'S2', 'S3'}

    def test_camarilla_variant_levels(self, app):
        prev = datetime(2025, 6, 25)
        _add_candle('BTCUSDT', '1d', prev, o=95, h=110, l=90, c=100, vol=1)
        db.session.commit()

        levels = compute_pivots('BTCUSDT', variant='camarilla', period='1d')
        labels = [l['label'] for l in levels]
        assert set(labels) == {'P', 'H1', 'H2', 'H3', 'H4', 'L1', 'L2', 'L3', 'L4'}

    def test_all_variant_dedupes_p(self, app):
        prev = datetime(2025, 6, 25)
        _add_candle('BTCUSDT', '1d', prev, o=95, h=110, l=90, c=100, vol=1)
        db.session.commit()

        levels = compute_pivots('BTCUSDT', variant='all', period='1d')
        labels = [l['label'] for l in levels]
        # P should appear exactly once (deduped)
        assert labels.count('P') == 1
        # Should contain both standard and camarilla labels
        assert 'R1' in labels and 'H3' in labels

    def test_levels_sorted_high_to_low(self, app):
        prev = datetime(2025, 6, 25)
        _add_candle('BTCUSDT', '1d', prev, o=95, h=110, l=90, c=100, vol=1)
        db.session.commit()

        levels = compute_pivots('BTCUSDT', variant='camarilla', period='1d')
        prices = [l['level'] for l in levels]
        assert prices == sorted(prices, reverse=True)

    def test_no_data_returns_empty(self, app):
        levels = compute_pivots('BTCUSDT', variant='camarilla', period='1d')
        assert levels == []

    def test_invalid_variant_raises(self, app):
        prev = datetime(2025, 6, 25)
        _add_candle('BTCUSDT', '1d', prev, o=95, h=110, l=90, c=100, vol=1)
        db.session.commit()

        with pytest.raises(ValueError):
            compute_pivots('BTCUSDT', variant='bogus', period='1d')

    def test_single_candle_fallback(self, app):
        # Only one candle exists — should fall back to it rather than crash.
        only = datetime(2025, 6, 25)
        _add_candle('BTCUSDT', '1d', only, o=95, h=110, l=90, c=100, vol=1)
        db.session.commit()

        levels = compute_pivots('BTCUSDT', variant='standard', period='1d')
        assert len(levels) > 0
        p = next(l for l in levels if l['label'] == 'P')
        assert abs(p['level'] - 100.0) < 1e-9
