"""Binance Futures Provider — wraps existing Binance REST + WebSocket logic."""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import List, Optional, Callable

import requests
import websocket

from app.providers.base import AbstractMarketProvider, AbstractStreamManager

logger = logging.getLogger(__name__)


class BinanceStreamManager(AbstractStreamManager):
    """
    Manages Binance WebSocket kline streams for live candle data.
    Architecture:
    - One combined stream URL for all symbol/timeframe pairs in a session
    - Uses websocket-client in a background daemon thread
    - Detects candle close events (kline.x == True) and fires on_candle_close callback
    - Tracks live price from unclosed candles and fires on_price_update callback
    - Supports auto-reconnect with exponential backoff
    - Thread-safe start/stop
    """

    BINANCE_WS_BASE = "wss://fstream.binance.com/market/stream"

    def __init__(
        self,
        symbol: str,
        timeframes: List[str],
        on_candle_close: Optional[Callable] = None,
        on_price_update: Optional[Callable] = None,
        on_live_candle: Optional[Callable] = None,
        on_reconnect: Optional[Callable] = None,
        max_retries: int = 20,
    ):
        self.symbol = symbol.upper()
        self.timeframes = timeframes
        self.on_candle_close = on_candle_close
        self.on_price_update = on_price_update
        self.on_live_candle = on_live_candle
        self.on_reconnect = on_reconnect
        self.max_retries = max_retries

        self._ws: Optional[websocket.WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._retry_count = 0
        self._lock = threading.Lock()

    def _build_stream_url(self) -> str:
        streams = []
        sym_lower = self.symbol.lower()
        for tf in self.timeframes:
            streams.append(f"{sym_lower}@kline_{tf}")
        return f"{self.BINANCE_WS_BASE}?streams={'/'.join(streams)}"

    def _on_message(self, ws, message: str):
        try:
            msg = json.loads(message)
            data = msg.get("data", {})
            event_type = data.get("e")
            if event_type != "kline":
                return

            kline = data.get("k", {})
            symbol = data.get("s", "").upper()
            timeframe = kline.get("i", "")
            is_closed = kline.get("x", False)
            close_price = float(kline.get("c", 0))

            if self.on_price_update and close_price > 0:
                tick_time = datetime.fromtimestamp(data.get("E", 0) / 1000.0, tz=timezone.utc)
                try:
                    self.on_price_update(symbol, close_price, tick_time)
                except Exception as e:
                    logger.error(f"[BinanceWS] Error in on_price_update: {e}")

            if self.on_live_candle:
                live_candle = {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "open_time": kline.get("t", 0),
                    "close_time": kline.get("T", 0),
                    "open": float(kline.get("o", 0)),
                    "high": float(kline.get("h", 0)),
                    "low": float(kline.get("l", 0)),
                    "close": float(kline.get("c", 0)),
                    "volume": float(kline.get("v", 0)),
                    "is_closed": is_closed,
                }
                try:
                    self.on_live_candle(symbol, timeframe, live_candle)
                except Exception as e:
                    logger.error(f"[BinanceWS] Error in on_live_candle: {e}")

            if is_closed and self.on_candle_close:
                candle_data = {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "open_time": datetime.fromtimestamp(kline.get("t", 0) / 1000.0, tz=timezone.utc),
                    "open": float(kline.get("o", 0)),
                    "high": float(kline.get("h", 0)),
                    "low": float(kline.get("l", 0)),
                    "close": float(kline.get("c", 0)),
                    "volume": float(kline.get("v", 0)),
                }
                try:
                    self.on_candle_close(symbol, timeframe, candle_data)
                except Exception as e:
                    logger.error(f"[BinanceWS] Error in on_candle_close: {e}")

        except json.JSONDecodeError:
            logger.warning(f"[BinanceWS] Failed to parse message: {message[:100]}")
        except Exception as e:
            logger.error(f"[BinanceWS] Unexpected error in message handler: {e}")

    def _on_error(self, ws, error):
        logger.error(f"[BinanceWS] Error for {self.symbol}: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        logger.info(f"[BinanceWS] Connection closed for {self.symbol} "
                    f"(status={close_status_code}, msg={close_msg})")
        if self._running and self._retry_count < self.max_retries:
            self._retry_count += 1
            delay = min(2 ** (self._retry_count - 1), 60)
            logger.warning(f"[BinanceWS] Reconnecting in {delay}s "
                          f"(attempt {self._retry_count}/{self.max_retries})...")
            time.sleep(delay)
            if self._running:
                self._connect()
        elif self._retry_count >= self.max_retries:
            logger.error(f"[BinanceWS] Max retries ({self.max_retries}) exceeded for {self.symbol}.")
            self._running = False

    def _on_open(self, ws):
        is_reconnect = self._retry_count > 0
        self._retry_count = 0
        logger.info(f"[BinanceWS] {'Re-c' if is_reconnect else 'C'}onnected for {self.symbol} — "
                    f"streaming {', '.join(self.timeframes)}")
        if is_reconnect and self.on_reconnect:
            try:
                self.on_reconnect(self.symbol)
            except Exception as e:
                logger.error(f"[BinanceWS] Error in on_reconnect callback: {e}")

    def _connect(self):
        url = self._build_stream_url()
        self._ws = websocket.WebSocketApp(
            url,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )
        self._ws.run_forever(ping_interval=30, ping_timeout=10)

    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            self._retry_count = 0
            self._thread = threading.Thread(
                target=self._connect,
                name=f"binance-ws-{self.symbol.lower()}",
                daemon=True,
            )
            self._thread.start()
            logger.info(f"[BinanceWS] Started stream thread for {self.symbol}")

    def stop(self):
        with self._lock:
            if not self._running:
                return
            self._running = False
            if self._ws:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._ws = None
            logger.info(f"[BinanceWS] Stopped stream for {self.symbol}")

    @property
    def is_running(self) -> bool:
        return self._running


class BinanceProvider(AbstractMarketProvider):
    """Binance Futures USDT-Margined data provider for crypto markets."""

    market_type = 'CRYPTO'
    BINANCE_FAPI_BASE = "https://fapi.binance.com/fapi/v1/klines"

    supported_timeframes = [
        '1m', '3m', '5m', '15m', '30m',
        '1h', '2h', '4h', '6h', '8h', '12h',
        '1d', '3d', '1w',
    ]

    def fetch_candles(
        self, symbol: str, timeframe: str,
        start_time_ms: int, end_time_ms: int,
    ) -> List[dict]:
        all_candles = []
        current_start = start_time_ms
        limit = 1000

        while current_start < end_time_ms:
            params = {
                "symbol": symbol,
                "interval": timeframe,
                "startTime": current_start,
                "endTime": end_time_ms,
                "limit": limit,
            }
            response = requests.get(self.BINANCE_FAPI_BASE, params=params)
            if response.status_code != 200:
                raise Exception(f"Binance API Error: {response.text}")

            data = response.json()
            if not data:
                break

            for row in data:
                all_candles.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "open_time": datetime.fromtimestamp(row[0] / 1000.0, tz=timezone.utc),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                })

            last_time = data[-1][0]
            if current_start == last_time + 1:
                break
            current_start = last_time + 1
            time.sleep(0.1)

        return all_candles

    def create_stream(
        self,
        symbol: str,
        timeframes: List[str],
        on_candle_close: Callable,
        on_price_update: Callable,
        on_live_candle: Optional[Callable] = None,
        on_reconnect: Optional[Callable] = None,
    ) -> BinanceStreamManager:
        return BinanceStreamManager(
            symbol=symbol,
            timeframes=timeframes,
            on_candle_close=on_candle_close,
            on_price_update=on_price_update,
            on_live_candle=on_live_candle,
            on_reconnect=on_reconnect,
        )

    def get_market_hours(self) -> dict:
        return {
            'open_utc': None,
            'close_utc': None,
            'pre_open_utc': None,
            'timezone': 'UTC',
            'is_24_7': True,
        }

    def is_market_open(self) -> bool:
        return True

    def resolve_symbol(self, search_key: str) -> str:
        return search_key.upper()

    def get_lot_size(self, symbol: str) -> int:
        return 1
