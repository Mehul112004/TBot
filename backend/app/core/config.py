"""
Core Application Configuration
Shared configuration constants used across modules.
"""

CANDLE_WARMUP = 400
SUPPORTED_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT']

# ── Indian Market Configuration ──

SUPPORTED_INDIAN_EQUITY_SYMBOLS = [
    'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
    'ITC', 'SBIN', 'BHARTIARTL', 'KOTAKBANK', 'LT',
    'AXISBANK', 'WIPRO', 'HCLTECH', 'SUNPHARMA', 'TITAN',
    'MARUTI', 'TATAMOTORS', 'BAJFINANCE', 'ASIANPAINT', 'NESTLEIND',
]

SUPPORTED_INDIAN_INDEX_SYMBOLS = ['NIFTY', 'BANKNIFTY', 'SENSEX', 'FINNIFTY']

# Merge for UI dropdown
SUPPORTED_INDIAN_SYMBOLS = SUPPORTED_INDIAN_INDEX_SYMBOLS + SUPPORTED_INDIAN_EQUITY_SYMBOLS

# Round-number S/R detection thresholds for Indian instruments
INDIAN_ROUND_NUMBER_CONFIG = {
    'NIFTY': {'small': 50, 'large': 100},
    'BANKNIFTY': {'small': 100, 'large': 500},
    'SENSEX': {'small': 100, 'large': 500},
    'FINNIFTY': {'small': 50, 'large': 100},
    'DEFAULT': {'small': 10, 'large': 50},
}

INDIAN_MARKET_SESSION = {
    'pre_open_start': '09:00',
    'pre_open_end': '09:15',
    'trading_start': '09:15',
    'trading_end': '15:30',
    'closing_start': '15:30',
    'closing_end': '15:40',
    'timezone': 'Asia/Kolkata',
}

# Strategy parameter overrides for Indian market (tighter SL, lower ATR)
INDIAN_STRATEGY_OVERRIDES = {
    'Trend Following': {
        'sl_atr_mult': 1.2,
        'min_confidence': 0.50,
    },
    'Breakout & Retest': {
        'sl_atr_mult': 1.0,
        'min_confidence': 0.50,
    },
    'Key Level Reversal': {
        'min_confidence': 0.65,
    },
}
