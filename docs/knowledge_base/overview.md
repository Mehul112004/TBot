# TBot Architecture Overview

TBot is a multi-strategy signal intelligence platform that ingests real-time market data from Binance Futures, applies technical analysis strategies, and optionally validates signals through LLM-based reasoning before surfacing them to the frontend and Telegram.

---

## 1. System Startup

```
run.py  →  create_app()
              ├── Flask + CORS
              ├── SQLAlchemy (PostgreSQL) + auto-migrations
              ├── StrategyRegistry.load_builtin_strategies() + sync_with_db()
              ├── Register 7 API blueprints
              └── Launch background services:
                    ├── LiveScanner (singleton, idle until session started)
                    ├── APScheduler (periodic S/R zone refresh every 1h/4h)
                    ├── LLMQueueManager (background LLM validation worker)
                    ├── TelegramDeliveryManager (message delivery worker)
                    ├── OutcomeTracker (in-memory cache of active signals)
                    └── PriceAlertTracker (in-memory cache of price alerts)
```

### API Blueprints

| Prefix | Purpose |
|---|---|
| `/api/data` | Historical candles, Binance import, CSV import |
| `/api/indicators` | Indicator computation and retrieval |
| `/api/sr-zones` | Support/Resistance zone queries and refresh |
| `/api/strategies` | Strategy listing, enable/disable, confidence tuning |
| `/api/signals` | Analysis sessions, watching setups, confirmed signals, SSE stream |
| `/api/backtest` | Backtest execution, history, export |
| `/api/alerts` | User-defined price alert CRUD |

### Infrastructure

- **PostgreSQL 15** via Docker (container `signals_db`, port 5432)
- The platform is a single Flask process — no separate "backtest mode" or "live mode" binary. Backtesting is a REST endpoint, live scanning is background-threaded.

---

## 2. Data Flow

### 2.1 Historical Data (REST)

```
Binance REST API (fapi.binance.com)
       │
       ▼
fetch_klines(symbol, timeframe, start_ms, end_ms)
       │  Paginates 1000 candles/request
       ▼
List[dict] of OHLCV rows
       │
       ├──► POST /api/data/import/binance  →  bulk upsert into candles table
       │
       └──► POST /api/data/import/csv      →  csv_parser.validate()  →  bulk upsert
```

### 2.2 Real-Time Data (WebSocket)

```
Binance Futures WebSocket (fstream.binance.com)
       │  Combined stream: btcusdt@kline_1h/btcusdt@kline_4h/...
       ▼
BinanceStreamManager (daemon thread, auto-reconnect with exponential backoff)
       │
       ├── on_price_update(symbol, price, timestamp)        every tick
       ├── on_live_candle(symbol, tf, candle)                every ~1s (throttled 500ms)
       └── on_candle_close(symbol, tf, candle)                on kline.x == True
              │
              ▼
       LiveScanner._on_candle_close()    ← THE MAIN LOOP (described below)
```

### 2.3 Cold Start & Gap Healing

On session start:
- If DB has <400 candles for the symbol/timeframe → backfills ~480 candles from REST API
- On every candle close: compares incoming `open_time` against the last stored candle. If a temporal gap > 500ms is detected, immediately backfills the missing candles via REST API — ensuring indicators that depend on recursive state (EMA, RSI, MACD) always see contiguous data.

---

## 3. The Candle Close Pipeline (Core Loop)

This is the heart of the platform. Every time a kline closes on Binance:

```
1. UPSERT closed candle into candles table
2. DETECT & HEAL temporal gaps (REST backfill if needed)
3. INVALIDATE indicator cache for (symbol, timeframe)
4. REFRESH S/R ZONES
     ├── 4h / 1d candles  →  full refresh (swing points, round numbers, prev day/week)
     └── 1h / 15m candles →  minor update (swing points on recent 50 candles)
5. COMPUTE INDICATORS  ──  EMA 9/21/50/100/200, RSI 14, MACD, BB, ATR 14, Volume MA 20, ADX 14
6. DETECT MARKET REGIME ──  TRENDING_UP / TRENDING_DOWN / RANGING / CHOPPY
7. FETCH nearby S/R zones within ±3% of current price
8. RUN each enabled strategy via StrategyRunner.run_single_scan()
9. On SIGNAL:  WatchingManager.create_or_update_setup()
                → SSE push to frontend
                → Telegram "watching" alert
                → Enqueue for LLM validation
10. TICK expiry counters on existing watching setups
11. PUSH SSE events: live candle update, price update
```

### Live Tick Strategies

Strategies with `run_on_live_candle=True` (e.g. EMA Cross Alert) run every ~10 seconds on the evolving (not-yet-closed) candle rather than on candle close.

---

## 4. Indicator System

All indicators are **pure stateless functions** — `pd.Series` in, `pd.Series` out. No caching, no DB access, no side effects.

| Function | Computes |
|---|---|
| `compute_ema(closes, period)` | Exponential Moving Average |
| `compute_rsi(closes, period=14)` | Relative Strength Index (0-100) |
| `compute_macd(closes, fast, slow, signal)` | MACD line, signal line, histogram |
| `compute_bollinger(closes, period, std_dev)` | Upper/Middle/Lower bands, %B, bandwidth |
| `compute_atr(highs, lows, closes, period=14)` | Average True Range |
| `compute_keltner(highs, lows, closes, period, atr_mult)` | Keltner Channel |
| `compute_adx(highs, lows, closes, period=14)` | Average Directional Index (0-100) |
| `compute_volume_ma(volumes, period=20)` | Volume Moving Average |

**IndicatorService** wraps these with:
- DB fetch (gets candles from the database)
- Caching by `(symbol, timeframe, last_open_time)`
- API serialization helpers

Minimum candles required: 20 (hard minimum), 400 (ideal warmup).

---

## 5. Market Regime

Before strategy execution, the engine determines market context:

```
detect_market_regime(df)
    ├── Uses ADX 14, EMA 100, EMAs 50/200 position
    ├── Hysteresis: once trending, stays trending until EMA 100 crossed or ADX < 15
    ├── BB bandwidth percentile  →  volatility_regime: LOW / NORMAL / HIGH
    └── Outputs: regime, regime_strength, volatility_regime, structural_bias
```

Strategies declare `allowed_regimes` — they only fire when the current regime matches.

---

## 6. Market Structure (SMC Concepts)

Several features are extracted from raw candles before strategy evaluation:

| Module | What It Detects |
|---|---|
| `market_structure.py` | **Order Blocks (OB)**: last bullish/bearish candle before a strong move. **Fair Value Gaps (FVG)**: 3-candle imbalances where wicks don't overlap |
| `events.py` | **BOS (Break of Structure)**: continuation breaks beyond prior swing. **CHoCH (Change of Character)**: reversal breaks. **Volume Climax**: volume 2x+ average. **Liquidity Sweeps**: wicks beyond a key level with close inside |
| `fractals.py` | **Swing High/Low**: local maxima/minima via ±N candle lookback |
| `confluence.py` | **Multi-timeframe alignment**: checks HTF trend direction matches LTF signal |

---

## 7. Strategy System

### Base Strategy Contract

```python
class BaseStrategy(ABC):
    name: str
    version: str                    # "3.0"
    timeframes: List[str]           # e.g. ["1h", "4h"]
    allowed_regimes: List[str]      # e.g. ["TRENDING_UP", "TRENDING_DOWN"]
    require_htf_alignment: bool
    min_confidence: float           # 0.0 to 1.0
    run_on_live_candle: bool        # run on every tick instead of candle close
    required_features: List[str]    # ['ema', 'rsi', 'macd', 'bb', 'atr', 'adx', ...]
    sl_atr_mult: float
    tp1_rr: float
    tp2_rr: float

    @classmethod
    def pre_process(df, symbol, timeframe) → pd.DataFrame
        # Loads only required features + always ADX, EMA 50/100/200, ATR

    @abstractmethod
    def generate_signals(df) → pd.DataFrame
        # Must add columns: signal, direction, confidence
        # Uses gate-based evaluation

    def calculate_sl(signal, df, signal_idx, atr) → float
        # Structural stop loss: 5-bar pivot ± ATR multiplier

    def calculate_tp(signal, df, signal_idx, atr) → (float, float)
        # Risk-based take profits: entry ± RISK*1.5, entry ± RISK*3.0
```

### Gate-Based Confidence System

Each strategy defines a set of conditions. Every condition is either a **hard gate** (must pass) or a **soft gate** (contributes to confidence). Confidence is computed as:

```
confidence = (hard_gates_passed + soft_gates_passed) / total_gates
```

This makes confidence **transparent and comparable** across strategies.

### Active Strategies

| Strategy | TF | Regime Requirement | Trigger |
|---|---|---|---|
| **Trend Following** | 1h | Trending | EMA 21 pullback, ADX ≥ 25, EMA stack aligned |
| **Burner 9/20** | 1h | Trending | 9/20 EMA pullback, 200 EMA filter, hidden divergence, trap detection |
| **Breakout & Retest** | 4h | Trending | BOS/CHoCH with retest, rejection at broken level |
| **Liquidity Sweep** | 4h | All | Wick beyond key level, close inside, momentum shift |
| **Key Level Reversal** | 15m | All incl. Ranging | 4+ touches, engulfing ≥2x body, RSI extreme, volume ≥2x, weakening ADX |
| **EMA Cross Alert** | 30m, 1h | All | Live tick: 9/20 EMA imminent crossover → direct Telegram alert |

### Strategy Auto-Discovery

The `StrategyRegistry` scans `app/strategies/` at startup, imports all `.py` files, finds `BaseStrategy` subclasses, and registers them. State (enabled/disabled, min_confidence) is persisted in the `strategies` DB table.

---

## 8. Support/Resistance Zones & Pivot Points

The chart overlays **four independent horizontal-level layers**, each toggleable:

| Layer | Source | Style | Toggle |
|---|---|---|---|
| **S/R Zones** | `sr_engine.py` — swing detection + round numbers | Filled **bands** (rectangles) | Green |
| **Pivot Points** | `pivot_engine.py` — Camarilla/Standard from prev day's H/L/C | Thin **lines** | Purple |
| **Psych Levels** | `sr_engine.detect_round_numbers` (large grain) | Faint dotted lines | Amber (off by default) |
| **SMC Zones** | `market_structure.py` — FVG/OB/CHoCH/BoS | Lines + markers | Cyan |

> See [docs/logic/sr_engine.md](../logic/sr_engine.md), [docs/logic/pivot_points.md](../logic/pivot_points.md), and [docs/knowledge_base/sr_zones_and_pivots.md](./sr_zones_and_pivots.md) for full details.

### S/R Zone Detection (v2.0 — de-bloated)

| Method | Algorithm |
|---|---|
| **Swing Points** | ±12 candle lookback local maxima/minima (structural pivots, not micro-noise) |
| **Round Numbers** | Psychological levels — large grain only (BTC $5000, ETH $500, SOL $50; dynamic for unknown symbols) |
| ~~**Previous Day/Week H/L**~~ | Removed — subsumed by the richer Pivot Points layer |

### Zone Processing

1. **Width** = price_level ± (0.25 × ATR)
2. **Merge** overlapping zones within **0.75 × ATR** (iterate until stable)
3. **Score** = touch-gated + recency-decayed:
   - `<2 touches` → score 0 (a single touch is not S/R)
   - `base = min(1.0, (touches − 1) × 0.12 + tf_weight × 0.5)`
   - `strength = base × exp(−age / 150)` (halflife ~104 bars)
4. **Temporal Masking**: zones only appear after their formation candle (prevents lookahead bias)
5. **Persist** to `sr_zones` table via upsert (full refresh wipes stale rows first)
6. **Filter**: zones with `<2 touches` are never persisted or charted

### Multi-Timeframe (MTF) Stacking

The chart shows the viewed timeframe's zones **plus 2 higher timeframes** up the ladder `[15m, 1h, 4h, 1d, 1w]`. Example: viewing `1h` shows `1h + 4h + 1d` zones. **Confluence** is flagged when a viewed-TF band overlaps an HTF band (marked with `*` on the chart).

### Pivot Points

Computed on-the-fly (not persisted) from the **previous completed** UTC day's 1D candle. **Camarilla** is the default variant (H3/L3 = reversal zones, H4/L4 = breakout levels, P = bias line). See [pivot_points.md](../logic/pivot_points.md) for formulas and label meanings.

### Refresh Schedule

| Trigger | Scope | Prune? |
|---|---|---|
| APScheduler: 4h at :01 UTC | `4h` full refresh | Yes |
| APScheduler: daily at :02 UTC | `1d` full refresh | Yes |
| APScheduler: hourly at :03 UTC | `1h`, `15m` minor update (swing only) | No |
| Startup (on boot) | All supported TFs full refresh | Yes |
| 4h/1d candle close | Full refresh | Yes |
| 1h/15m candle close | Minor update | No |
| Session start (no zones) | Full refresh | Yes |

---

## 9. Signal → LLM → Confirmation Pipeline

### Watching Manager

- Deduplicates signals: one WATCHING setup per `(session_id, strategy_name, symbol, timeframe)` at a time
- Tracks `candles_since_detected` — increments on each candle close
- Expires setups after `SIGNAL_EXPIRY_CANDLES` (default 3) candle closes with no price trigger

### LLM Validation Flow

```
Signal detected
    │
    ▼
LLMQueueManager.enqueue_signal()
    │
    ▼
Background worker:
    1. Fetch HTF candles (4h, 1d)
    2. Fetch live market data (funding rate, OI change, trading session)
    3. Build structured context payload (8 dimensions):
         a. Signal metadata (strategy, TF, direction, confidence)
         b. Risk metrics (entry, SL, TP1, TP2, R:R)
         c. Market structure (S/R zones, OB, FVG, BOS, CHoCH)
         d. Indicators snapshot
         e. Volume analysis
         f. HTF context
         g. Recent price action narrative
         h. Classified candlestick patterns
    4. Send to LLM provider (LM Studio / Groq / OpenAI / Vertex AI) with system prompt
    5. Parse JSON response → LLMVerdictSchema
    6. Handle verdict:
         ├── CONFIRM / MODIFY → store ConfirmedSignal
         │      ├── SSE event: signal_confirmed
         │      ├── Telegram alert: confirmed
         │      └── OutcomeTracker: begin tracking SL/TP levels
         └── REJECT → store RejectedSignal
                ├── SSE event: setup_rejected
                └── Telegram alert: rejected
```

### Supported LLM Providers

- **LM Studio** — local (default, `http://localhost:1234`)
- **Groq** — cloud, fast inference
- **OpenRouter** — multi-model gateway
- **OpenAI** — GPT models
- **Google Vertex AI** — Gemini models

---

## 10. Outcome Tracking

The `OutcomeTracker` maintains an in-memory cache of all signals with `trade_outcome='ACTIVE'`. On every live price tick:

1. Check current price against SL level → if hit: mark `HIT_SL`, dispatch Telegram alert, push SSE event
2. Check against TP1 → `HIT_TP1`
3. Check against TP2 → `HIT_TP2`
4. Expire signals after `timeframe_duration * 24` (favorable) or `* 8` (unfavorable) minutes of inactivity

**TBot does not execute orders.** It only tracks outcomes conceptually. It is a signal intelligence platform, not an execution engine.

---

## 11. Frontend (React + TypeScript)

### Pages

| Page | Purpose |
|---|---|
| **Signal Feed** | Live watching/confirmed/rejected cards, session controls, SSE connection |
| **Charts** | Candlestick chart with indicator overlays |
| **Backtest** | Configure and run backtests |
| **Backtest Analyzer** | Detailed per-trade analysis |
| **Historical Data** | Import Binance data or upload CSV |
| **LLM Prompts** | View full LLM interaction logs |
| **Price Alerts** | Manage user-defined price alerts |

### Real-Time Updates (SSE)

The frontend connects to `/api/signals/events` via EventSource. Events include:

- `price_update` — real-time price tick
- `live_candle` — evolving candle update
- `candle_close` — final closed candle
- `signal_detected` — new watching setup
- `signal_confirmed` — LLM approved
- `setup_rejected` — LLM rejected
- `signal_expired` — watching setup timed out
- `outcome_hit` — TP1/TP2/SL hit

---

## 12. Complete Signal Lifecycle (End-to-End)

```
User clicks "Start Session" in Signal Feed
         │
         ▼
POST /api/signals/sessions  {"symbol": "BTCUSDT", "strategy_names": ["Trend Following"]}
         │
         ▼
LiveScanner.start_session()
    ├── Starts BinanceStreamManager (WebSocket → Binance)
    ├── Backfills historical candles from REST API (if needed)
    ├── Ensures S/R zones exist for the symbol
    └── Listens for kline events
         │
         ▼
    KLINE CLOSES on Binance (e.g., 1h candle)
         │
         ▼
    _on_candle_close()
         ├── Persist candle to DB
         ├── Heal gaps
         ├── Refresh S/R zones
         ├── Compute indicators + regime
         └── Run "Trend Following" strategy
               │
               ▼
    SIGNAL DETECTED (confidence ≥ threshold, regime matches)
         │
         ▼
    WatchingManager: create WATCHING setup (DB + SSE + Telegram)
         │
         ▼
    LLMQueueManager: build 8-dimension context → send to LLM
         │
         ├── LLM CONFIRMS ──► ConfirmedSignal stored
         │      └── OutcomeTracker begins monitoring SL/TP levels
         │
         └── LLM REJECTS ──► RejectedSignal stored
                └── Setup moves to "REJECTED" status
         │
         ▼
    (If confirmed) OutcomeTracker watches every price tick
         │
         ├── Price hits TP1 → mark HIT_TP1
         ├── Price hits TP2 → mark HIT_TP2
         └── Price hits SL  → mark HIT_SL
```

---

## 13. Key Design Principles

1. **Pure functions for indicators** — no side effects, no DB access, trivially testable
2. **Gate-based confidence** — transparent, comparable, no magic numbers
3. **Stateless strategy execution** — strategies take a DataFrame, return a DataFrame. The scanner owns all I/O.
4. **Backtest uses the same code path** — `StrategyRunner.scan_historical()` runs the exact same `pre_process()` + `generate_signals()` pipeline over historical candles
5. **All state is in DB** — in-memory caches are read-through. Server restart loses nothing.
6. **Temporal integrity** — gap detection + auto-healing ensures indicators never see discontinuous data
7. **Temporal masking** — S/R zones and structure events only exist after their formation bar, preventing lookahead bias in backtests
8. **Human + AI readability** — every signal decision is traceable through gate logs, LLM prompt logs, and the DB
