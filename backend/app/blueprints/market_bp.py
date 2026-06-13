"""Market API Blueprint — endpoints for market status, instruments, and option chains."""

from flask import Blueprint, request, jsonify

market_bp = Blueprint('market', __name__)


@market_bp.route('/status', methods=['GET'])
def market_status():
    """Return open/closed status for all registered market types."""
    from app.providers import get_provider, list_providers

    statuses = {}
    for mt in list_providers():
        provider = get_provider(mt)
        if provider:
            statuses[mt.lower()] = {
                'is_open': provider.is_market_open(),
                'hours': provider.get_market_hours(),
            }
    return jsonify(statuses), 200


@market_bp.route('/instruments', methods=['GET'])
def search_instruments():
    """Search Indian instruments by name/symbol."""
    market_type = request.args.get('market_type', 'INDIAN').upper()
    query = request.args.get('q', '')

    if market_type != 'INDIAN':
        return jsonify({'error': 'Instrument search only available for INDIAN market'}), 400
    if not query or len(query) < 1:
        return jsonify({'error': 'Query parameter q is required'}), 400

    from app.providers import get_provider
    provider = get_provider('INDIAN')
    if not provider:
        return jsonify({'error': 'Indian market provider not available'}), 503

    results = provider.search_instruments(query)
    return jsonify({'instruments': results, 'count': len(results)}), 200


@market_bp.route('/option-chain', methods=['GET'])
def option_chain():
    """Get option chain for a given symbol and expiry date."""
    symbol = request.args.get('symbol', '')
    expiry = request.args.get('expiry', '')

    if not symbol:
        return jsonify({'error': 'Symbol parameter is required'}), 400
    if not expiry:
        return jsonify({'error': 'Expiry parameter is required (YYYY-MM-DD)'}), 400

    from app.providers import get_provider
    provider = get_provider('INDIAN')
    if not provider:
        return jsonify({'error': 'Indian market provider not available'}), 503

    results = provider.get_option_chain(symbol, expiry)
    return jsonify({'chain': results, 'count': len(results)}), 200
