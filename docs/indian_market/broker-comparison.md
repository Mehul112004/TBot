# Broker Comparison & Recommendation

## Requirements

- Free access to **live market data** via WebSockets
- Free access to **historical and intraday data** via REST APIs
- Support for **intraday stocks** and **options trading** (Nifty, Sensex, BankNifty)
- Python-friendly SDK or straightforward HTTP/WS API
- Suitable for automated/algorithmic trading

## Comparison Matrix

| Feature | Angel One Smart API | ICICIdirect Breeze | Upstox |
|---|---|---|---|
| **Cost** | Free for account holders | Free for existing holders | Free for account holders |
| **Live WebSocket** | Yes (token-based) | Yes (Candle Stream) | Yes |
| **Historical Data** | Yes (REST, multi-timeframe) | Yes (REST, 3yr F&O) | Yes (REST) |
| **Python SDK** | `smartapi-python` (official) | `breeze-connect` | `upstox-python` |
| **Equity Intraday** | Yes | Yes (NSE only) | Yes |
| **F&O / Options** | Yes (full chain) | Yes (NFO only) | Yes |
| **Option Chain** | Yes | Yes | Yes |
| **Market Orders** | Allowed | **Not permitted** | Allowed |
| **Static IP Required** | No | **Yes** | No |
| **Rate Limit** | Generous | 100/min, 5000/day | Good |
| **Regulatory Restrictions** | Standard SEBI | Strict (IP-locked, no market orders, 10 orders/sec cap) | Standard SEBI |
| **Community / Adoption** | Widely used in Indian retail algo trading | Moderate | Growing |
| **Instrument Coverage** | NSE, BSE, NFO, MCX, CDS | NSE, NFO only | NSE, BSE, MCX, NFO, CDS |

## Detailed Analysis

### Angel One Smart API (Recommended)

**Pros:**
- Completely free — no API subscription fees
- Mature Python SDK (`smartapi-python`) with good documentation
- WebSocket live streaming for real-time OHLCV ticks
- REST API for historical candle data (1m, 5m, 15m, 30m, 1h, 1d)
- Full option chain data with Greeks
- Widely tested by Indian retail algo community — high reliability
- No static IP requirement
- Market orders allowed
- Simple session-based authentication (client code + password + TOTP)

**Cons:**
- Token-based WebSocket (requires instrument master sync, unlike Binance's symbol-based streams)
- SDK needs periodic re-login (session expiry)

**Auth Flow:**
```python
from smartapi import SmartConnect
obj = SmartConnect(api_key="your_api_key")
data = obj.generateSession(client_code, password, totp)
refresh_token = data['data']['refreshToken']
feed_token = obj.getfeedToken()
# Use feed_token for WebSocket connection
```

**Historical Data:**
```python
historic = obj.getCandleData({
    "exchange": "NSE",
    "symboltoken": "3045",  # from instrument master
    "interval": "FIFTEEN_MINUTE",
    "fromdate": "2024-01-01 09:15",
    "todate": "2024-01-30 15:30"
})
```

### ICICIdirect Breeze

**Pros:**
- 3 years of historical F&O data
- Clean REST API with good documentation
- Option chain data available
- Live streaming OHLCV

**Cons:**
- **Static IP mandatory** — makes cloud deployment painful
- **Market orders not permitted** — limit orders only
- Rate limit is restrictive: 100 calls/min, 5,000 calls/day
- NSE/NFO only — no BSE, no MCX
- Complex auth: OAuth2 + SHA256 checksum per request
- Single API key restriction for unregistered algos
- 10 orders/sec combined limit (place + modify + cancel)

**Auth Complexity:**
```python
# Every request requires:
checksum = sha256(timestamp + json_body + secret_key).hexdigest()
headers = {
    'X-Checksum': f'token {checksum}',
    'X-Timestamp': timestamp,  # ISO 8601 UTC with .000Z
    'X-AppKey': app_key,
    'X-SessionToken': session_token,
}
```

### Upstox

**Pros:**
- Modern developer platform
- Good documentation
- WebSocket + REST
- OAuth 2.0 authentication

**Cons:**
- Relatively newer API ecosystem
- Regulatory changes may impact usability (recent SEBI circulars)
- Python SDK less battle-tested than Angel One

## Recommendation: Angel One Smart API

**Primary reasons:**

1. **Least restrictive** — no static IP, market orders allowed, generous rate limits
2. **Proven in production** — widely used by Indian retail algo traders
3. **Cleanest integration** — Python SDK handles auth, token refresh, WebSocket lifecycle
4. **Full instrument coverage** — NSE equities, NFO futures/options, currencies
5. **Zero cost** — completely free for account holders

### Fallback: Upstox
If Angel One has availability issues, Upstox is the second choice due to its modern API design and lack of static IP requirement. Breeze is least preferred due to its operational restrictions.

## Implementation Notes

- Angel One uses **numeric tokens** for instruments (e.g., `3045` for SBIN EQ), not human-readable symbols
- Must sync instrument master daily (8:00 AM IST update)
- Symbol mapping table (`indian_instruments` DB table) needed for token resolution
- WebSocket subscription format differs from Binance — normalization layer required in the provider
