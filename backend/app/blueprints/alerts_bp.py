import uuid
from datetime import datetime

from flask import Blueprint, request, jsonify

from app.models.db import db, PriceAlert
from app.core.price_alert_tracker import price_alert_tracker
from app.core.sse import sse_manager

alerts_bp = Blueprint('alerts', __name__)


@alerts_bp.route('', methods=['GET'])
def list_alerts():
    status = request.args.get('status')
    query = PriceAlert.query
    if status:
        query = query.filter_by(status=status.upper())
    alerts = query.order_by(PriceAlert.created_at.desc()).all()
    return jsonify({'alerts': [a.to_dict() for a in alerts], 'count': len(alerts)}), 200


@alerts_bp.route('', methods=['POST'])
def create_alert():
    body = request.get_json(silent=True) or {}
    symbol = body.get('symbol')
    target_price = body.get('target_price')
    direction = body.get('direction')
    alert_type = body.get('alert_type', 'ONCE')
    note = body.get('note', '')

    if not symbol:
        return jsonify({'error': 'Missing required field: symbol'}), 400
    if target_price is None:
        return jsonify({'error': 'Missing required field: target_price'}), 400
    if direction not in ('ABOVE', 'BELOW'):
        return jsonify({'error': 'direction must be ABOVE or BELOW'}), 400
    if alert_type not in ('ONCE', 'EVERY_TIME'):
        return jsonify({'error': 'alert_type must be ONCE or EVERY_TIME'}), 400

    try:
        target_price = float(target_price)
    except (TypeError, ValueError):
        return jsonify({'error': 'target_price must be a number'}), 400

    alert = PriceAlert(
        id=str(uuid.uuid4()),
        symbol=symbol.upper(),
        target_price=target_price,
        direction=direction,
        alert_type=alert_type,
        status='ACTIVE',
        cross_state=None,
        note=note,
    )
    db.session.add(alert)
    db.session.commit()

    price_alert_tracker.add_to_cache(alert)

    alert_dict = alert.to_dict()
    sse_manager.publish('price_alert_created', alert_dict)

    return jsonify({'alert': alert_dict}), 201


@alerts_bp.route('/<alert_id>', methods=['GET'])
def get_alert(alert_id):
    alert = PriceAlert.query.get(alert_id)
    if not alert:
        return jsonify({'error': f'Alert not found: {alert_id}'}), 404
    return jsonify({'alert': alert.to_dict()}), 200


@alerts_bp.route('/<alert_id>', methods=['DELETE'])
def cancel_alert(alert_id):
    alert = PriceAlert.query.get(alert_id)
    if not alert:
        return jsonify({'error': f'Alert not found: {alert_id}'}), 404
    if alert.status in ('CANCELLED',):
        return jsonify({'error': 'Alert is already cancelled'}), 400

    alert.status = 'CANCELLED'
    alert.cancelled_at = datetime.utcnow()
    db.session.commit()

    price_alert_tracker.remove_from_cache(alert_id)

    alert_dict = alert.to_dict()
    sse_manager.publish('price_alert_cancelled', alert_dict)

    return jsonify({'alert': alert_dict}), 200
