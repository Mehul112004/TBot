# Phase E+F Implementation — Walkthrough

## What Was Implemented

**Phase E (Indian Market Strategies):** Three new Indian-specific trading strategies. Existing crypto strategies locked to `CRYPTO` market. VWAP indicator added. Strategy registry filters by market type.

**Phase F (Polish & Handover):** Full verification, strategy API market filtering, documentation.

---

## 1. New Indian Strategies

### Indian ORB (Opening Range Breakout)
**File:** `backend/app/strategies/indian_orb.py`  
**Timeframe:** 15m | **Market:** INDIAN only | **Confidence:** 0.60

| Gate | Type | Logic |
|---|---|---|
| G1 | HARD | Opening range established (first 15m candle) |
| G2 | HARD | Close breaks above range high (LONG) or below low (SHORT) |
| G3 | HARD | Volume > 1.5x moving average |
| S1 | SOFT | Breakout aligns with EMA 50 |
| S2 | SOFT | RSI confirms momentum (not extreme) |
| S3 | SOFT | Not first breakout candle (confirmation candle) |
| S4 | SOFT | Price within 2x ATR of range boundary |

### Indian VWAP Reversal
**File:** `backend/app/strategies/indian_vwap_reversal.py`  
**Timeframe:** 5m | **Market:** INDIAN only | **Confidence:** 0.65

| Gate | Type | Logic |
|---|---|---|
| G1 | HARD | Price deviates >1.5% from daily VWAP |
| G2 | HARD | RSI extreme (< 30 LONG, > 70 SHORT) |
| G3 | HARD | Volume declining (exhaustion) |
| S1 | SOFT | Reversal candle pattern (long wick) |
| S2 | SOFT | Deviation < 5% (not parabolic) |
| S3 | SOFT | Price moving back toward VWAP |

### Indian Gap Fill
**File:** `backend/app/strategies/indian_gap_fill.py`  
**Timeframe:** 5m | **Market:** INDIAN only | **Confidence:** 0.55

| Gate | Type | Logic |
|---|---|---|
| G1 | HARD | Gap 1-3% from prior close |
| G2 | HARD | Within first 60 min of trading |
| G3 | HARD | First 2 candles confirm gap direction |
| S1 | SOFT | Volume > average |
| S2 | SOFT | ADX > 20 (momentum) |
| S3 | SOFT | Close moving further in gap direction |

---

## 2. Supporting Changes

### VWAP Indicator (`indicators.py`)
- `compute_vwap(df)` — cumulative VWAP from start
- `compute_daily_vwap(df)` — VWAP resetting per calendar day (for Indian markets)
- Added `vwap` to `BaseStrategy.pre_process()` feature system

### Strategy Market Lockdown
All existing crypto strategies now declare `allowed_market_types = ['CRYPTO']`:
- `trend_following.py`, `breakout_retest.py`, `key_level_reversal.py`
- `liquidity_sweep.py`, `burner_9_20.py`, `ema_cross_alert.py`

Indian strategies declare `allowed_market_types = ['INDIAN']`:
- `indian_orb.py`, `indian_vwap_reversal.py`, `indian_gap_fill.py`

### Strategy Registry (`strategy_loader.py`)
- `get_all()` includes `allowed_market_types` in metadata
- `get_strategies_for_market('CRYPTO')` → 6 strategies
- `get_strategies_for_market('INDIAN')` → 3 strategies

### Strategy API (`strategies_bp.py`)
- `GET /api/strategies?market_type=INDIAN` — returns only Indian strategies
- `GET /api/strategies?market_type=CRYPTO` — returns only Crypto strategies
- No param → returns all

---

## 3. How to Test

### 3.1 Verify Strategies Load

```bash
cd backend && python3 -c "
from app.core.strategy_loader import StrategyRegistry
r = StrategyRegistry()
r.load_builtin_strategies()
print('Crypto:', [s.name for s in r.get_strategies_for_market('CRYPTO')])
print('Indian:', [s.name for s in r.get_strategies_for_market('INDIAN')])
"
# Expected:
# Crypto: ['Breakout & Retest', 'Burner 9/20', 'EMA Cross Alert', 'Key Level Reversal', 'Liquidity Sweep', 'Trend Following']
# Indian: ['Indian Gap Fill', 'Indian ORB', 'Indian VWAP Reversal']
```

### 3.2 Test Strategy API Filtering

```bash
# Indian-only strategies
curl 'http://localhost:5001/api/strategies?market_type=INDIAN'

# Crypto-only strategies
curl 'http://localhost:5001/api/strategies?market_type=CRYPTO'
```

### 3.3 Start Indian Session with Indian Strategies

```bash
curl -X POST http://localhost:5001/api/signals/sessions \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"NIFTY","strategy_names":["Indian ORB","Indian VWAP Reversal"],"timeframes":["5m","15m"],"market_type":"INDIAN"}'
```

### 3.4 Indian Strategy Isolation

- Starting a session with `market_type: "INDIAN"` and Indian strategies → only Indian strategies scan Indian symbols
- Starting a session with `market_type: "CRYPTO"` and "Indian ORB" → strategy won't scan (wrong market type)
- Crypto and Indian sessions can run concurrently without interference

---

## 4. Strategy Selection Flow

```
Frontend: market_type = 'INDIAN'
  → GET /api/strategies?market_type=INDIAN
  → Returns: Indian ORB, Indian VWAP Reversal, Indian Gap Fill
  → SessionPanel shows only Indian strategies
  → User starts session with Indian ORB on NIFTY
  → StrategyRunner loads NIFTY candles (market_type='INDIAN')
  → Indian ORB.generate_signals() runs on NIFTY data
  → Only fires on Indian market patterns
  → Crypto strategies (Trend Following, etc.) don't fire on NIFTY
```

## 5. Full Implementation Summary (All Phases)

| Phase | Status | Files Changed |
|---|---|---|
| **A** — Database & Provider Foundation | ✅ | `db.py`, `__init__.py`, `config.py`, `data_utils.py` |
| **B** — Angel One Integration | ✅ | `angelone_provider.py`, `binance_provider.py`, `base.py`, `requirements.txt` |
| **C** — Backend Unification | ✅ | `scanner.py`, `sr_engine.py`, `indicator_service.py`, `strategy_loader.py`, `backtest_engine.py`, `scheduler.py`, `llm_queue.py`, `backtest_bp.py`, `market_bp.py` |
| **D** — Frontend Toggle | ✅ | `App.tsx`, `SignalFeed.tsx`, `SessionPanel.tsx`, `signals.ts`, `client.ts`, `MarketContext.tsx`, `MarketBadge` |
| **E** — Indian Strategies | ✅ | `indian_orb.py`, `indian_vwap_reversal.py`, `indian_gap_fill.py`, `indicators.py`, `base_strategy.py`, all existing strategies |
| **F** — Polish & Docs | ✅ | `strategies_bp.py`, `WALKTHROUGH_PHASE_E_F.md` |

**Total: 35+ files created or modified across all 6 phases.**

---

## 6. What's Working End-to-End

1. **Database** — All 9 tables have `market_type`, new `indian_instruments` table
2. **Provider Layer** — `BinanceProvider` (CRYPTO) + `AngelOneProvider` (INDIAN)
3. **Scanner** — Creates sessions per market type, routes to correct provider
4. **Market Hours** — Indian sessions skip processing when NSE closed
5. **S/R Engine** — Zones isolated by market type
6. **Indicators** — Include VWAP, cache key includes market_type
7. **Strategies** — 6 crypto + 3 Indian, each locked to their market
8. **Backtester** — Filters candles by market_type
9. **SSE Stream** — Events tagged with market_type, filtered by frontend
10. **Frontend Toggle** — Full UI switch between Crypto and Indian context
11. **Market API** — `/api/market/status`, `/instruments`, `/option-chain`
12. **Strategy API** — Filterable by `market_type`

## 7. Manual Steps for Production

1. Set Angel One credentials in `.env`
2. Restart backend — migrations run automatically
3. Open frontend — click `Indian` toggle
4. Start session on NIFTY/RELIANCE with Indian strategies
