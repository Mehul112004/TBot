"""
Signals API Blueprint
Endpoints for analysis sessions, watching setups, and SSE streaming.

REST endpoints:
  GET    /api/signals/sessions         — List active analysis sessions
  POST   /api/signals/sessions         — Start a new analysis session
  DELETE /api/signals/sessions/<id>    — Stop an analysis session
  GET    /api/signals/watching          — Get all active watching setups
  GET    /api/signals/watching/<id>    — Get a specific watching setup
  GET    /api/signals/stream           — SSE event stream
"""

import json
import queue

from flask import Blueprint, request, jsonify, Response, stream_with_context

from app.core.sse import sse_manager

signals_bp = Blueprint('signals', __name__)


# ---------- Analysis Sessions ----------

@signals_bp.route('/sessions', methods=['GET'])
def list_sessions():
    """List all active analysis sessions."""
    from app.core.scanner import live_scanner
    sessions = live_scanner.get_active_sessions()
    return jsonify({'sessions': sessions, 'count': len(sessions)}), 200


@signals_bp.route('/sessions', methods=['POST'])
def start_session():
    """
    Start a new analysis session.

    Body (JSON):
        symbol (required): Trading pair, e.g. "BTCUSDT"
        strategy_names (required): List of strategy names to activate
    """
    body = request.get_json(silent=True) or {}
    symbol = body.get('symbol')
    strategy_names = body.get('strategy_names', [])
    timeframes = body.get('timeframes', None)
    market_type = body.get('market_type', 'CRYPTO')

    if not symbol:
        return jsonify({'error': 'Missing required field: symbol'}), 400
    if not strategy_names or not isinstance(strategy_names, list):
        return jsonify({'error': 'strategy_names must be a non-empty list'}), 400

    try:
        from app.core.scanner import live_scanner
        session = live_scanner.start_session(symbol, strategy_names, timeframes, market_type=market_type)
        return jsonify({'session': session}), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception(f"Failed to start session for {symbol}")
        return jsonify({'error': f'Failed to start session: {str(e)}'}), 500


@signals_bp.route('/sessions/<session_id>', methods=['DELETE'])
def stop_session(session_id):
    """Stop an analysis session by ID."""
    from app.core.scanner import live_scanner
    success = live_scanner.stop_session(session_id)
    if not success:
        return jsonify({'error': f'Session not found or already stopped: {session_id}'}), 404
    return jsonify({'message': f'Session {session_id} stopped'}), 200


# ---------- Watching Setups ----------

@signals_bp.route('/watching', methods=['GET'])
def list_watching():
    """
    Get all active watching setups.

    Query params:
        session_id (optional): Filter by session
        market_type (optional): Filter by market type (CRYPTO/INDIAN)
    """
    from app.core.watching import WatchingManager
    from app.models.db import WatchingSetup
    session_id = request.args.get('session_id')
    market_type = request.args.get('market_type')

    if market_type:
        query = WatchingSetup.query.filter_by(status='WATCHING', market_type=market_type)
        if session_id:
            query = query.filter_by(session_id=session_id)
        setups = query.order_by(WatchingSetup.detected_at.desc()).all()
        return jsonify({'setups': [s.to_dict() for s in setups], 'count': len(setups)}), 200

    setups = WatchingManager.get_active_setups(session_id)
    return jsonify({'setups': setups, 'count': len(setups)}), 200


@signals_bp.route('/watching/<setup_id>', methods=['GET'])
def get_watching(setup_id):
    """Get a specific watching setup by ID."""
    from app.core.watching import WatchingManager
    setup = WatchingManager.get_setup(setup_id)
    if not setup:
        return jsonify({'error': f'Setup not found: {setup_id}'}), 404
    return jsonify({'setup': setup}), 200


# ---------- Confirmed Signals ----------

@signals_bp.route('/confirmed', methods=['GET'])
def list_confirmed_signals():
    """
    Get all confirmed/modified signals that have passed the LLM filter.
    Includes the origin session_id by joining WatchingSetup.

    Query params:
        market_type (optional): Filter by market type (CRYPTO/INDIAN)
    """
    from app.models.db import db, ConfirmedSignal, WatchingSetup

    market_type = request.args.get('market_type')
    
    query = db.session.query(ConfirmedSignal, WatchingSetup.session_id)\
        .join(WatchingSetup, ConfirmedSignal.watching_setup_id == WatchingSetup.id)
    
    if market_type:
        query = query.filter(ConfirmedSignal.market_type == market_type)
    
    results = query.order_by(ConfirmedSignal.created_at.desc()).all()
        
    signals_list = []
    for sig, session_id in results:
        sig_dict = sig.to_dict()
        sig_dict['session_id'] = session_id
        signals_list.append(sig_dict)
        
    return jsonify({'signals': signals_list, 'count': len(signals_list)}), 200


@signals_bp.route('/rejected', methods=['GET'])
def list_rejected_signals():
    """
    Get all rejected signals from the LLM filter.
    Includes the origin session_id by joining WatchingSetup.

    Query params:
        market_type (optional): Filter by market type (CRYPTO/INDIAN)
    """
    from app.models.db import db, RejectedSignal, WatchingSetup

    market_type = request.args.get('market_type')
    
    query = db.session.query(RejectedSignal, WatchingSetup.session_id)\
        .join(WatchingSetup, RejectedSignal.watching_setup_id == WatchingSetup.id)
    
    if market_type:
        query = query.filter(RejectedSignal.market_type == market_type)
    
    results = query.order_by(RejectedSignal.created_at.desc()).all()
        
    signals_list = []
    for sig, session_id in results:
        sig_dict = sig.to_dict()
        sig_dict['session_id'] = session_id
        signals_list.append(sig_dict)
        
    return jsonify({'signals': signals_list, 'count': len(signals_list)}), 200


@signals_bp.route('/export/confirmed', methods=['GET'])
def export_confirmed_signals():
    """
    Export all confirmed signals up to today as a JSON file,
    excluding telegram specific fields.
    """
    from app.models.db import ConfirmedSignal
    from datetime import datetime

    signals = ConfirmedSignal.query.order_by(ConfirmedSignal.created_at.desc()).all()
    
    export_data = []
    for sig in signals:
        sig_dict = sig.to_dict()
        # Remove telegram specifics
        sig_dict.pop('telegram_status', None)
        sig_dict.pop('telegram_retries', None)
        sig_dict.pop('telegram_message_id', None)
        export_data.append(sig_dict)

    current_date = datetime.now().strftime('%Y-%m-%d')
    filename = f"{current_date}-confirmed-signals.json"

    return Response(
        json.dumps(export_data, indent=2),
        mimetype="application/json",
        headers={"Content-disposition": f"attachment; filename={filename}"}
    )


@signals_bp.route('/lm-studio-status', methods=['GET'])
def lm_studio_status():
    """
    Check if the local LM Studio instance is reachable.
    """
    from app.core.llm_client import LLMClient
    status = LLMClient.ping_status()
    return jsonify({'online': status}), 200


# ---------- LLM Prompt Logs ----------

@signals_bp.route('/llm_logs', methods=['GET'])
def get_llm_logs():
    """Get Paginated LLM Prompts & Responses for debugging."""
    from app.models.db import LLMPromptLog
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    logs = LLMPromptLog.query.order_by(LLMPromptLog.created_at.desc()).limit(limit).offset(offset).all()
    count = LLMPromptLog.query.count()
    
    return jsonify({
        'logs': [l.to_dict() for l in logs],
        'total': count,
        'limit': limit,
        'offset': offset
    }), 200



# ---------- Server-Sent Events ----------

@signals_bp.route('/stream')
def event_stream():
    """
    SSE endpoint — pushes real-time events to the frontend.

    Event types:
    - setup_detected: New watching card
    - setup_expired: Watching card expired
    - setup_updated: Existing watching card refreshed (dedup)
    - session_started: Analysis session started
    - session_stopped: Analysis session stopped
    - candle_close: Live candle close notification
    - price_update: Live price tick {session_id, symbol, price, timestamp}
    """
    def generate():
        q = sse_manager.subscribe()
        try:
            while True:
                try:
                    event = q.get(timeout=30)
                except queue.Empty:
                    # Send keepalive comment to prevent timeout
                    yield ": keepalive\n\n"
                    continue

                if event is None:
                    yield ": keepalive\n\n"
                else:
                    yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
        except GeneratorExit:
            sse_manager.unsubscribe(q)

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )
