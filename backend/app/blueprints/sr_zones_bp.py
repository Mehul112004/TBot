"""
S/R Zones API Blueprint
Endpoints:
  GET  /api/sr-zones           — Fetch stored S/R zones with MTF confluence + optional round numbers
  POST /api/sr-zones/refresh   — Manually trigger a full zone refresh for a symbol
  GET  /api/sr-zones/pivots    — Compute pivot-point levels (Camarilla/Standard) from prev period
  GET  /api/smc-zones          — Compute FVG/OB zones from candle data on-the-fly
"""

from flask import Blueprint, request, jsonify
import pandas as pd
from app.models.db import db, SRZone, Candle
from app.core.sr_engine import SREngine
from app.core.config import SUPPORTED_SYMBOLS
from app.core.pivot_engine import compute_pivots

sr_zones_bp = Blueprint('sr_zones', __name__)

# Canonical higher-timeframe ladder (low → high), the clean set we stack onto a
# viewed lower-timeframe chart (FIX-SR-MTF). Excludes intermediate TFs (2h, 6h,
# 8h, 12h, 3d) to keep the chart readable: a view shows itself + 2 HTFs up this
# ladder (e.g. 1h → 1h + 4h + 1d).
HTF_LADDER = ['15m', '1h', '4h', '1d', '1w']

# Full canonical ordering used to rank arbitrary viewed timeframes against the
# ladder (covers 5m/30m which aren't in the ladder but can be viewed).
TF_RANK = {
    '1m': 0, '3m': 1, '5m': 2, '15m': 3, '30m': 4, '1h': 5, '2h': 6,
    '4h': 7, '6h': 8, '8h': 9, '12h': 10, '1d': 11, '3d': 12, '1w': 13,
}


def _htf_stack(viewed_tf: str, depth: int) -> list[str]:
    """
    Return the viewed timeframe plus the next `depth` ladder timeframes that are
    strictly higher than it. A viewed TF not in the ladder (e.g. 5m, 30m) is
    still included first, and the HTFs are taken from the ladder above its rank.
    """
    viewed_rank = TF_RANK.get(viewed_tf, 0)
    stack = [viewed_tf]
    for tf in HTF_LADDER:
        if TF_RANK.get(tf, 0) > viewed_rank and len(stack) <= depth:
            stack.append(tf)
    return stack


def _zones_overlap(a: dict, b: dict) -> bool:
    """True if two zone bands [zone_lower, zone_upper] overlap."""
    return (
        a.get('zone_lower') is not None
        and a.get('zone_upper') is not None
        and b.get('zone_lower') is not None
        and b.get('zone_upper') is not None
        and a['zone_lower'] <= b['zone_upper']
        and a['zone_upper'] >= b['zone_lower']
    )


@sr_zones_bp.route('', methods=['GET'])
def get_sr_zones():
    """
    Get stored S/R zones for a given symbol, with multi-timeframe (MTF)
    confluence and optional psychological round-number sub-layer.

    Query params:
        symbol (required): Trading pair, e.g. 'BTCUSDT'
        timeframe (required): The viewed timeframe. Its own zones plus the next
                              `htf_depth` higher timeframes are returned.
        min_touches (optional): Minimum touch count to include (default 3)
        limit (optional): Top-N zones per timeframe, by strength (default 8)
        include_htf (optional): Stack higher-timeframe zones (default true)
        htf_depth (optional): How many HTFs to stack (default 2)
        include_round_numbers (optional): Emit a separate round_numbers array
                                           of large-grain psychological levels (default false)
        near_price (optional): Only return zones within ±3% of this price

    Returns:
        JSON with `zones` (MTF, each tagged with origin timeframe + confluence
        flags), optional `round_numbers`, and metadata.
    """
    symbol = request.args.get('symbol')
    if not symbol:
        return jsonify({'error': 'Missing required query parameter: symbol'}), 400

    viewed_tf = request.args.get('timeframe')
    if not viewed_tf:
        return jsonify({'error': 'Missing required query parameter: timeframe'}), 400

    min_touches = request.args.get('min_touches', 3, type=int)
    limit = request.args.get('limit', 8, type=int)
    include_htf = request.args.get('include_htf', 'true').lower() in ('true', '1', 'yes')
    htf_depth = request.args.get('htf_depth', 2, type=int)
    include_round_numbers = request.args.get(
        'include_round_numbers', 'false'
    ).lower() in ('true', '1', 'yes')
    near_price = request.args.get('near_price', type=float)

    try:
        # Timeframes to fetch: viewed + HTF stack
        tfs = _htf_stack(viewed_tf, htf_depth) if include_htf else [viewed_tf]

        # Per-TF top-N zones by strength, filtered by min_touches (+near_price)
        zones_by_tf: dict[str, list[dict]] = {}
        all_zones: list[dict] = []

        for tf in tfs:
            q = SRZone.query.filter_by(symbol=symbol, timeframe=tf)
            if min_touches > 0:
                q = q.filter(SRZone.touch_count >= min_touches)
            if near_price:
                pl = near_price * 0.97
                pu = near_price * 1.03
                q = q.filter(SRZone.price_level >= pl, SRZone.price_level <= pu)
            rows = q.order_by(SRZone.strength_score.desc()).limit(limit).all()
            tf_zones = [z.to_dict() for z in rows]
            zones_by_tf[tf] = tf_zones
            all_zones.extend(tf_zones)

        # ── Confluence: a viewed-TF zone is "confluence" if its band overlaps
        #    any HTF zone's band (band overlap ≈ centres within 0.5×ATR since
        #    bands are ±0.25×ATR wide). HTF zones are also flagged if they
        #    overlap a viewed-TF zone. ──
        htf_tfs = [tf for tf in tfs if tf != viewed_tf]
        htf_zones = [z for tf in htf_tfs for z in zones_by_tf.get(tf, [])]
        viewed_zones = zones_by_tf.get(viewed_tf, [])

        for z in all_zones:
            z['confluence'] = False
            z['confluence_with'] = []

        for vz in viewed_zones:
            for hz in htf_zones:
                if _zones_overlap(vz, hz):
                    vz['confluence'] = True
                    hz['confluence'] = True
                    if hz['timeframe'] not in vz['confluence_with']:
                        vz['confluence_with'].append(hz['timeframe'])
                    if viewed_tf not in hz['confluence_with']:
                        hz['confluence_with'].append(viewed_tf)

        # Determine last refresh time across all returned zones
        last_refreshed = None
        if all_zones:
            updated = [z.get('updated_at') for z in all_zones if z.get('updated_at')]
            if updated:
                last_refreshed = max(updated)

        response = {
            'symbol': symbol,
            'timeframe': viewed_tf,
            'zones': all_zones,
            'count': len(all_zones),
            'last_refreshed': last_refreshed,
            'filters': {
                'min_touches': min_touches,
                'limit': limit,
                'include_htf': include_htf,
                'htf_depth': htf_depth,
                'timeframes': tfs,
                'near_price': near_price,
            },
        }

        # ── Round-number sub-layer (large grain only, separate from S/R) ──
        if include_round_numbers:
            response['round_numbers'] = _compute_round_numbers(symbol, viewed_tf, near_price)

        return jsonify(response), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def _compute_round_numbers(symbol: str, viewed_tf: str, near_price: float | None) -> list[dict]:
    """
    Compute large-grain psychological round-number levels covering the visible
    price range. Not merged into swing zones, not subject to min-touches/top-N.
    Capped to ~6 levels nearest the current price.
    """
    candles = (
        Candle.query
        .filter_by(symbol=symbol, timeframe=viewed_tf)
        .order_by(Candle.open_time.desc())
        .limit(250)
        .all()
    )
    if not candles:
        return []

    closes = [float(c.close) for c in candles]
    current_price = closes[0]
    price_min, price_max = min(closes), max(closes)

    raw = SREngine.detect_round_numbers(
        symbol, current_price, price_range=(price_min, price_max), grain='large',
    )

    # Keep the ~6 nearest to current price
    raw.sort(key=lambda z: abs(z['price_level'] - current_price))
    raw = raw[:6]
    # Sort back to price order for stable rendering
    raw.sort(key=lambda z: z['price_level'])

    return [
        {
            'price_level': z['price_level'],
            'zone_type': z['zone_type'],
        }
        for z in raw
    ]


@sr_zones_bp.route('/pivots', methods=['GET'])
def get_pivots():
    """
    Compute pivot-point levels (Camarilla / Standard / both) from the previous
    completed period's candle. Levels are NOT persisted — computed per request.

    Query params:
        symbol (required): Trading pair, e.g. 'BTCUSDT'
        variant (optional): 'camarilla' (default) | 'standard' | 'all'
        period (optional): Source candle timeframe — '1d' (previous UTC day,
                           default) or '1w' (previous ISO week)

    Returns:
        JSON with `levels` (resistance → pivot → support, top to bottom),
        `source_open_time`, and metadata.
    """
    symbol = request.args.get('symbol')
    if not symbol:
        return jsonify({'error': 'Missing required query parameter: symbol'}), 400

    variant = request.args.get('variant', 'camarilla')
    period = request.args.get('period', '1d')

    try:
        levels = compute_pivots(symbol, variant=variant, period=period)
        source_open_time = levels[0]['source_open_time'] if levels else None

        return jsonify({
            'symbol': symbol,
            'variant': variant,
            'period': period,
            'levels': levels,
            'count': len(levels),
            'source_open_time': source_open_time,
        }), 200

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@sr_zones_bp.route('/refresh', methods=['POST'])
def refresh_zones():
    """
    Manually trigger a full S/R zone refresh (with stale-row pruning).

    Recomputes zones from scratch via SREngine.full_refresh(), which now
    (a) uses the de-bloated detection pipeline and (b) prunes any existing
    rows for the symbol/timeframe that have <2 touches under the new scoring
    — i.e. leftovers from older regimes are wiped on refresh.

    Body (JSON):
        symbol (required): Trading pair to refresh. Use 'all' for all supported symbols.
        timeframe (optional): Specific timeframe. Default: refreshes the full
                              chart stack — ['15m', '1h', '4h', '1d'] — so the
                              MTF endpoint returns freshly-scored zones for the
                              viewed TF and its 2 HTFs.
    """
    body = request.get_json(silent=True) or {}
    symbol = body.get('symbol')

    if not symbol:
        return jsonify({'error': 'Missing required field: symbol'}), 400

    # Refresh the full MTF ladder by default so the chart shows fresh data on
    # every layer, not just the layer the caller names.
    timeframes = ['15m', '1h', '4h', '1d']
    target_timeframe = body.get('timeframe')
    if target_timeframe:
        timeframes = [target_timeframe]

    symbols = SUPPORTED_SYMBOLS if symbol == 'all' else [symbol]

    try:
        total_zones = 0
        results = []

        for sym in symbols:
            for tf in timeframes:
                # full_refresh detects + persists + prunes stale <2-touch rows.
                SREngine.full_refresh(sym, tf)
                # Report the count of valid (>=2-touch) zones now in the DB.
                kept = SRZone.query.filter(
                    SRZone.symbol == sym,
                    SRZone.timeframe == tf,
                    SRZone.touch_count >= 2,
                ).count()
                total_zones += kept
                results.append({
                    'symbol': sym,
                    'timeframe': tf,
                    'zones_kept': kept,
                })

        return jsonify({
            'message': f'Zone refresh complete. {total_zones} zones kept (stale rows pruned).',
            'results': results,
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@sr_zones_bp.route('/smc-zones', methods=['GET'])
def get_smc_zones():
    """
    Compute Fair Value Gaps (FVGs) and Order Blocks (OBs) on-the-fly
    from candle data. Zones are NOT persisted — computed in-memory per request.

    Query params:
        symbol (required): Trading pair, e.g. 'BTCUSDT'
        timeframe (required): Candle timeframe (e.g. '1h', '4h')
        limit (optional): How many candles to scan (default 200)

    Returns:
        JSON with list of active FVG and OB zones.
    """
    symbol = request.args.get('symbol')
    if not symbol:
        return jsonify({'error': 'Missing required query parameter: symbol'}), 400

    timeframe = request.args.get('timeframe', '1h')
    limit = request.args.get('limit', 200, type=int)

    try:
        from app.core.data_utils import get_finalized_candles, StaleDataError
        from app.strategies.archive.smc_v1.market_structure import extract_fvgs, extract_order_blocks
        from app.strategies.archive.smc_v1.events import detect_choch, detect_liquidity_sweep

        try:
            df = get_finalized_candles(symbol, timeframe, limit=limit)
        except StaleDataError as e:
            # Stale candle data (e.g. an imported-but-not-streamed symbol, or a
            # disconnected WebSocket). Degrade gracefully: return an empty SMC
            # zone set so the chart still renders the candle / S/R / pivot
            # layers instead of applying a 500 that blocks the whole page.
            return jsonify({
                'symbol': symbol,
                'timeframe': timeframe,
                'zones': [],
                'count': 0,
                'warning': f'Candle data is stale — SMC zones unavailable. {e}',
            }), 200

        if len(df) == 0:
            return jsonify({'symbol': symbol, 'timeframe': timeframe, 'zones': [], 'count': 0}), 200

        df = extract_fvgs(df)
        df = extract_order_blocks(df)
        df = detect_choch(df)
        df = detect_liquidity_sweep(df)

        import numpy as np
        zones = []

        # ── Active FVGs ──
        active_fvg_rows = df[df['fvg_active'] == True]
        for _, row in active_fvg_rows.iterrows():
            upper = float(row['fvg_upper']) if not pd.isna(row.get('fvg_upper')) else None
            lower = float(row['fvg_lower']) if not pd.isna(row.get('fvg_lower')) else None
            if upper is None or lower is None:
                continue
            direction = 'bullish' if upper > lower else 'bearish'
            zones.append({
                'type': 'fvg',
                'direction': direction,
                'upper': upper,
                'lower': lower,
                'volume': float(row['fvg_volume']) if not pd.isna(row.get('fvg_volume')) else None,
                'created_at': str(row['fvg_created_at']) if not pd.isna(row.get('fvg_created_at')) else None,
                'active': True,
            })

        # ── Active OBs ──
        active_ob_rows = df[df['ob_active'] == True]
        for _, row in active_ob_rows.iterrows():
            upper = float(row['ob_upper']) if not pd.isna(row.get('ob_upper')) else None
            lower = float(row['ob_lower']) if not pd.isna(row.get('ob_lower')) else None
            if upper is None or lower is None:
                continue
            zones.append({
                'type': 'ob',
                'direction': str(row.get('ob_direction', 'bullish')),
                'upper': upper,
                'lower': lower,
                'volume': float(row['ob_volume']) if not pd.isna(row.get('ob_volume')) else None,
                'created_at': str(row['ob_created_at']) if not pd.isna(row.get('ob_created_at')) else None,
                'active': True,
            })

        # ── Historical ChoCh/BOS events and Regime changes ──
        prev_regime = None
        for idx, row in df.iterrows():
            open_time_str = str(row['open_time'])
            
            if row.get('event_choch_bullish', False):
                zones.append({'type': 'event', 'label': 'CHoCH', 'direction': 'bullish', 'active': False, 'time': open_time_str})
            elif row.get('event_choch_bearish', False):
                zones.append({'type': 'event', 'label': 'CHoCH', 'direction': 'bearish', 'active': False, 'time': open_time_str})
                
            if row.get('event_bos_bullish', False):
                zones.append({'type': 'event', 'label': 'BoS', 'direction': 'bullish', 'active': False, 'time': open_time_str})
            elif row.get('event_bos_bearish', False):
                zones.append({'type': 'event', 'label': 'BoS', 'direction': 'bearish', 'active': False, 'time': open_time_str})

        return jsonify({
            'symbol': symbol,
            'timeframe': timeframe,
            'zones': zones,
            'count': len(zones),
            'candles_scanned': len(df)
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
