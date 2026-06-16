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
        provider=None,
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
        self._provider = provider
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

            raw_ltp = float(tick_data.get('last_traded_price', 0) or 0)
            ltp = raw_ltp / 100.0
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
        """Connect and subscribe to Angel One WebSocket 2.0."""
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2
        
        while self._running:
            try:
                if not self._provider:
                    return

                self._provider._ensure_valid_session()

                ws_client = SmartWebSocketV2(
                    self._provider._auth_token,
                    self._provider.api_key,
                    self._provider.client_code,
                    self._provider._feed_token,
                    max_retry_attempt=3
                )

                def on_data(ws, message):
                    self._on_tick(message)
                    
                def on_open(ws):
                    self._on_connect()
                    from app.models.db import IndianInstrument
                    nse_tokens = []
                    nfo_tokens = []
                    # Segregate tokens into exchange types (1=NSE, 2=NFO)
                    for t in self.tokens:
                        # In a real context we would want a DB session, but we can do a quick check
                        # assuming token length or pattern, or ideally the DB has it
                        # But since this runs in a thread, DB queries here might need an app context
                        # To be safe, we'll try to find if it's NFO or NSE based on the mapped symbol
                        # If symbol ends with FUT or CE/PE, it's NFO. Otherwise NSE.
                        sym = self._get_symbol(t)
                        if "FUT" in sym or "CE" in sym or "PE" in sym:
                            nfo_tokens.append(t)
                        else:
                            nse_tokens.append(t)
                            
                    token_list = []
                    if nse_tokens:
                        token_list.append({"exchangeType": 1, "tokens": nse_tokens})
                    if nfo_tokens:
                        token_list.append({"exchangeType": 2, "tokens": nfo_tokens})
                        
                    payload = {
                        "correlationID": "tbot_ws",
                        "action": 1,
                        "params": {
                            "mode": 1,
                            "tokenList": token_list
                        }
                    }
                    ws.send_request(self._provider._auth_token, payload)
                    
                def on_error(*args):
                    error = args[-1] if args else "Unknown error"
                    self._on_error(error)
                    
                def on_close(*args):
                    self._on_close()

                ws_client.on_data = on_data
                ws_client.on_open = on_open
                ws_client.on_error = on_error
                ws_client.on_close = on_close

                self._ws = ws_client

                ws_client.connect()

            except ImportError:
                logger.error("[AngelOneWS] smartapi not installed. Install: pip install smartapi-python")
                break
            except Exception as e:
                logger.error(f"[AngelOneWS] Connection error: {e}")
            
            # If we reach here, connect() returned (which means the socket disconnected)
            if not self._running:
                break
                
            if self._retry_count < self.max_retries:
                self._retry_count += 1
                delay = min(2 ** (self._retry_count - 1), 60)
                logger.warning(f"[AngelOneWS] Reconnecting in {delay}s "
                              f"(attempt {self._retry_count}/{self.max_retries})...")
                time.sleep(delay)
            else:
                logger.error("[AngelOneWS] Max retries reached. Stopping stream.")
                self._running = False
                break

    def _on_close(self):
        logger.info("[AngelOneWS] Connection closed by server or internal logic")

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
        self._auth_token = ''
        self._session_expiry = None

        self._token_map: dict[str, str] = {}
        self._reverse_token_map: dict[str, str] = {}

        if self.api_key and self.client_code and self.password:
            try:
                self.connect()
            except Exception as e:
                logger.warning(f"[AngelOne] Initial connect failed: {e}")

    def connect(self):
        import pyotp
        from SmartApi import SmartConnect

        self._smart = SmartConnect(api_key=self.api_key)

        totp = None
        if self.totp_secret:
            totp = pyotp.TOTP(self.totp_secret).now()

        data = self._smart.generateSession(self.client_code, self.password, totp)
        if data.get('status') is False:
            raise Exception(f"Angel One auth failed: {data.get('message', data)}")

        session_data = data.get('data', {})
        self._refresh_token = session_data.get('refreshToken', '')
        self._auth_token = session_data.get('jwtToken', '')
        self._feed_token = self._smart.getfeedToken()
        
        # Token expires in a few hours, we renew after 6 hours
        self._session_expiry = datetime.now() + timedelta(hours=6)

        logger.info("[AngelOne] Authenticated successfully")
        self._sync_instruments()
        
    def _ensure_valid_session(self):
        """Renew the auth token if it's nearing expiry."""
        if not self._smart or not self._session_expiry:
            self.connect()
            return
            
        if datetime.now() >= self._session_expiry:
            logger.info("[AngelOne] Token expired, attempting renewal...")
            try:
                # generateToken uses the refresh token to get a new JWT
                data = self._smart.generateToken(self._refresh_token)
                if data.get('status'):
                    session_data = data.get('data', {})
                    self._auth_token = session_data.get('jwtToken', '')
                    self._refresh_token = session_data.get('refreshToken', '')
                    self._session_expiry = datetime.now() + timedelta(hours=6)
                    logger.info("[AngelOne] Token renewed successfully")
                else:
                    logger.warning("[AngelOne] Token renewal failed, reconnecting completely...")
                    self.connect()
            except Exception as e:
                logger.error(f"[AngelOne] Token renewal error: {e}, reconnecting...")
                self.connect()

    def _sync_instruments(self):
        import requests
        try:
            from app.models.db import db, IndianInstrument
            
            logger.info("[AngelOne] Fetching ScripMaster JSON...")
            url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            response = requests.get(url, timeout=15)
            if response.status_code != 200:
                logger.error(f"[AngelOne] Failed to fetch instruments: {response.status_code}")
                return
                
            data = response.json()
            
            existing_tokens = {row.token for row in db.session.query(IndianInstrument.token).all()}
            new_instruments = []
            
            for instr in data:
                exchange = instr.get('exch_seg', '')
                if exchange not in ['NSE', 'NFO']:
                    continue

                token = str(instr.get('token', ''))
                symbol = instr.get('symbol', '')
                
                if not token or not symbol:
                    continue
                    
                # Populate memory map
                self._token_map[symbol.upper()] = token
                self._reverse_token_map[token] = symbol.upper()
                
                if token not in existing_tokens:
                    name = instr.get('name', symbol)
                    inst_type = instr.get('instrumenttype', '')
                    try:
                        lot_size = int(instr.get('lotsize', 1) or 1)
                    except ValueError:
                        lot_size = 1
                        
                    expiry_str = instr.get('expiry', None)
                    strike_str = instr.get('strike', None)
                    tick_size_str = instr.get('tick_size', '0.05')

                    expiry = None
                    if expiry_str:
                        try:
                            expiry = datetime.strptime(expiry_str, '%d%b%Y').date()
                        except (ValueError, TypeError):
                            pass

                    strike = None
                    if strike_str and strike_str != '-1.000000':
                        try:
                            strike = float(strike_str)
                        except ValueError:
                            pass
                    
                    try:
                        tick_size = float(tick_size_str)
                    except ValueError:
                        tick_size = 0.05
                        
                    new_instruments.append(IndianInstrument(
                        token=token,
                        symbol=symbol,
                        name=name,
                        exchange=exchange,
                        instrument_type=inst_type,
                        lot_size=lot_size,
                        expiry=expiry,
                        strike_price=strike,
                        tick_size=tick_size,
                    ))
                    existing_tokens.add(token) # prevent duplicates in JSON
            
            if new_instruments:
                logger.info(f"[AngelOne] Bulk inserting {len(new_instruments)} new instruments into DB...")
                db.session.bulk_save_objects(new_instruments)
                db.session.commit()
                
            logger.info(f"[AngelOne] Instrument sync complete — {len(self._token_map)} symbols mapped")

        except Exception as e:
            logger.error(f"[AngelOne] Instrument sync error: {e}")

    def resolve_symbol(self, search_key: str) -> str:
        if search_key in self._reverse_token_map:
            return search_key
            
        upper_key = search_key.upper()
        if upper_key in self._token_map:
            return self._token_map[upper_key]
            
        # Angel One equities often have a -EQ suffix (e.g., RELIANCE-EQ)
        eq_key = f"{upper_key}-EQ"
        if eq_key in self._token_map:
            return self._token_map[eq_key]
            
        return upper_key

    def get_symbol_for_token(self, token: str) -> str:
        return self._reverse_token_map.get(str(token), str(token))

    def fetch_candles(
        self, symbol: str, timeframe: str,
        start_time_ms: int, end_time_ms: int,
    ) -> List[dict]:
        self._ensure_valid_session()

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

        # Angel One Historical API requires the "999" prefix for NSE indices (like NIFTY, BANKNIFTY)
        # Equities also have an empty instrument_type, but their symbols end with -EQ, -BE, etc. Indices do not.
        instr_symbol = instr.symbol if instr else symbol
        is_index = False
        if instr and instr.instrument_type in ('', 'AMXIDX') and not instr_symbol.endswith('-EQ') and not instr_symbol.endswith('-BE'):
            is_index = True
        elif symbol.upper() in ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'INDIAVIX']:
            is_index = True
            
        hist_token = token
        if exchange == 'NSE' and is_index and not hist_token.startswith('999'):
            hist_token = f"999{token}"

        historic_params = {
            "exchange": exchange,
            "symboltoken": hist_token,
            "interval": interval,
            "fromdate": start_ist.strftime('%Y-%m-%d %H:%M'),
            "todate": end_ist.strftime('%Y-%m-%d %H:%M'),
        }

        all_candles = []
        max_retries = 10
        
        for attempt in range(max_retries):
            try:
                data = self._smart.getCandleData(historic_params)
                
                if data and data.get('errorcode') == 'AB8051':
                    logger.warning(f"[AngelOne] Rate limit exceeded, retrying in {attempt + 2}s...")
                    time.sleep(attempt + 2)
                    continue
                    
                if not data or data.get('status') is False:
                    logger.error(f"[AngelOne] getCandleData error: {data}")
                    break
                    
                if 'data' not in data or not data['data']:
                    break

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
                break # Success
            except Exception as e:
                err_str = str(e)
                if "exceeding access rate" in err_str or "AB8051" in err_str:
                    logger.warning(f"[AngelOne] Rate limit exceeded for {symbol}, retrying in {attempt + 2}s...")
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(attempt + 2)
                    continue
                
                logger.error(f"[AngelOne] fetch_candles exception for {symbol}: {e}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)

        return all_candles

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
            provider=self,
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
