"""Abstract Market Provider — interface all market data sources must implement."""

from abc import ABC, abstractmethod
from typing import List, Optional, Callable, Dict


class AbstractStreamManager(ABC):
    """Base interface for WebSocket stream management."""

    @abstractmethod
    def start(self):
        ...

    @abstractmethod
    def stop(self):
        ...

    @property
    @abstractmethod
    def is_running(self) -> bool:
        ...


class AbstractMarketProvider(ABC):
    """
    Base interface for all market data providers.

    Implementations:
      - BinanceProvider  (market_type='CRYPTO')
      - AngelOneProvider (market_type='INDIAN')
    """

    market_type: str  # 'CRYPTO' | 'INDIAN'

    @abstractmethod
    def fetch_candles(
        self, symbol: str, timeframe: str,
        start_time_ms: int, end_time_ms: int,
    ) -> List[dict]:
        """
        Fetch historical OHLCV candles.
        Returns list of dicts: {symbol, timeframe, open_time(datetime),
                                open, high, low, close, volume}
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
    ) -> AbstractStreamManager:
        """Create a live data stream for the given symbol and timeframes."""
        ...

    @abstractmethod
    def get_market_hours(self) -> dict:
        """
        Returns dict with keys: open_utc, close_utc, pre_open_utc, timezone.
        For 24/7 markets, open_utc and close_utc are None.
        """
        ...

    @abstractmethod
    def is_market_open(self) -> bool:
        """Check if the market is currently open for trading."""
        ...

    @abstractmethod
    def resolve_symbol(self, search_key: str) -> str:
        """
        Resolve a human-readable symbol to provider-native format.
        Crypto: 'BTCUSDT' -> 'BTCUSDT' (passthrough)
        Indian: 'RELIANCE' -> token string
        """
        ...

    @property
    @abstractmethod
    def supported_timeframes(self) -> List[str]:
        """Timeframes available for this market."""
        ...

    @abstractmethod
    def get_lot_size(self, symbol: str) -> int:
        """Lot size (1 for crypto, variable for F&O)."""
        ...
