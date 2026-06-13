# Implementation Phases

## Phase A: Foundation — Database & Provider Abstraction

**Estimated:** 3 days  
**Risk:** Low — no existing functionality affected  
**Goal:** Database ready for both markets. Provider interface defined. Binance refactored.

### Tasks

1. **Database Migration**
   - Add `market_type` column to all 9 tables (`candles`, `watching_setups`, `confirmed_signals`, `rejected_signals`, `analysis_sessions`, `backtest_runs`, `backtest_trades`, `price_alerts`, `llm_prompt_logs`, `sr_zones`)
   - Update composite primary key on `candles` to include `market_type`
   - Update unique constraint on `sr_zones` to include `market_type`
   - Create `indian_instruments` table
   - Add migration ALTER statements in `app/__init__.py`
   - File: `backend/app/models/db.py`

2. **Provider Abstraction**
   - Create `backend/app/providers/base.py` — `AbstractMarketProvider` ABC
   - Create `backend/app/providers/__init__.py` — provider registry
   - No functional changes yet

3. **Binance Refactor**
   - Create `backend/app/providers/binance_provider.py`
   - Move `BinanceStreamManager` from `utils/binance.py` into this file
   - Wrap in `BinanceProvider` class implementing `AbstractMarketProvider`
   - Keep `utils/binance.py` as thin re-export wrapper for backward compatibility
   - Verify all existing tests pass

### Success Criteria
- `db.create_all()` succeeds with new columns
- Existing crypto functionality unchanged
- `get_provider('CRYPTO')` returns valid `BinanceProvider`
- All existing tests pass

---

## Phase B: Angel One Integration

**Estimated:** 4 days  
**Risk:** Medium — new external API dependency  
**Goal:** Angel One provider fully functional for historical + live data

### Tasks

1. **SDK Setup**
   - Add `smartapi-python` to `requirements.txt`
   - Add `pyotp` for TOTP generation
   - Create env vars: `ANGELONE_API_KEY`, `ANGELONE_CLIENT_CODE`, `ANGELONE_PASSWORD`, `ANGELONE_TOTP_SECRET`

2. **Provider Implementation**
   - Create `backend/app/providers/angelone_provider.py`
   - Implement `connect()` — authentication + session management
   - Implement `_sync_instruments()` — pull instrument master, populate DB
   - Implement `fetch_candles()` — historical data via REST
   - Implement `create_stream()` — WebSocket streaming with normalizer
   - Implement `get_market_hours()`, `is_market_open()`
   - Implement `resolve_symbol()` — token lookup
   - Implement `get_option_chain()` — option chain data

3. **WebSocket Normalization**
   - Angel One WS returns different message format
   - `AngelOneStreamManager` normalizes to Binance-compatible format
   - Same callback signature as `BinanceStreamManager`:
     - `on_candle_close(symbol, timeframe, candle_dict)`
     - `on_price_update(symbol, price, timestamp)`
     - `on_live_candle(symbol, timeframe, live_candle_dict)`

4. **Instrument Master Sync**
   - Daily sync at 8:15 AM IST (after Angel One updates)
   - Cache in `indian_instruments` DB table
   - Build in-memory `_token_map` and `_reverse_token_map`
   - Handle instrument additions (new listings, new option strikes)

5. **Tests**
   - Unit tests for `resolve_symbol()`
   - Mock tests for `fetch_candles()` response parsing
   - Market hours logic tests (IST timezone edge cases)
   - Instrument master sync test

### Success Criteria
- `get_provider('INDIAN')` returns authenticated `AngelOneProvider`
- Historical candle fetch returns correctly formatted data
- WebSocket stream delivers normalized candle close events
- Market hours detection correct for IST
- Instrument search works

---

## Phase C: Backend Unification

**Estimated:** 3 days  
**Risk:** Medium — touches core scanner/conductor logic  
**Goal:** Scanner, data utils, API routes, and strategies all market-aware

### Tasks

1. **Scanner Updates** (`scanner.py`)
   - `AnalysisSession` gains `market_type` field
   - `start_session()` accepts `market_type` param, routes to correct provider
   - `_on_candle_close()` respects market hours (skip when closed)
   - `_backfill_historical_data()` uses provider's fetch method
   - `_ensure_sr_zones()` includes `market_type`
   - Market session auto-stop at close + auto-restart at open (optional)

2. **Data Utilities** (`data_utils.py`)
   - `get_finalized_candles()` accepts `market_type` parameter
   - All DB queries include `market_type` filter

3. **API Route Updates**
   - `signals_bp.py` — all endpoints filter by `market_type` query param
   - `data.py` — new `POST /import/angelone` endpoint
   - SSE stream includes `market_type` in all events
   - New `market_bp.py` blueprint with `/status`, `/instruments`, `/option-chain`

4. **Strategy Updates**
   - `BaseStrategy` gains `allowed_market_types: List[str]`
   - `StrategyRegistry` filters by market type
   - `StrategyRunner.run_single_scan()` propagates `market_type` to data fetches
   - Existing strategies default to `['CRYPTO']`

5. **Configuration** (`config.py`)
   - `SUPPORTED_INDIAN_EQUITY_SYMBOLS`
   - `SUPPORTED_INDIAN_INDEX_SYMBOLS`
   - `INDIAN_ROUND_NUMBER_CONFIG`
   - `INDIAN_MARKET_SESSION`
   - `INDIAN_STRATEGY_OVERRIDES`

6. **Registry** (`app/__init__.py`)
   - Initialize Angel One provider on startup
   - Register `market_bp` blueprint
   - Run instrument master sync (async, non-blocking)

### Success Criteria
- `POST /sessions` with `market_type: 'INDIAN'` starts Indian market session
- `GET /watching?market_type=INDIAN` returns only Indian setups
- SSE events correctly tagged with market_type
- Existing crypto sessions unaffected
- Indian sessions handle market open/close correctly

---

## Phase D: Frontend

**Estimated:** 3 days  
**Risk:** Low — purely additive UI changes  
**Goal:** Full market toggle, market-aware UI across all pages

### Tasks

1. **Market Context & Toggle**
   - Create `MarketContext.tsx` with localStorage persistence
   - Add toggle to `App.tsx` sidebar
   - Add market status badge (Indian only)
   - Color theme switching (emerald for crypto, orange/saffron for Indian)

2. **Signal Feed Adaptations**
   - `SignalFeed.tsx` — pass `marketType` to all API calls, filter SSE events
   - `SessionPanel.tsx` — market-aware symbol/timeframe/strategy selectors
   - Quick Start adapts per market

3. **Signal Cards**
   - `WatchingCard`, `ConfirmedCard`, `RejectedCard` — add `MarketBadge`
   - New `MarketBadge` component

4. **Charts Page**
   - Symbol selector market-aware
   - Candle fetch includes `market_type`

5. **Historical Data Page**
   - Market toggle between Binance and Angel One import tabs
   - Angel One form with symbol search, timeframe, date range

6. **Types & API Client**
   - Add `MarketType` to all TypeScript interfaces
   - Add `marketType` param to `startSession()`, `fetchCandles()`, etc.
   - Add new API functions: `searchIndianInstruments`, `fetchMarketStatus`, `fetchOptionChain`

### Success Criteria
- Toggle switches between Crypto and Indian views
- Indian market shows correct symbols, timeframes, strategies
- Signal cards display market type badge
- Charts load Indian market data correctly
- Market status indicator updates in real-time

---

## Phase E: Indian Market Strategies

**Estimated:** 3 days  
**Risk:** Medium — strategy logic is domain-specific  
**Goal:** At least 2 working Indian-specific strategies

### Tasks

1. **Opening Range Breakout** (`indian_orb.py`)
   - Opening range detection (first 15m candle)
   - Breakout confirmation gates
   - Entry/SL/TP calculation

2. **VWAP Mean Reversion** (`indian_vwap_reversal.py`)
   - VWAP computation (daily reset)
   - Deviation + reversal confirmation
   - Time-of-day filtering

3. **(Stretch) Gap Fill Strategy** (`indian_gap_fill.py`)
   - Gap detection from prior close
   - First-60-minute constraint gates

4. **VWAP Indicator** (new feature)
   - Add `compute_vwap()` to `indicators.py`
   - Add `vwap` to `required_features` system
   - Daily reset based on market open time

5. **Backtest Validation**
   - Backtest each strategy on 1 year of Indian market data
   - Validate win rate, Sharpe, max drawdown
   - Tune gate thresholds based on results

### Success Criteria
- ORB strategy detects valid breakouts and generates signals
- VWAP strategy correctly reverts extended moves
- Backtests produce realistic metrics
- Strategies appear in frontend strategy selector for Indian market

---

## Phase F: Polish & Handover

**Estimated:** 2 days  
**Risk:** Low  
**Goal:** Production-ready, documented, tested

### Tasks

1. **Integration Testing**
   - End-to-end: start Indian session → candle close → strategy fires → watching card → LLM confirmation → confirmed signal
   - Market hours edge cases (pre-open, closing auction, weekends, holidays)
   - Concurrent crypto + Indian sessions (resource usage)
   - WebSocket reconnect after market close/reopen cycle

2. **Error Handling**
   - Angel One API downtime → graceful degradation, retry with backoff
   - Auth token expiry → auto-reconnect
   - Instrument master stale → alert, fallback to cached data
   - Market holiday calendar → skip processing entirely

3. **Performance**
   - Indian instrument master sync should not block startup
   - WebSocket normalization should be lightweight
   - DB queries with market_type index should be fast

4. **Documentation**
   - Update README.md with Indian market section
   - Add `.env.example` with Angel One config
   - Add setup guide for Angel One account + API key creation

### Success Criteria
- Full signal pipeline works for Indian market end-to-end
- App handles market open/close transitions cleanly
- No crypto functionality regression
- Documentation complete for new users

---

## Timeline Summary

| Phase | Description | Est. Days | Cumulative |
|---|---|---|---|
| A | Foundation (DB + Provider Interface + Binance Refactor) | 3 | 3 |
| B | Angel One Integration (Provider + WS + Instruments) | 4 | 7 |
| C | Backend Unification (Scanner + API + Strategies) | 3 | 10 |
| D | Frontend (Toggle + UI + Types) | 3 | 13 |
| E | Indian Market Strategies | 3 | 16 |
| F | Polish & Handover | 2 | 18 |

**Total estimated: 18 working days (~3.5 weeks)**
