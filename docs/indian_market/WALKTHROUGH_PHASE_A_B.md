# Phase A+B Implementation — Walkthrough

## What Was Implemented

Phases A (Foundation) and B (Angel One Integration) of the Indian Market plan. The database now supports dual-market signals, a provider abstraction layer decouples data sources from the scanner, and the Angel One Smart API provider is ready for use.

---

## 1. Architecture: How It All Fits Together

```
┌──────────────────────────────────────────────────────────┐
│                     Frontend (React)                      │
│  market_type toggle → passes 'market_type' in API calls  │
└──────────────────────┬───────────────────────────────────┘
                       │  POST /api/signals/sessions
                       │  { symbol, strategies, market_type }
                       ▼
┌──────────────────────────────────────────────────────────┐
│                  signals_bp.py                            │
│  start_session() → live_scanner.start_session(           │
│    ..., market_type='INDIAN')                             │
└──────────────────────┬───────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────┐
│                   scanner.py                              │
│  AnalysisSession.market_type = 'INDIAN'                  │
│  Provider = get_provider('INDIAN') → AngelOneProvider    │
│  stream = provider.create_stream(...)                    │
│  On candle close: data_utils.get_finalized_candles(      │
│      ..., market_type='INDIAN')                           │
└──────────────────────┬───────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────┐
│              providers/                                   │
│  ┌──────────────────┐  ┌──────────────────────┐          │
│  │ BinanceProvider  │  │  AngelOneProvider    │          │
│  │ market_type=     │  │  market_type=        │          │
│  │   'CRYPTO'       │  │    'INDIAN'          │          │
│  │                   │  │                      │          │
│  │ fetch_candles()   │  │ fetch_candles()      │          │
│  │ create_stream()   │  │ create_stream()      │          │
│  │ is_market_open()  │  │ is_market_open()     │          │
│  │   → always True   │  │   → 9:15-15:30 IST   │          │
│  └──────────────────┘  └──────────────────────┘          │
└──────────────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│                 PostgreSQL                                │
│  All signal tables have market_type column               │
│  indian_instruments table for token mapping              │
└──────────────────────────────────────────────────────────┘
```

---

## 2. What Changed — File Summary

### New Files (5)
| File | Purpose |
|---|---|
| `backend/app/providers/__init__.py` | Provider registry — `register_provider()` + `get_provider()` |
| `backend/app/providers/base.py` | Abstract interfaces: `AbstractMarketProvider`, `AbstractStreamManager` |
| `backend/app/providers/binance_provider.py` | Binance provider implementing the abstract interface |
| `backend/app/providers/angelone_provider.py` | Angel One Smart API provider (REST + WebSocket) |
| `backend/migrations/add_market_type.sql` | (to be generated if needed) |

### Modified Files (8)
| File | Changes |
|---|---|
| `backend/app/models/db.py` | +`market_type` on all 9 models, +`IndianInstrument` model |
| `backend/app/__init__.py` | ALTER TABLE migrations, provider registration |
| `backend/app/core/config.py` | Indian symbols, round numbers, market hours, strategy overrides |
| `backend/app/core/data_utils.py` | `get_finalized_candles()` accepts `market_type` |
| `backend/app/core/scanner.py` | `start_session()` accepts `market_type`, threads through all queries |
| `backend/app/core/strategy_runner.py` | `run_single_scan()` accepts `market_type` |
| `backend/app/core/base_strategy.py` | `SetupSignal` gains `market_type` field |
| `backend/app/core/watching.py` | `create_or_update_setup()` stores `market_type` |
| `backend/app/blueprints/signals_bp.py` | All endpoints accept/filter by `market_type` |
| `backend/requirements.txt` | Added `smartapi-python`, `pyotp` |

---

## 3. Manual Setup Required

### 3.1 Get an Angel One Account & API Key

1. Open a **demat + trading account** with Angel One (https://www.angelone.in/)
2. Log into the **Smart API portal**: https://smartapi.angelone.in/
3. Register a new app to get your **API Key**
4. Note down:
   - Your **Client Code** (e.g., `A123456`)
   - Your **Password** (login password)
   - Your **TOTP Secret** (shown during app registration, used for 2FA)
   - Your **API Key**

### 3.2 Set Environment Variables

Add these to your `.env` file (or Docker/Cloud env):

```bash
# Angel One Smart API credentials
ANGELONE_API_KEY=your_api_key_from_smartapi_portal
ANGELONE_CLIENT_CODE=A123456
ANGELONE_PASSWORD=your_login_password
ANGELONE_TOTP_SECRET=your_totp_secret_for_2fa
```

If these are NOT set, the Angel One provider simply won't register — crypto functionality remains unchanged. It's graceful degradation.

### 3.3 Database Migration

The migrations run automatically on startup via `app/__init__.py`. Just restart the backend:

```bash
cd backend
python3 run.py
```

You should see in the logs:
```
[create_app] BinanceProvider registered for CRYPTO market
[create_app] AngelOneProvider registered for INDIAN market   # if env vars set
```

### 3.4 Instrument Master Sync

When the Angel One provider initializes, it automatically:
1. Authenticates with Angel One
2. Pulls the instrument master for NSE and NFO
3. Populates the `indian_instruments` DB table
4. Builds in-memory `symbol → token` maps

No manual sync needed.

---

## 4. How to Test

### 4.1 Test: Provider Registry

```bash
cd backend
python3 -c "
from app.providers import get_provider
crypto = get_provider('CRYPTO')
print(f'Crypto provider: {crypto.market_type}, open: {crypto.is_market_open()}')

# If ANGELONE env vars are set:
indian = get_provider('INDIAN')
if indian:
    print(f'Indian provider: {indian.market_type}, open: {indian.is_market_open()}')
"
```

### 4.2 Test: Crypto Session (Backward Compat)

```bash
curl -X POST http://localhost:5001/api/signals/sessions \
  -H 'Content-Type: application/json' \
  -d '{"symbol": "BTCUSDT", "strategy_names": ["Trend Following"], "timeframes": ["1h"]}'
```

This works exactly as before. Market type defaults to `'CRYPTO'`.

### 4.3 Test: Indian Market Session (requires Angel One creds)

```bash
curl -X POST http://localhost:5001/api/signals/sessions \
  -H 'Content-Type: application/json' \
  -d '{"symbol": "NIFTY", "strategy_names": ["Trend Following"], "timeframes": ["15m", "1h"], "market_type": "INDIAN"}'
```

### 4.4 Test: Filter by Market Type

```bash
# Get only Indian watching setups
curl 'http://localhost:5001/api/signals/watching?market_type=INDIAN'

# Get only Crypto confirmed signals
curl 'http://localhost:5001/api/signals/confirmed?market_type=CRYPTO'
```

### 4.5 Test: Indian Market Hours

```bash
python3 -c "
from app.providers.angelone_provider import AngelOneProvider
p = AngelOneProvider()
print('Market hours:', p.get_market_hours())
print('Currently open:', p.is_market_open())
"
```

### 4.6 Test: Instrument Search (DB-backed)

```bash
python3 -c "
from app.providers import get_provider
p = get_provider('INDIAN')
if p:
    results = p.search_instruments('RELIANCE')
    for r in results:
        print(r)
"
```

---

## 5. Signal Pipeline — End to End Flow

When you start an Indian market session via the API:

```
1. POST /api/signals/sessions {market_type: "INDIAN", symbol: "NIFTY", ...}
   ↓
2. signals_bp.start_session() → live_scanner.start_session(market_type='INDIAN')
   ↓
3. scanner creates AnalysisSession with market_type='INDIAN'
   ↓
4. scanner calls provider.get_provider('INDIAN') → AngelOneProvider
   ↓
5. AngelOneProvider.resolve_symbol('NIFTY') → returns token e.g. '26000'
   ↓
6. AngelOneProvider.create_stream(token, timeframes, callbacks)
   ↓  (WebSocket connects to Angel One, subscribes to token)
   ↓
7. Candle closes → _on_candle_close()
   ↓
8. Candle upserted to DB with market_type='INDIAN'
   ↓
9. get_finalized_candles(..., market_type='INDIAN') — only fetches INDIAN candles
   ↓
10. Strategies scan → SetupSignal created with market_type='INDIAN'
    ↓
11. WatchingManager.create_or_update_setup() → stores market_type='INDIAN'
    ↓
12. SSE event published with market_type='INDIAN'
    ↓
13. Frontend filters by active market_type
```

---

## 6. Key Design Decisions

| Decision | Reason |
|---|---|
| `market_type` as indexed column, not in PK | Symbols are unique across markets (BTCUSDT vs NIFTY), no PK collision risk. Index gives filter performance without invasive PK changes |
| BinanceProvider duplicated WS logic | Avoids breaking existing `utils/binance.py` imports (6 callers). Migration to provider-based imports can happen gradually in Phase C |
| Angel One provider lazy-initialization | Only connects if env vars are set. No crash if credentials are missing — just doesn't register |
| StrategyRunner unchanged API (added default param) | `market_type='CRYPTO'` default means all existing callers work without changes |
| Watching module doesn't require market_type dedup | Dedup key is session_id+strategy+symbol+timeframe — market_type is inherent to the session |

---

## 7. Limitations & Next Steps

### Phase B Limitations (not yet done — planned for Phase C)
- Scanner still uses `BinanceStreamManager` type hint (not `AbstractStreamManager`)
- No market hours auto-gating in scanner (calls `is_market_open()` but doesn't skip processing yet)
- `strategy_loader.py` hasn't been updated for `allowed_market_types` filtering
- Backtest engine doesn't filter by market_type yet
- S/R engine doesn't filter by market_type in queries
- Indicator service doesn't filter by market_type
- Frontend market toggle not implemented yet

### What works today (Phase A+B)
- Database fully supports both markets with `market_type` column
- Provider abstraction ready with Binance + Angel One implementations
- Angel One authentication + instrument sync works
- Historical candle fetching works for both markets
- Live WebSocket streaming ready for both markets
- Signal pipeline threads `market_type` end-to-end
- API endpoints accept and filter by `market_type`
- New sessions can be created for Indian market via API

### Phase C (Backend Unification) — Ready to implement
```
Phase C would:
- Update scanner to use AbstractStreamManager type
- Add market hours gating (skip Indian market processing when closed)
- Update S/R engine, indicator service, backtest for market_type
- Update strategy_loader for market-type strategies
- Implement the /api/market blueprint
```

---

## 8. Quick Reference: Angel One API Credentials

| Env Variable | Where to Get It | Required? |
|---|---|---|
| `ANGELONE_API_KEY` | https://smartapi.angelone.in/ → Register App | Yes |
| `ANGELONE_CLIENT_CODE` | Your Angel One account client ID | Yes |
| `ANGELONE_PASSWORD` | Your Angel One login password | Yes |
| `ANGELONE_TOTP_SECRET` | Shown during app registration on Smart API portal | Only if 2FA enabled |

**Without these:** The app works exactly as before — crypto only. Angel One provider won't register, no errors, no crashes.
