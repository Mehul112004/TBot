# Backend Architecture Changes

## Overview

The core change is introducing a **market provider abstraction layer**. Instead of hardcoding Binance throughout the scanner and data utilities, everything flows through an `AbstractMarketProvider` interface. Two implementations exist:

- `BinanceProvider` — existing Binance Futures functionality, refactored
- `AngelOneProvider` — new Indian market data source

## 1. Provider Abstraction Layer

**New directory:** `backend/app/providers/`

```
backend/app/providers/
├── __init__.py
├── base.py                  # AbstractMarketProvider ABC
├── binance_provider.py      # Binance implementation (refactored from utils/binance.py)
└── angelone_provider.py     # Angel One Smart API implementation
```

### `AbstractMarketProvider` Interface

File: `backend/app/providers/base.py`

```python
from abc import ABC, abstractmethod
from typing import Optional, Callable, List

class AbstractMarketProvider(ABC):
    """Base interface for all market data providers."""

    market_type: str  # 'CRYPTO' or 'INDIAN'

    @abstractmethod
    def fetch_candles(
        self, symbol: str, timeframe: str,
        start_time_ms: int, end_time_ms: int
    ) -> List[dict]:
        """
        Fetch historical OHLCV candles.
        Returns list of dicts with keys:
        symbol, timeframe, open_time, open, high, low, close, volume
        """
        ...

    @abstractmethod
    def create_stream(
        self,
        symbol: str,
        timeframes: List[str],
        on_candle_close: Callable,
        on_price_update: Callable,
        on_live_candle: Optional[Callable] = None,
        on_reconnect: Optional[Callable] = None,
    ) -> 'AbstractStreamManager':
        """Create a live data stream for the given symbol and timeframes."""
        ...

    @abstractmethod
    def get_market_hours(self) -> dict:
        """Returns dict with: open_utc, close_utc, pre_open_utc, timezone."""
        ...

    @abstractmethod
    def is_market_open(self) -> bool:
        """Check if the market is currently open for trading."""
        ...

    @abstractmethod
    def resolve_symbol(self, search_key: str) -> str:
        """
        Resolve a human-readable symbol to the provider's native format.
        Crypto: 'BTCUSDT' -> 'BTCUSDT' (passthrough)
        Indian: 'RELIANCE' -> '2885' (token lookup)
        """
        ...

    @property
    @abstractmethod
    def supported_timeframes(self) -> List[str]:
        """Timeframes available for this market."""
        ...

    @abstractmethod
    def get_lot_size(self, symbol: str) -> int:
        """Lot size for the instrument (1 for crypto, variable for F&O)."""
        ...
```

### `AbstractStreamManager`

```python
class AbstractStreamManager(ABC):
    """Base interface for WebSocket stream management."""

    @abstractmethod
    def start(self):
        """Start the WebSocket stream in background."""
        ...

    @abstractmethod
    def stop(self):
        """Stop the WebSocket stream and clean up."""
        ...

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Whether the stream is currently active."""
        ...
```

### `BinanceProvider`

File: `backend/app/providers/binance_provider.py`

- Refactor `backend/app/utils/binance.py` into this file
- `BinanceStreamManager` already implements the pattern — wrap it in `BinanceStreamAdapter`
- `fetch_candles()` wraps existing `fetch_klines()`
- `market_type = 'CRYPTO'`
- `supported_timeframes = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w']`
- `is_market_open()` always returns `True` (24/7)
- Backward compatible: old code importing from `utils/binance.py` can be migrated gradually

### `AngelOneProvider`

File: `backend/app/providers/angelone_provider.py`

**Dependencies:** `smartapi-python` package

**Authentication:**
```python
from smartapi import SmartConnect

class AngelOneProvider(AbstractMarketProvider):
    market_type = 'INDIAN'
    supported_timeframes = ['1m', '5m', '15m', '30m', '1h', '1d']

    def __init__(self):
        self.api_key = os.environ['ANGELONE_API_KEY']
        self.client_code = os.environ['ANGELONE_CLIENT_CODE']
        self.password = os.environ['ANGELONE_PASSWORD']
        self.totp_secret = os.environ.get('ANGELONE_TOTP_SECRET')
        self._smart = None
        self._feed_token = None
        self._refresh_token = None
        self._token_map: dict[str, str] = {}  # symbol -> token
        self._reverse_token_map: dict[str, str] = {}  # token -> symbol

    def connect(self):
        """Authenticate and obtain tokens."""
        self._smart = SmartConnect(api_key=self.api_key)
        totp = pyotp.TOTP(self.totp_secret).now() if self.totp_secret else None
        data = self._smart.generateSession(self.client_code, self.password, totp)
        self._refresh_token = data['data']['refreshToken']
        self._feed_token = self._smart.getfeedToken()
        self._sync_instruments()

    def _sync_instruments(self):
        """Pull instrument master and populate token maps."""
        # Angel One provides instrument dump via API or file
        # Store in indian_instruments DB table
        # Build self._token_map and self._reverse_token_map
        ...

    def resolve_symbol(self, search_key: str) -> str:
        """e.g., 'RELIANCE' -> '2885' (token)"""
        return self._token_map.get(search_key.upper(), search_key)

    def fetch_candles(self, symbol, timeframe, start_ms, end_ms):
        """Map timeframe to Angel One interval enum, call getCandleData."""
        ...

    def create_stream(self, ...):
        """Create AngelOneStreamManager with token-based subscription."""
        ...

    def get_market_hours(self):
        return {
            'open_utc': '03:45',     # 9:15 IST
            'close_utc': '10:00',    # 15:30 IST
            'pre_open_utc': '03:30', # 9:00 IST
            'timezone': 'Asia/Kolkata',
        }

    def is_market_open(self):
        now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        weekday = now_ist.weekday()
        if weekday >= 5:  # Saturday/Sunday
            return False
        time_str = now_ist.strftime('%H:%M')
        return '09:15' <= time_str <= '15:30'
```

**WebSocket Details:**

Angel One uses token-based WS subscriptions:
```python
# Subscribe to tokens: [token1, token2, ...]
# Callback receives: {token, exchange, last_traded_price, open, high, low, close, volume, ...}
```

The `AngelOneStreamManager` normalizes this to the same internal format as Binance:

```python
def _normalize_candle(self, tick_data, timeframe) -> dict:
    return {
        "symbol": self._reverse_token_map[tick_data['token']],
        "timeframe": timeframe,
        "open_time": datetime.fromtimestamp(tick_data['timestamp'] / 1000, tz=timezone.utc),
        "open": float(tick_data['open']),
        "high": float(tick_data['high']),
        "low": float(tick_data['low']),
        "close": float(tick_data['close']),
        "volume": float(tick_data['volume']),
    }
```

## 2. Provider Registry

File: `backend/app/providers/__init__.py`

```python
from app.providers.binance_provider import BinanceProvider
from app.providers.angelone_provider import AngelOneProvider

PROVIDERS = {
    'CRYPTO': BinanceProvider(),
    'INDIAN': AngelOneProvider(),
}

def get_provider(market_type: str) -> AbstractMarketProvider:
    return PROVIDERS[market_type.upper()]
```

## 3. Scanner Changes

File: `backend/app/core/scanner.py`

### `AnalysisSession` dataclass

Add `market_type` field:
```python
@dataclass
class AnalysisSession:
    # ... existing fields
    market_type: str = 'CRYPTO'
    # stream_manager changes to generic AbstractStreamManager type
    stream_manager: Optional[AbstractStreamManager] = None
```

### `LiveScanner.start_session()`

```python
def start_session(self, symbol, strategy_names, selected_timeframes=None, market_type='CRYPTO'):
    provider = get_provider(market_type)
    
    # Resolve symbol for provider
    native_symbol = provider.resolve_symbol(symbol)
    
    # Create stream via provider (not hardcoded BinanceStreamManager)
    stream = provider.create_stream(
        symbol=native_symbol,
        timeframes=timeframes,
        on_candle_close=lambda sym, tf, data: self._on_candle_close(...),
        on_price_update=lambda sym, price, ts: self._on_price_update(...),
        on_live_candle=...,
        on_reconnect=...,
    )
    
    session = AnalysisSession(
        ...,
        market_type=market_type,
        stream_manager=stream,
    )
```

### Market hours awareness

`_on_candle_close()` checks market hours for Indian market:
```python
def _on_candle_close(self, session_id, symbol, timeframe, candle_data):
    session = self._sessions.get(session_id)
    provider = get_provider(session.market_type)
    
    if not provider.is_market_open():
        return  # Skip processing, market closed
    # ... rest of processing
```

Indian market sessions stay alive across trading days but skip processing when market is closed. The scheduler can auto-start sessions at 9:15 IST and auto-stop at 15:30 IST if configured.

## 4. API Blueprint Changes

### `signals_bp.py`

All list/filter endpoints gain `market_type` query parameter:

```python
@signals_bp.route('/sessions', methods=['GET'])
def get_sessions():
    market_type = request.args.get('market_type', 'CRYPTO')
    # Filter by market_type
    ...

@signals_bp.route('/sessions', methods=['POST'])
def create_session():
    body = request.get_json()
    market_type = body.get('market_type', 'CRYPTO')
    live_scanner.start_session(..., market_type=market_type)
    ...

@signals_bp.route('/watching', methods=['GET'])
def get_watching():
    market_type = request.args.get('market_type', 'CRYPTO')
    setups = WatchingSetup.query.filter_by(market_type=market_type).all()
    ...
```

SSE stream publishes `market_type` in all event data — frontend filters by active market type.

### New blueprint: `market_bp`

File: `backend/app/blueprints/market_bp.py`

```python
market_bp = Blueprint('market', __name__)

@market_bp.route('/status', methods=['GET'])
def market_status():
    """Return open/closed status for all market types."""
    return jsonify({
        'crypto': {'is_open': True, 'session': '24/7'},
        'indian': {
            'is_open': get_provider('INDIAN').is_market_open(),
            'hours': get_provider('INDIAN').get_market_hours(),
        }
    })

@market_bp.route('/instruments', methods=['GET'])
def search_instruments():
    """Search Indian instruments by name/symbol."""
    market_type = request.args.get('market_type', 'INDIAN')
    query = request.args.get('q', '')
    provider = get_provider(market_type.upper())
    results = provider.search_instruments(query)
    return jsonify({'instruments': results})

@market_bp.route('/option-chain', methods=['GET'])
def option_chain():
    """Get option chain for a given symbol and expiry."""
    symbol = request.args.get('symbol')
    expiry = request.args.get('expiry')
    chain = get_provider('INDIAN').get_option_chain(symbol, expiry)
    return jsonify({'chain': chain})
```

Registered in `app/__init__.py` with prefix `/api/market`.

## 5. Data Utilities

### `data_utils.py`

`get_finalized_candles()` gains `market_type` parameter:
```python
def get_finalized_candles(symbol, timeframe, limit=500, market_type='CRYPTO'):
    candles = Candle.query.filter_by(
        symbol=symbol, timeframe=timeframe, market_type=market_type
    ).order_by(Candle.open_time.desc()).limit(limit).all()
    ...
```

### `config.py`

Add Indian market configuration:
```python
# Indian Market
SUPPORTED_INDIAN_EQUITY_SYMBOLS = [
    'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
    'ITC', 'SBIN', 'BHARTIARTL', 'KOTAKBANK', 'LT',
    'AXISBANK', 'WIPRO', 'HCLTECH', 'SUNPHARMA', 'TITAN',
    'MARUTI', 'TATAMOTORS', 'BAJFINANCE', 'ASIANPAINT', 'NESTLEIND',
]

SUPPORTED_INDIAN_INDEX_SYMBOLS = ['NIFTY', 'BANKNIFTY', 'SENSEX', 'FINNIFTY']

INDIAN_ROUND_NUMBER_CONFIG = {
    'NIFTY': {'small': 50, 'large': 100},
    'BANKNIFTY': {'small': 100, 'large': 500},
    'SENSEX': {'small': 100, 'large': 500},
    'RELIANCE': {'small': 10, 'large': 50},
    'TCS': {'small': 20, 'large': 100},
    # ... more stocks
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
```

## 6. `app/__init__.py` Changes

```python
# After existing initializations:
# Initialize Angel One provider (background)
if not app.config.get('TESTING', False):
    try:
        from app.providers import get_provider
        indian_provider = get_provider('INDIAN')
        if indian_provider:
            indian_provider.connect()
            indian_provider.sync_instruments()
    except Exception as e:
        print(f"[create_app] Angel One provider init failed: {e}")

# Register new blueprint
from app.blueprints.market_bp import market_bp
app.register_blueprint(market_bp, url_prefix='/api/market')
```

## 7. Strategy Runner Changes

File: `backend/app/core/strategy_runner.py`

The `run_single_scan()` method gains `market_type` parameter, passed to `get_finalized_candles()`:
```python
def run_single_scan(strategy, symbol, timeframe, market_type='CRYPTO', min_confidence_override=None):
    df = get_finalized_candles(symbol, timeframe, limit=lookback, market_type=market_type)
    ...
```
