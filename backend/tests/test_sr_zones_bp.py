"""
Integration tests for the S/R Zones API blueprint.
Covers the multi-timeframe (MTF) /sr-zones endpoint, confluence detection,
the round-numbers sub-layer, and the /sr-zones/pivots endpoint.
"""

import pytest
from datetime import datetime, timedelta

from app.models.db import db, SRZone, Candle


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


@pytest.fixture
def client(app):
    return app.test_client()


def _add_zone(symbol, timeframe, price_level, zone_upper, zone_lower,
              zone_type='support', method='swing', strength=0.5,
              touches=3, last_tested=None):
    db.session.add(SRZone(
        symbol=symbol,
        timeframe=timeframe,
        price_level=price_level,
        zone_upper=zone_upper,
        zone_lower=zone_lower,
        zone_type=zone_type,
        detection_method=method,
        strength_score=strength,
        touch_count=touches,
        last_tested=last_tested,
    ))


def _add_candle(symbol, timeframe, open_time, o, h, l, c, vol=1.0):
    db.session.add(Candle(
        symbol=symbol, timeframe=timeframe, open_time=open_time,
        open=o, high=h, low=l, close=c, volume=vol, is_closed=True,
    ))


class TestGetSRZonesMTF:
    """Tests for the multi-timeframe GET /api/sr-zones endpoint."""

    def test_requires_symbol(self, client):
        r = client.get('/api/sr-zones', query_string={'timeframe': '1h'})
        assert r.status_code == 400

    def test_requires_timeframe(self, client):
        r = client.get('/api/sr-zones', query_string={'symbol': 'BTCUSDT'})
        assert r.status_code == 400

    def test_mtf_returns_viewed_plus_htf(self, app, client):
        # Viewed 1h zone + 4h zone + 1d zone (next 2 HTFs up from 1h).
        _add_zone('BTCUSDT', '1h', 100.0, 102.0, 98.0, touches=5)
        _add_zone('BTCUSDT', '4h', 110.0, 112.0, 108.0, touches=4)
        _add_zone('BTCUSDT', '1d', 120.0, 122.0, 118.0, touches=6)
        db.session.commit()

        r = client.get('/api/sr-zones', query_string={
            'symbol': 'BTCUSDT', 'timeframe': '1h', 'min_touches': 3,
        })
        assert r.status_code == 200
        body = r.get_json()
        tfs = {z['timeframe'] for z in body['zones']}
        # Viewed 1h + next 2 HTFs (4h, 1d) should all be present
        assert tfs == {'1h', '4h', '1d'}
        assert body['count'] == 3
        assert body['filters']['timeframes'] == ['1h', '4h', '1d']

    def test_min_touches_filter(self, app, client):
        _add_zone('BTCUSDT', '1h', 100.0, 101.0, 99.0, touches=2)
        _add_zone('BTCUSDT', '1h', 110.0, 111.0, 109.0, touches=5)
        db.session.commit()

        r = client.get('/api/sr-zones', query_string={
            'symbol': 'BTCUSDT', 'timeframe': '1h', 'min_touches': 3,
        })
        body = r.get_json()
        assert len(body['zones']) == 1
        assert body['zones'][0]['touch_count'] == 5

    def test_confluence_flagged_on_overlap(self, app, client):
        # Viewed 1h zone band 98-102 overlaps 4h zone band 99-103.
        _add_zone('BTCUSDT', '1h', 100.0, 102.0, 98.0, touches=4)
        _add_zone('BTCUSDT', '4h', 101.0, 103.0, 99.0, touches=4)
        # 1d zone far away — no overlap.
        _add_zone('BTCUSDT', '1d', 200.0, 202.0, 198.0, touches=4)
        db.session.commit()

        r = client.get('/api/sr-zones', query_string={
            'symbol': 'BTCUSDT', 'timeframe': '1h', 'min_touches': 3,
        })
        body = r.get_json()
        by_tf = {}
        for z in body['zones']:
            by_tf.setdefault(z['timeframe'], []).append(z)

        vz = by_tf['1h'][0]
        hz = by_tf['4h'][0]
        nz = by_tf['1d'][0]

        assert vz['confluence'] is True
        assert '4h' in vz['confluence_with']
        assert hz['confluence'] is True
        assert '1h' in hz['confluence_with']
        # Non-overlapping 1d zone is not confluence
        assert nz['confluence'] is False

    def test_include_htf_false_returns_only_viewed(self, app, client):
        _add_zone('BTCUSDT', '1h', 100.0, 101.0, 99.0, touches=4)
        _add_zone('BTCUSDT', '4h', 110.0, 111.0, 109.0, touches=4)
        db.session.commit()

        r = client.get('/api/sr-zones', query_string={
            'symbol': 'BTCUSDT', 'timeframe': '1h', 'min_touches': 3,
            'include_htf': 'false',
        })
        body = r.get_json()
        tfs = {z['timeframe'] for z in body['zones']}
        assert tfs == {'1h'}

    def test_top_n_limit_per_tf(self, app, client):
        # 10 zones on 1h, limit=3 → only 3 returned for 1h.
        for i in range(10):
            _add_zone('BTCUSDT', '1h', 100.0 + i * 10, 101.0 + i * 10,
                      99.0 + i * 10, touches=4, strength=0.1 * i)
        db.session.commit()

        r = client.get('/api/sr-zones', query_string={
            'symbol': 'BTCUSDT', 'timeframe': '1h', 'min_touches': 3, 'limit': 3,
        })
        body = r.get_json()
        one_h = [z for z in body['zones'] if z['timeframe'] == '1h']
        assert len(one_h) == 3
        # Should be the 3 strongest (strength 0.9, 0.8, 0.7)
        strengths = sorted([z['strength_score'] for z in one_h], reverse=True)
        assert strengths[0] == 0.9

    def test_round_numbers_sublayer(self, app, client):
        # Need candle data for the viewed TF to compute the price range.
        for i in range(30):
            _add_candle('BTCUSDT', '1h',
                        datetime(2025, 6, 1) + timedelta(hours=i),
                        o=67000, h=67500, l=66500, c=67000 + i * 10)
        _add_zone('BTCUSDT', '1h', 67000.0, 67100.0, 66900.0, touches=4)
        db.session.commit()

        r = client.get('/api/sr-zones', query_string={
            'symbol': 'BTCUSDT', 'timeframe': '1h', 'min_touches': 3,
            'include_round_numbers': 'true',
        })
        body = r.get_json()
        assert 'round_numbers' in body
        assert isinstance(body['round_numbers'], list)
        # Large grain for BTC = 5000; near 67k we expect 65000 and/or 70000.
        levels = [rn['price_level'] for rn in body['round_numbers']]
        assert 65000.0 in levels
        assert 70000.0 in levels

    def test_round_numbers_omitted_by_default(self, app, client):
        _add_zone('BTCUSDT', '1h', 100.0, 101.0, 99.0, touches=4)
        db.session.commit()

        r = client.get('/api/sr-zones', query_string={
            'symbol': 'BTCUSDT', 'timeframe': '1h', 'min_touches': 3,
        })
        body = r.get_json()
        assert 'round_numbers' not in body


class TestPivotsEndpoint:
    """Tests for GET /api/sr-zones/pivots."""

    def test_pivots_camarilla(self, app, client):
        # Previous completed 1D candle: H=110, L=90, C=100.
        _add_candle('BTCUSDT', '1d', datetime(2025, 6, 25),
                    o=95, h=110, l=90, c=100)
        _add_candle('BTCUSDT', '1d', datetime(2025, 6, 26),
                    o=99, h=101, l=98, c=100)  # forming "today"
        db.session.commit()

        r = client.get('/api/sr-zones/pivots', query_string={
            'symbol': 'BTCUSDT', 'variant': 'camarilla', 'period': '1d',
        })
        assert r.status_code == 200
        body = r.get_json()
        labels = [l['label'] for l in body['levels']]
        assert 'P' in labels
        assert 'H3' in labels and 'L3' in labels
        assert 'H4' in labels and 'L4' in labels
        # P should be 100 (from prev completed candle)
        p = next(l for l in body['levels'] if l['label'] == 'P')
        assert abs(p['level'] - 100.0) < 1e-9

    def test_pivots_invalid_variant(self, client):
        r = client.get('/api/sr-zones/pivots', query_string={
            'symbol': 'BTCUSDT', 'variant': 'bogus',
        })
        assert r.status_code == 400

    def test_pivots_no_symbol(self, client):
        r = client.get('/api/sr-zones/pivots')
        assert r.status_code == 400

    def test_pivots_empty_when_no_data(self, client):
        r = client.get('/api/sr-zones/pivots', query_string={
            'symbol': 'BTCUSDT', 'variant': 'camarilla',
        })
        assert r.status_code == 200
        body = r.get_json()
        assert body['levels'] == []
        assert body['count'] == 0
