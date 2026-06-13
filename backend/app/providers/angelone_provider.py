"""Angel One Smart API Provider — Indian market data source (NSE/BSE/NFO)."""

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Callable

from app.providers.base import AbstractMarketProvider, AbstractStreamManager

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# Timeframe durations for candle aggregation
TIMEFRAME_MINUTES = {
    '1m': 1, '5m': 5, '15m': 15, '30m': 30,
    '1h': 60, '1d': 1440,
}


def _get_candle_open_time(ts: datetime, tf_minutes: int) -> datetime:
    """Round timestamp down to the nearest candle open time."""
    minutes_since_midnight = ts.hour * 60 + ts.minute
    
    # Apply 15-minute offset for Indian market intraday timeframes
    # This ensures 30m and 1h candles align with the 09:15 start time
    if tf_minutes < 1440:
        offset = 15
        bucket = ((minutes_since_midnight - offset) // tf_minutes) * tf_minutes + offset
    else:
        bucket = (minutes_since_midnight // tf_minutes) * tf_minutes
        
    return ts.replace(hour=bucket // 60, minute=bucket % 60, second=0, microsecond=0)


class AngelOneStreamManager(AbstractStreamManager):
    """
    WebSocket stream manager for Angel One Smart API.
    Token-based subscription — symbols resolved via instrument master.
    Aggregates tick-level data into OHLCV candles per timeframe.
    """

    def __init__(
        self,
        tokens: List[str],
        timeframes: List[str],
        token_map: dict,
        on_candle_close: Callable,
        on_price_update: Callable,
        on_live_candle: Optional[Callable] = None,
        on_reconnect: Optional[Callable] = None,
        smart_api=None,
        max_retries: int = 20,
    ):
        self.tokens = tokens
        self.timeframes = timeframes
        self._token_map = token_map  # token -> human-readable symbol
        self._reverse_token_map = {v: k for k, v in token_map.items()}
        self.on_candle_close = on_candle_close
        self.on_price_update = on_price_update
        self.on_live_candle = on_live_candle
        self.on_reconnect = on_reconnect
        self._smart_api = smart_api
        self.max_retries = max_retries

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._retry_count = 0
        self._lock = threading.Lock()

        # Candle aggregation state: (token, timeframe) -> current candle dict
        self._candles: dict[tuple, dict] = {}
        self._candles_lock = threading.Lock()

    def _get_symbol(self, token: str) -> str:
        return self._token_map.get(str(token), str(token))

    def _on_tick(self, tick_data: dict):
        """Aggregate tick into candles and detect candle closes."""
        try:
            token = str(tick_data.get('token', ''))
            symbol = self._get_symbol(token)
            if not symbol:
                return

            ltp = float(tick_data.get('last_traded_price', 0) or 0)
            if ltp <= 0:
                return

            now_utc = datetime.now(timezone.utc)
            now_ist = now_utc.astimezone(IST)

            # Fire price update for every tick
            if self.on_price_update:
                try:
                    self.on_price_update(symbol, ltp, now_utc)
                except Exception as e:
                    logger.error(f"[AngelOneWS] on_price_update error: {e}")

            # Aggregate into candles per timeframe
            for tf in self.timeframes:
                tf_minutes = TIMEFRAME_MINUTES.get(tf)
                if tf_minutes is None:
                    continue

                candle_key = (token, tf)
                candle_open = _get_candle_open_time(now_ist, tf_minutes)

                with self._candles_lock:
                    current = self._candles.get(candle_key)

                    if current is None:
                        # First tick: initialize candle
                        self._candles[candle_key] = {
                            'symbol': symbol,
                            'timeframe': tf,
                            'open_time': candle_open,
                            'open': ltp,
                            'high': ltp,
                            'low': ltp,
                            'close': ltp,
                            'volume': 0,
                        }
                        continue

                    # Check if this tick belongs to a new candle
                    if candle_open > current['open_time']:
                        # Close the old candle
                        closed_candle = dict(current)
                        closed_candle['open_time'] = current['open_time'].replace(tzinfo=timezone.utc)
                        
                        # Fire on_candle_close
                        if self.on_candle_close:
                            try:
                                self.on_candle_close(symbol, tf, closed_candle)
                            except Exception as e:
                                logger.error(f"[AngelOneWS] on_candle_close error: {e}")

                        # Start new candle
                        current.clear()
                        current.update({
                            'symbol': symbol,
                            'timeframe': tf,
                            'open_time': candle_open,
                            'open': ltp,
                            'high': ltp,
                            'low': ltp,
                            'close': ltp,
                            'volume': 0,
                        })
                    else:
                        # Update existing candle
                        current['high'] = max(current['high'], ltp)
                        current['low'] = min(current['low'], ltp)
                        current['close'] = ltp

                    # Fire on_live_candle for current state
                    if self.on_live_candle:
                        try:
                            live_candle = {
                                "symbol": symbol,
                                "timeframe": tf,
                                "open_time": int(current['open_time'].timestamp() * 1000),
                                "close_time": int((current['open_time'] + timedelta(minutes=tf_minutes)).timestamp() * 1000),
                                "open": current['open'],
                                "high": current['high'],
                                "low": current['low'],
                                "close": current['close'],
                                "volume": current['volume'],
                                "is_closed": False,
                            }
                            self.on_live_candle(symbol, tf, live_candle)
                        except Exception as e:
                            logger.error(f"[AngelOneWS] on_live_candle error: {e}")

        except Exception as e:
            logger.error(f"[AngelOneWS] Error processing tick: {e}")

    def _on_connect(self):
        is_reconnect = self._retry_count > 0
        self._retry_count = 0
        logger.info(f"[AngelOneWS] {'Re-c' if is_reconnect else 'C'}onnected — "
                    f"aggregating candles for {len(self.tokens)} tokens × {len(self.timeframes)} tfs")
        if is_reconnect and self.on_reconnect:
            try:
                # Find first token's symbol for reconnect callback
                sym = self._get_symbol(self.tokens[0]) if self.tokens else "unknown"
                self.on_reconnect(sym)
            except Exception as e:
                logger.error(f"[AngelOneWS] Error in on_reconnect: {e}")

    def _run_websocket(self):
        """Connect and subscribe to Angel One WebSocket."""
        try:
            from smartapi import WebSocket as AngelWebSocket

            ws_client = AngelWebSocket(
                feed_token=self._smart_api._feed_token,
                client_code=self._smart_api._client_code,
            )
            ws_client.on_tick = self._on_tick
            ws_client.on_connect = self._on_connect
            ws_client.on_close = self._on_close
            ws_client.on_error = self._on_error

            self._ws = ws_client

            ws_client.connect()
            ws_client.subscribe(self.tokens, "mw")

            while self._running:
                time.sleep(1)

        except ImportError:
            logger.error("[AngelOneWS] smartapi not installed. Install: pip install smartapi-python")
        except Exception as e:
            logger.error(f"[AngelOneWS] Connection error: {e}")
            if self._running and self._retry_count < self.max_retries:
                self._retry_count += 1
                delay = min(2 ** (self._retry_count - 1), 60)
                logger.warning(f"[AngelOneWS] Reconnecting in {delay}s "
                              f"(attempt {self._retry_count}/{self.max_retries})...")
                time.sleep(delay)
                if self._running:
                    self._run_websocket()

    def _on_close(self):
        logger.info("[AngelOneWS] Connection closed")
        if self._running and self._retry_count < self.max_retries:
            self._retry_count += 1
            delay = min(2 ** (self._retry_count - 1), 60)
            logger.warning(f"[AngelOneWS] Reconnecting in {delay}s "
                          f"(attempt {self._retry_count}/{self.max_retries})...")
            time.sleep(delay)
            if self._running:
                self._run_websocket()

    def _on_error(self, error):
        logger.error(f"[AngelOneWS] Error: {error}")

    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            self._retry_count = 0
            self._thread = threading.Thread(
                target=self._run_websocket,
                name="angelone-ws",
                daemon=True,
            )
            self._thread.start()
            logger.info("[AngelOneWS] Started stream thread")

    def stop(self):
        with self._lock:
            if not self._running:
                return
            self._running = False
            if hasattr(self, '_ws') and self._ws:
                try:
                    self._ws.close_connection()
                except Exception:
                    pass
            logger.info("[AngelOneWS] Stopped stream")

    @property
    def is_running(self) -> bool:
        return self._running


class AngelOneProvider(AbstractMarketProvider):
    """Angel One Smart API data provider."""

    market_type = 'INDIAN'

    supported_timeframes = ['1m', '5m', '15m', '30m', '1h', '1d']

    def __init__(self):
        self.api_key = os.environ.get('ANGELONE_API_KEY', '')
        self.client_code = os.environ.get('ANGELONE_CLIENT_CODE', '')
        self.password = os.environ.get('ANGELONE_PASSWORD', '')
        self.totp_secret = os.environ.get('ANGELONE_TOTP_SECRET', '')

        self._smart = None
        self._feed_token = ''
        self._refresh_token = ''

        self._token_map: dict[str, str] = {}
        self._reverse_token_map: dict[str, str] = {}

        if self.api_key and self.client_code and self.password:
            try:
                self.connect()
            except Exception as e:
                logger.warning(f"[AngelOne] Initial connect failed: {e}")

    def connect(self):
        import pyotp
        from smartapi import SmartConnect

        self._smart = SmartConnect(api_key=self.api_key)

        totp = None
        if self.totp_secret:
            totp = pyotp.TOTP(self.totp_secret).now()

        data = self._smart.generateSession(self.client_code, self.password, totp)
        if data.get('status') is False:
            raise Exception(f"Angel One auth failed: {data.get('message', data)}")

        session_data = data.get('data', {})
        self._refresh_token = session_data.get('refreshToken', '')
        self._feed_token = self._smart.getfeedToken()

        logger.info("[AngelOne] Authenticated successfully")
        self._sync_instruments()

    def _sync_instruments(self):
        try:
            from app.models.db import db, IndianInstrument

            for exchange in ['NSE', 'NFO']:
                try:
                    instruments = self._smart.getSymbolList(exchange)
                    if instruments and 'data' in instruments:
                        for instr in instruments['data']:
                            token = str(instr.get('token', ''))
                            symbol = instr.get('symbol', '')
                            name = instr.get('name', symbol)
                            inst_type = instr.get('instrumenttype', '')
                            lot_size = int(instr.get('lotsize', 1))
                            expiry_str = instr.get('expiry', None)
                            strike = instr.get('strike', None)
                            tick_size = float(instr.get('tick_size', 0.05))

                            expiry = None
                            if expiry_str:
                                try:
                                    expiry = datetime.strptime(expiry_str, '%d%b%Y').date()
                                except (ValueError, TypeError):
                                    pass

                            existing = IndianInstrument.query.get(token)
                            if existing:
                                existing.symbol = symbol
                                existing.name = name
                                existing.last_updated = datetime.now(timezone.utc)
                            else:
                                db.session.add(IndianInstrument(
                                    token=token,
                                    symbol=symbol,
                                    name=name,
                                    exchange=exchange,
                                    instrument_type=inst_type,
                                    lot_size=lot_size,
                                    expiry=expiry,
                                    strike_price=float(strike) if strike else None,
                                    tick_size=tick_size,
                                ))

                            self._token_map[symbol.upper()] = token
                            self._reverse_token_map[token] = symbol.upper()

                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logger.warning(f"[AngelOne] Instrument sync failed for {exchange}: {e}")

            logger.info(f"[AngelOne] Instrument sync complete — "
                        f"{len(self._token_map)} symbols mapped")

        except Exception as e:
            logger.error(f"[AngelOne] Instrument sync error: {e}")

    def resolve_symbol(self, search_key: str) -> str:
        if search_key in self._reverse_token_map:
            return search_key
        return self._token_map.get(search_key.upper(), search_key.upper())

    def get_symbol_for_token(self, token: str) -> str:
        return self._reverse_token_map.get(str(token), str(token))

    def fetch_candles(
        self, symbol: str, timeframe: str,
        start_time_ms: int, end_time_ms: int,
    ) -> List[dict]:
        if self._smart is None:
            self.connect()

        token = self.resolve_symbol(symbol)
        if token is None:
            raise ValueError(f"Symbol not found in instrument master: {symbol}")

        interval_map = {
            '1m': 'ONE_MINUTE', '5m': 'FIVE_MINUTE',
            '15m': 'FIFTEEN_MINUTE', '30m': 'THIRTY_MINUTE',
            '1h': 'ONE_HOUR', '1d': 'ONE_DAY',
        }
        interval = interval_map.get(timeframe, 'FIFTEEN_MINUTE')

        start_ist = datetime.fromtimestamp(start_time_ms / 1000, IST)
        end_ist = datetime.fromtimestamp(end_time_ms / 1000, IST)

        # Determine exchange from instrument type — F&O uses NFO, equities use NSE
        from app.models.db import IndianInstrument
        instr = IndianInstrument.query.get(token)
        exchange = 'NFO' if (instr and instr.instrument_type in ('FUTIDX', 'OPTIDX', 'FUTSTK', 'OPTSTK')) else 'NSE'

        try:
            historic_params = {
                "exchange": exchange,
                "symboltoken": token,
                "interval": interval,
                "fromdate": start_ist.strftime('%Y-%m-%d %H:%M'),
                "todate": end_ist.strftime('%Y-%m-%d %H:%M'),
            }
            data = self._smart.getCandleData(historic_params)

            if not data or 'data' not in data or not data['data']:
                return []

            all_candles = []
            for row in data['data']:
                ts = row[0]
                if isinstance(ts, str):
                    try:
                        open_time = datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S%z')
                    except ValueError:
                        open_time = datetime.fromtimestamp(int(ts) / 1000, IST)
                else:
                    open_time = datetime.fromtimestamp(ts / 1000, IST)

                all_candles.append({
                    "symbol": symbol.upper(),
                    "timeframe": timeframe,
                    "open_time": open_time,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]) if len(row) > 5 else 0,
                    "market_type": "INDIAN",
                })

            return all_candles

        except Exception as e:
            logger.error(f"[AngelOne] fetch_candles error for {symbol} {timeframe}: {e}")
            raise

    def create_stream(
        self,
        symbol: str,
        timeframes: List[str],
        on_candle_close: Callable,
        on_price_update: Callable,
        on_live_candle: Optional[Callable] = None,
        on_reconnect: Optional[Callable] = None,
    ) -> AngelOneStreamManager:
        token = self.resolve_symbol(symbol)
        if token is None:
            raise ValueError(f"Symbol not found: {symbol}")

        return AngelOneStreamManager(
            tokens=[token],
            timeframes=timeframes,
            token_map=self._token_map,
            on_candle_close=on_candle_close,
            on_price_update=on_price_update,
            on_live_candle=on_live_candle,
            on_reconnect=on_reconnect,
            smart_api=self._smart,
        )

    def get_market_hours(self) -> dict:
        return {
            'open_utc': '03:45',
            'close_utc': '10:00',
            'pre_open_utc': '03:30',
            'timezone': 'Asia/Kolkata',
            'is_24_7': False,
            'trading_start_ist': '09:15',
            'trading_end_ist': '15:30',
        }

    def is_market_open(self) -> bool:
        now_ist = datetime.now(IST)
        if now_ist.weekday() >= 5:
            return False
        time_str = now_ist.strftime('%H:%M')
        return '09:15' <= time_str <= '15:30'

    def get_lot_size(self, symbol: str) -> int:
        token = self.resolve_symbol(symbol)
        try:
            from app.models.db import IndianInstrument
            instr = IndianInstrument.query.get(token)
            if instr:
                return instr.lot_size
        except Exception:
            pass
        return 1

    def search_instruments(self, query: str, exchange: str = 'NSE') -> List[dict]:
        try:
            from app.models.db import IndianInstrument
            q = query.upper()
            results = IndianInstrument.query.filter(
                IndianInstrument.exchange == exchange,
                IndianInstrument.symbol.ilike(f'%{q}%')
            ).limit(20).all()
            return [r.to_dict() for r in results]
        except Exception:
            return []

    def get_option_chain(self, symbol: str, expiry: str) -> List[dict]:
        try:
            from app.models.db import IndianInstrument
            expiry_date = datetime.strptime(expiry, '%Y-%m-%d').date()
            results = IndianInstrument.query.filter(
                IndianInstrument.symbol.ilike(f'%{symbol.upper()}%'),
                IndianInstrument.instrument_type.in_(['OPTIDX', 'OPTSTK']),
                IndianInstrument.expiry == expiry_date,
            ).order_by(IndianInstrument.strike_price).all()
            return [r.to_dict() for r in results]
        except Exception:
            return []

    def get_option_data(self, symbol: str, expiry: str, strike: float, right: str) -> Optional[dict]:
        """Get a specific option instrument from the master."""
        try:
            from app.models.db import IndianInstrument
            instr = IndianInstrument.query.filter(
                IndianInstrument.symbol.ilike(f'%{symbol.upper()}%'),
                IndianInstrument.instrument_type.in_(['OPTIDX', 'OPTSTK']),
                IndianInstrument.expiry == datetime.strptime(expiry, '%Y-%m-%d').date(),
                IndianInstrument.strike_price == strike,
            ).first()
            return instr.to_dict() if instr else None
        except Exception:
            return None
