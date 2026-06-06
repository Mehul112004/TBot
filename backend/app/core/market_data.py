"""
Market Data Fetcher — Real-time Funding Rate, Open Interest, Trading Session

Fetches live Binance futures data to enrich LLM context with:
  - Current funding rate (confirms market positioning)
  - Open Interest % change (contextualizes absolute OI levels)
  - Active trading session (Asian/London/NY/Transition)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BINANCE_FUTURES_BASE = "https://fapi.binance.com"
REQUEST_TIMEOUT = 5  # seconds


def get_trading_session(candle_timestamp: Optional[float] = None) -> str:
    """Determine the active trading session based on UTC hour."""
    if candle_timestamp:
        dt = datetime.fromtimestamp(candle_timestamp / 1000, tz=timezone.utc)
    else:
        dt = datetime.now(timezone.utc)

    hour = dt.hour

    # Asian Session (Tokyo/Sydney): ~00:00 to 08:00 UTC
    if 0 <= hour < 8:
        return "Asian"
    # London Session: ~08:00 to 13:00 UTC (pre-NY overlap)
    elif 8 <= hour < 13:
        return "London"
    # New York Session: ~13:00 to 21:00 UTC
    elif 13 <= hour < 21:
        return "New_York"
    # Post-NY / Late Asian overlap
    else:
        return "Transition/Asian"


def fetch_funding_rate(symbol: str) -> Optional[float]:
    """Fetch the current (real-time) funding rate for a Binance futures symbol."""
    try:
        url = f"{BINANCE_FUTURES_BASE}/fapi/v1/premiumIndex"
        resp = requests.get(url, params={"symbol": symbol}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        rate_str = data.get("lastFundingRate")
        if rate_str is not None:
            return round(float(rate_str) * 100, 4)  # Convert to percentage
        return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"[MarketData] Funding rate fetch failed for {symbol}: {e}")
        return None
    except Exception as e:
        logger.warning(f"[MarketData] Unexpected error fetching funding rate: {e}")
        return None


def fetch_oi_change(symbol: str, period: str = "5m") -> Optional[float]:
    """Fetch Open Interest % change between current and previous candle."""
    try:
        url = f"{BINANCE_FUTURES_BASE}/futures/data/openInterestHist"
        resp = requests.get(
            url,
            params={"symbol": symbol, "period": period, "limit": 2},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        if not isinstance(data, list) or len(data) < 2:
            logger.warning(f"[MarketData] Insufficient OI data for {symbol}: {data}")
            return None

        prev_oi = float(data[0].get("sumOpenInterest", 0))
        curr_oi = float(data[1].get("sumOpenInterest", 0))

        if prev_oi <= 0:
            return None

        change_pct = ((curr_oi - prev_oi) / prev_oi) * 100
        return round(change_pct, 2)
    except requests.exceptions.RequestException as e:
        logger.warning(f"[MarketData] OI fetch failed for {symbol}: {e}")
        return None
    except Exception as e:
        logger.warning(f"[MarketData] Unexpected error fetching OI: {e}")
        return None


def fetch_market_data(symbol: str, period: str = "5m") -> dict:
    """Convenience: fetch all market data for a symbol in one call."""
    funding_rate = fetch_funding_rate(symbol)
    oi_change = fetch_oi_change(symbol, period)
    session = get_trading_session()

    return {
        "funding_rate": funding_rate,
        "oi_change": oi_change,
        "session": session,
    }
