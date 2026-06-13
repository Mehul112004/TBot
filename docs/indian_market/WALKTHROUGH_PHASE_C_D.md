# Phase C+D Implementation — Walkthrough

## What Was Implemented

**Phase C (Backend Unification):** The scanner, S/R engine, indicator service, backtest engine, strategy loader, scheduler, and all API blueprints now fully support dual-market operation via the `market_type` field.

**Phase D (Frontend):** A global market toggle (`CRYPTO` ↔ `INDIAN`) switches the entire UI context — symbols, timeframes, API calls, SSE filtering, and signal cards.

---

## 1. Phase C: Backend Unification (Files Modified)

### `backend/app/core/scanner.py`
- `AnalysisSession` uses `AbstractStreamManager` type instead of `BinanceStreamManager`
- **Market hours gating**: `_on_candle_close()` checks `is_market_open()` for Indian sessions — skips processing when NSE is closed
- All DB queries (candles, S/R zones) filtered by `market_type`

### `backend/app/core/sr_engine.py`
- `detect_zones()` — accepts `market_type`, filters candle query
- `full_refresh()` and `minor_update()` — accept & propagate `market_type`
- `persist_zones()` — accepts `market_type`, includes in upsert/fallback queries
- `_build_zone_record()` — includes `market_type` in DB record

### `backend/app/core/indicator_service.py`
- `_fetch_candles_df()` — accepts `market_type`, filters candle query
- `compute_all()` — accepts `market_type`, included in cache key
- Cache key: `(symbol, timeframe, last_open_time, market_type)` — prevents Crypto/Indian cache collisions

### `backend/app/core/strategy_loader.py`
- New `get_strategies_for_market(market_type)` — returns strategies that support the given market
- New `get_all_metadata_for_market(market_type)` — returns metadata for market-specific strategies
- Reads `allowed_market_types` from strategy class (defaults to `['CRYPTO']`)

### `backend/app/core/backtest_engine.py`
- `run()` accepts `market_type` param
- Filters candles by `market_type` in DB query
- Stores `market_type` on `BacktestRun` record

### `backend/app/core/scheduler.py`
- `_get_active_symbols()` returns `(symbol, market_type)` tuples
- All refresh functions pass `market_type` to SREngine calls
- `startup_full_refresh` handles both crypto and Indian symbols

### `backend/app/core/llm_queue.py`
- `_fetch_htf_df_for_llm()` accepts `market_type` and passes to `get_finalized_candles()`

### `backend/app/blueprints/backtest_bp.py`
- `POST /run` accepts `market_type` in request body
- `GET /history` accepts optional `market_type` query param

### `backend/app/blueprints/market_bp.py` **(NEW)**
Three endpoints:
- `GET /api/market/status` — open/closed status for all registered markets
- `GET /api/market/instruments?q=RELIANCE` — Indian instrument search (DB-backed)
- `GET /api/market/option-chain?symbol=NIFTY&expiry=2024-06-27` — option chain

### `backend/app/__init__.py`
- Registers `market_bp` blueprint at `/api/market`

---

## 2. Phase D: Frontend (Files Modified/Created)

### New Files (3)
| File | Purpose |
|---|---|
| `frontend/src/contexts/MarketContext.tsx` | React Context providing `marketType`, `setMarketType`, `toggleMarket` with localStorage persistence |
| `frontend/src/components/MarketBadge/MarketBadge.tsx` | Small "NSE" badge for Indian market signals |
| — | — |

### `frontend/src/main.tsx`
```tsx
<MarketProvider>
  <App />
</MarketProvider>
```

### `frontend/src/App.tsx`
- **Market toggle** in sidebar header: `[Crypto] [Indian]` segmented control
- **Accent color switching**: emerald for Crypto, orange for Indian
- **Title switching**: "Crypto Signals" / "Indian Markets"
- All page titles include market context
- Mobile drawer also has the toggle

### `frontend/src/pages/SignalFeed/SignalFeed.tsx`
- Imports and uses `useMarket()` context
- All API calls include `market_type` param
- SSE events filtered by active `marketType`
- `handleStartSession` passes marketType to API
- Quick Start adapts: Crypto starts BTC/ETH/SOL, Indian starts NIFTY/RELIANCE

### `frontend/src/pages/SignalFeed/SessionPanel.tsx`
- Symbol selector changes by market:
  - Crypto: `["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]`
  - Indian: 25 stock/index symbols (NIFTY, BANKNIFTY, RELIANCE, TCS, etc.)
- Timeframes adapt: Indian excludes `4h` (market is only 6h15), adds `1m`
- Market type badge on each session card
- Currency symbol switches: `$` for Crypto, `₹` for Indian

### `frontend/src/hooks/useAnalysisSessions.ts`
- `startSession()` accepts optional `marketType` and passes it to API

### `frontend/src/types/signals.ts`
- New `MarketType = 'CRYPTO' | 'INDIAN'` type
- Added `market_type: MarketType` to `AnalysisSession`, `WatchingSetup`, `ConfirmedSignal`, `RejectedSignal`

### `frontend/src/api/client.ts`
- `startSession()` accepts `marketType` param
- `fetchWatchingSetups()`, `fetchCandles()` accept optional `marketType`
- `fetchBacktestHistory()` accepts optional `marketType`
- New functions: `fetchMarketStatus()`, `searchIndianInstruments()`, `fetchOptionChain()`

---

## 3. How to Test

### 3.1 Verify Backend

```bash
# Market status (no creds needed for crypto)
curl http://localhost:5001/api/market/status

# Expected: {"crypto": {"is_open": true, "hours": {...}}}
# If Angel One is configured: {"crypto": {...}, "indian": {...}}

# Start Indian session
curl -X POST http://localhost:5001/api/signals/sessions \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"NIFTY","strategy_names":["Trend Following"],"timeframes":["15m","1h"],"market_type":"INDIAN"}'

# Filter by market type
curl 'http://localhost:5001/api/signals/watching?market_type=INDIAN'
curl 'http://localhost:5001/api/backtest/history?market_type=INDIAN'

# Indian instrument search
curl 'http://localhost:5001/api/market/instruments?q=RELIANCE'
```

### 3.2 Verify Frontend

```bash
cd frontend
npm run dev
```

- Open http://localhost:5173
- Toggle between **Crypto** and **Indian** in the sidebar
- Verify:
  - Page title changes
  - Accent color changes (emerald ↔ orange)
  - Signal Feed → Session Panel → symbol dropdown changes
  - Quick Start button label adapts
  - Starting a session with Indian market shows NSE badge on session card

### 3.3 S/R Zone Isolation

Crypto and Indian S/R zones are stored with different `market_type` values. Starting a NIFTY session will generate NIFTY zones without affecting BTC/ETH zones. The cache key includes `market_type` to prevent collisions.

### 3.4 Market Hours Gating

When Indian market is selected:
- If NSE is closed (after 3:30 PM IST or weekends), the scanner skips candle processing
- Crypto sessions continue uninterrupted (24/7)
- Market status endpoint shows real-time open/closed state

---

## 4. Architecture Flow (End-to-End)

```
User clicks [Indian] toggle
  → MarketContext.marketType = 'INDIAN'
  → App.tsx: title, accent, symbol list update
  → SessionPanel: shows NSE symbols, 1m/5m/15m/30m/1h/1d timeframes
  → User starts session: POST /sessions {market_type: "INDIAN", symbol: "NIFTY"}
  → Scanner creates session with market_type='INDIAN'
  → AngelOneProvider.create_stream() opens WebSocket
  → Candle closes → _on_candle_close() checks is_market_open()
  → If open: candle upserted with market_type='INDIAN'
  → S/R zones queried/filtered by market_type='INDIAN'
  → Strategies scan using market_type-aware data fetch
  → WatchingSetup stored with market_type='INDIAN'
  → SSE event published → SignalFeed filters by marketType
  → NSE badge shown on watching card
```

---

## 5. Limitations & Phase C+D Scope

### Done (Phase C+D)
- Backend fully market-aware (scanner, S/R, indicators, backtest, API)
- Frontend toggle with full context switching
- Market-aware session creation and management
- `/api/market` blueprint with status, instrument search, option chain
- Market hours gating

### Not Yet Done (Phase E territory)
- Indian-specific strategies (ORB, VWAP, Gap Fill) — scaffold only
- Strategy marker `allowed_market_types` on existing strategies (all currently run on Indian too)
- Frontend charts page market-aware (symbol selector not updated yet)
- Historical Data page Indian market tab
- Complete LLM context builder Indian additions
- Backtesting with Indian market data
