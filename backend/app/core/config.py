"""
Core Application Configuration
Shared configuration constants used across modules.
"""

CANDLE_WARMUP = 400
SUPPORTED_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT']


def get_supported_symbols() -> list[str]:
    """
    Return the list of supported Binance futures symbols.
    Tries Binance exchange info first, falls back to hardcoded list.
    """
    try:
        from app.utils.binance import fetch_futures_symbols
        symbols = fetch_futures_symbols()
        return [s['symbol'] for s in symbols]
    except Exception:
        return SUPPORTED_SYMBOLS
