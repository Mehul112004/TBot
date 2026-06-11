# TBot File & Method Blueprint

This document maps every significant file in the TBot codebase to its classes, methods, and what each does.

---

## Entry Point

### `backend/run.py`

| Item | Signature | Purpose |
|---|---|---|
| *(main)* | — | Loads `.env`, imports `create_app`, runs Flask on `0.0.0.0:5001` |

---

## App Factory

### `backend/app/__init__.py`

| Item | Signature | Purpose |
|---|---|---|
| `create_app()` | `(config_class=None) → Flask` | Full orchestrator: Flask + CORS, SQLAlchemy init, table creation + DDL migrations, StrategyRegistry init + DB sync, blueprint registration, background service launch (LiveScanner, Scheduler, LLMQueue, TelegramQueue, OutcomeTracker, PriceAlertTracker). Skips background services if `TESTING=True`. |

---

## Blueprints (REST API)

### `backend/app/blueprints/data.py`

| Item | Signature | Purpose |
|---|---|---|
| `POST /api/data/import/binance` | — | Triggers `fetch_klines()` from Binance REST API, bulk upserts into `candles` table. Accepts `{symbol, timeframes[], days_back}`. |
| `POST /api/data/import/csv` | — | Accepts CSV file upload, validates via `csv_parser.validate()`, bulk upserts. |
| `GET /api/data/candles` | — | Returns candles for `?symbol=&timeframe=&limit=&start_time=&end_time=`. |
| `GET /api/data/datasets` | — | Lists available symbol/timeframe combinations in the DB. |

### `backend/app/blueprints/indicators_bp.py`

| Item | Signature | Purpose |
|---|---|---|
| `GET /api/indicators` | — | Returns latest indicator values for `?symbol=&timeframe=&include_series=`. |
| `POST /api/indicators/refresh` | — | Invalidates cache and recomputes all indicators for a symbol/timeframe. |
| `GET /api/indicators/regime` | — | Returns current market regime for `?symbol=&timeframe=`. |

### `backend/app/blueprints/sr_zones_bp.py`

| Item | Signature | Purpose |
|---|---|---|
| `GET /api/sr-zones` | — | Returns S/R zones for `?symbol=&timeframe=&detection_method=`. |
| `POST /api/sr-zones/refresh` | — | Triggers full S/R zone recomputation for `{symbol, timeframe}`. |
| `GET /api/sr-zones/smc` | — | Returns FVG and Order Block data alongside S/R zones. |

### `backend/app/blueprints/strategies_bp.py`

| Item | Signature | Purpose |
|---|---|---|
| `GET /api/strategies` | — | Lists all registered strategies with metadata and config state. |
| `PATCH /api/strategies/<name>` | — | Toggles enabled, updates `min_confidence`. Persists to DB. |

### `backend/app/blueprints/signals_bp.py`

| Item | Signature | Purpose |
|---|---|---|
| `POST /api/signals/sessions` | — | Starts an analysis session: `{symbol, strategy_names[]}`. Creates `AnalysisSession` DB record, calls `LiveScanner.start_session()`. |
| `DELETE /api/signals/sessions/<id>` | — | Stops a session. |
| `GET /api/signals/sessions` | — | Lists active and historical sessions. |
| `GET /api/signals/watching` | — | Returns filtered watching setups `?session_id=&status=`. |
| `GET /api/signals/confirmed` | — | Returns confirmed signals `?symbol=&limit=`. |
| `GET /api/signals/rejected` | — | Returns rejected signals. |
| `GET /api/signals/events` | — | **SSE endpoint**. Streams real-time events: `price_update`, `live_candle`, `candle_close`, `signal_detected`, `signal_confirmed`, `setup_rejected`, `signal_expired`, `outcome_hit`. |
| `POST /api/signals/confirm` | — | Manually confirm a watching setup (bypass LLM). |
| `POST /api/signals/reject` | — | Manually reject a watching setup. |

### `backend/app/blueprints/backtest_bp.py`

| Item | Signature | Purpose |
|---|---|---|
| `POST /api/backtest/run` | — | Executes a backtest: `{symbol, timeframes[], strategy_names[], start_date, end_date, initial_capital, risk_percent}`. Returns `BacktestRun` with summary metrics + `BacktestTrade` list. |
| `GET /api/backtest` | — | Returns backtest run history. |
| `GET /api/backtest/<id>` | — | Returns a specific backtest run with all trades. |
| `GET /api/backtest/<id>/export` | — | Exports backtest results as CSV. |

### `backend/app/blueprints/alerts_bp.py`

| Item | Signature | Purpose |
|---|---|---|
| `GET /api/alerts` | — | Lists all user-defined price alerts. |
| `POST /api/alerts` | — | Creates a new price alert: `{symbol, price, direction, type}`. |
| `PUT /api/alerts/<id>` | — | Updates an alert. |
| `DELETE /api/alerts/<id>` | — | Deletes an alert. |

---

## Core Business Logic

### `backend/app/core/base_strategy.py`

| Item | Signature | Purpose |
|---|---|---|
| `Candle` | Dataclass (frozen) | Immutable OHLCV bar. Properties: `body_size`, `range_size`, `upper_wick`, `lower_wick`, `is_bullish`, `is_bearish`. Factory methods: `from_db_row()`, `from_df_row()`. |
| `Indicators` | Dataclass | Snapshot of latest indicator values: `ema_9/21/50/100/200`, `rsi_14`, `macd_line/macd_signal/macd_hist`, `atr_14`, `volume_ma_20`. |
| `SetupSignal` | Dataclass | Signal result: `strategy_name`, `symbol`, `timeframe`, `direction`, `confidence`, `entry`, `sl`, `tp1`, `tp2`, `notes`, `gates_passed`, `gates_failed`, `regime`. |
| `BaseStrategy` | Abstract class | Base for all strategies. Defines the full strategy contract. |
| `BaseStrategy.pre_process()` | `@classmethod (df, symbol, timeframe) → DataFrame` | Loads only requested features onto the DataFrame. Always adds ADX, EMA 50/100/200, ATR regardless of `required_features`. Calls indicator/fvg/ob/sr/event modules. |
| `BaseStrategy.generate_signals()` | `@abstractmethod (df) → DataFrame` | Must add columns `signal` (0/1), `direction` (LONG/SHORT), `confidence` (0-1). |
| `BaseStrategy.calculate_sl()` | `(signal, df, signal_idx, atr) → float` | Computes structural stop loss: finds 5-bar swing high/low, +/- `sl_atr_mult` × ATR. |
| `BaseStrategy.calculate_tp()` | `(signal, df, signal_idx, atr) → (float, float)` | Computes risk-based take profits at `tp1_rr` and `tp2_rr` risk-reward multiples. |
| `BaseStrategy.should_confirm_with_llm()` | `(signal) → bool` | Whether this signal should be sent to LLM. Default `True`. |
| `BaseStrategy.evaluate_gate()` | `@staticmethod (condition, name, weight) → GateResult` | Evaluates a single gate condition, returns weight or failure. |
| `BaseStrategy.hard_gate()` | `(condition, name) → GateResult` | Must pass; weight=1. |
| `BaseStrategy.soft_gate()` | `(condition, name, weight) → GateResult` | Contributes confidence; weight varies. |

### `backend/app/core/strategy_loader.py`

| Item | Signature | Purpose |
|---|---|---|
| `StrategyRegistry` | Singleton class | Auto-discovers, instantiates, and manages all strategies. |
| `load_builtin_strategies()` | `() → None` | Scans `app/strategies/`, imports `.py` files, finds `BaseStrategy` subclasses, instantiates them. |
| `sync_with_db()` | `() → None` | Creates DB records for newly discovered strategies, loads persisted `enabled` and `min_confidence` state. |
| `get_all()` | `() → List[BaseStrategy]` | Returns all registered strategy instances. |
| `get_by_name()` | `(name) → BaseStrategy` | Returns strategy instance by name. |
| `set_enabled()` | `(name, bool) → None` | Toggles strategy on/off, persists to DB. |
| `set_min_confidence()` | `(name, float) → None` | Updates confidence threshold, persists to DB. |

### `backend/app/core/strategy_runner.py`

| Item | Signature | Purpose |
|---|---|---|
| `StrategyRunner` | Class | Orchestrates strategy execution. No DB access directly — takes DataFrames. |
| `run_single_scan()` | `(strategy, symbol, timeframe) → (SetupSignal, DataFrame)` | **Live mode**: Fetches finalized candles via `get_finalized_candles()`, runs `pre_process()` then `generate_signals()`, extracts last bar's signal. Returns `None` if no signal. |
| `scan_historical()` | `(strategies, symbol, timeframe, candle_df) → List[SetupSignal]` | **Backtest mode**: Iterates all strategies over the full DataFrame, extracts every row where `signal == 1`. Returns all SetupSignals with temporal integrity. |
| `_validate_regime()` | `(strategy, regime) → bool` | Checks if current regime is in the strategy's `allowed_regimes`. Returns `False` if not. |

### `backend/app/core/indicators.py`

All functions are **pure**: `pd.Series → pd.Series` or `pd.Series → dict of pd.Series`.

| Item | Signature | Purpose |
|---|---|---|
| `compute_ema()` | `(closes, period) → Series` | Exponential Moving Average. |
| `compute_rsi()` | `(closes, period=14) → Series` | Relative Strength Index using Wilder's smoothing. |
| `compute_macd()` | `(closes, fast=12, slow=26, signal=9) → dict` | MACD: `{macd_line, signal_line, histogram}`. |
| `compute_bollinger()` | `(closes, period=20, std_dev=2.0) → dict` | Bollinger Bands: `{upper, middle, lower, percent_b, bandwidth}`. |
| `compute_atr()` | `(highs, lows, closes, period=14) → Series` | Average True Range. |
| `compute_keltner()` | `(highs, lows, closes, period=20, atr_mult=2.0) → dict` | Keltner Channel: `{upper, middle, lower}`. |
| `compute_adx()` | `(highs, lows, closes, period=14) → Series` | Average Directional Index (0-100). Computes +DI/-DI first, then smooths. |
| `compute_volume_ma()` | `(volumes, period=20) → Series` | Simple moving average of volume. |

### `backend/app/core/indicator_service.py`

| Item | Signature | Purpose |
|---|---|---|
| `IndicatorService` | Class | Caching wrapper + API serialization. |
| `compute_ema/rsi/macd/...()` | `static (args...) → Series/dict` | Thin delegation to pure functions in `indicators.py`. |
| `compute_all()` | `(symbol, timeframe, include_series=False) → dict` | Fetches candles from DB, computes all 14 indicator series, caches by `(symbol, tf, last_open_time)`, returns latest values. |
| `invalidate_cache()` | `(symbol=None, timeframe=None) → None` | Clears specific cache entry or all entries. |
| `get_cached()` | `(symbol, timeframe) → dict` | Returns cached indicator values if still valid. |
| `_fetch_candles()` | `(symbol, timeframe) → DataFrame` | DB query with minimum candle guard (20 required, 400 ideal). |

### `backend/app/core/market_regime.py`

| Item | Signature | Purpose |
|---|---|---|
| `detect_market_regime()` | `(df) → DataFrame` | Adds columns: `regime` (TRENDING_UP/DOWN/RANGING/CHOPPY), `regime_strength` (0-1), `volatility_regime` (LOW/NORMAL/HIGH), `structural_bias` (BULLISH/BEARISH/NEUTRAL). |
| `_hysteresis_trend()` | `(df, current_regime) → Series` | Once trending, persists trend until EMA 100 crossed or ADX < 15. |
| `_volatility_regime()` | `(df, bb_bandwidth) → Series` | Classifies volatility using BB bandwidth percentile. |
| `is_trending()` | `(df) → bool` | Convenience: last row regime has "TRENDING" prefix. |
| `is_ranging()` | `(df) → bool` | Convenience: last row regime == "RANGING". |
| `get_trend_direction()` | `(df) → str` | Returns "UP" / "DOWN" / "NEUTRAL". |

### `backend/app/core/market_structure.py`

| Item | Signature | Purpose |
|---|---|---|
| `extract_fvg()` | `(df) → DataFrame` | Detects Fair Value Gaps: 3-candle sequences where candle[1]'s wicks don't overlap candle[0]'s or candle[2]'s range. Gaps are "mitigated" when price later trades through them. |
| `extract_order_blocks()` | `(df) → DataFrame` | Detects Order Blocks: last opposite-color candle before a strong directional move (4+ consecutive candles). Marks OB high/low range. |
| `is_fvg_active()` | `(df, idx) → bool` | Returns whether an FVG at index is still unmitigated. |

### `backend/app/core/sr_engine.py`

| Item | Signature | Purpose |
|---|---|---|
| `SREngine` | Class | Full S/R zone lifecycle — detection, merging, scoring, persistence. |
| `detect_swing_points()` | `(df, lookback=5) → DataFrame` | Finds local swing highs and lows using fractals. |
| `detect_round_numbers()` | `(symbol, current_price) → DataFrame` | Generates round-number levels: BTC $1000/$5000 steps, asset-specific. |
| `detect_prev_period_hl()` | `(df, period='day') → DataFrame` | Extracts previous day/week high/low from 1D candles data. |
| `detect_zones_df()` | `(df, symbol, timeframe) → DataFrame` | Runs full detection pipeline, appends `sr_active`, `sr_support_*`, `sr_resistance_*` columns with temporal masking. |
| `_merge_overlapping()` | `(zones, atr) → DataFrame` | Merges overlapping zones within 0.5 × ATR range. Iterates until stable. |
| `_score_zones()` | `(zones, timeframe) → DataFrame` | Scores each zone: `min(1.0, touch_count * 0.15 + timeframe_weight)`. |
| `_apply_temporal_mask()` | `(df, zones) → DataFrame` | Ensures zones only register after their formation candle index. |
| `refresh()` | `(symbol, timeframe=None) → None` | Full refresh: drop existing, detect all, merge, score, persist. |
| `update_swings()` | `(symbol, timeframe) → None` | Minor update: swing point detection on recent 50 candles only. |
| `get_near_price()` | `(symbol, price, range_pct=0.03) → DataFrame` | Returns zones within ±3% of a given price. |

### `backend/app/core/events.py`

| Item | Signature | Purpose |
|---|---|---|
| `detect_choch()` | `(df, swing_col) → DataFrame` | Change of Character: swing high broken UP → bullish CHoCH (reversal). Swing low broken DOWN → bearish CHoCH. |
| `detect_bos()` | `(df, swing_col) → DataFrame` | Break of Structure: higher high broken → bullish BOS (continuation). Lower low broken → bearish BOS. |
| `detect_volume_climax()` | `(df) → DataFrame` | Volume spike ≥ 2 × recent average volume. |
| `detect_liquidity_sweep()` | `(df) → DataFrame` | Wick beyond key level (previous swing high/low) but candle closes inside — traps breakout traders. |

### `backend/app/core/fractals.py`

| Item | Signature | Purpose |
|---|---|---|
| `detect_swing_highs()` | `(df, n=5) → Series (bool)` | True at local maxima (highest high in ±n candle window). |
| `detect_swing_lows()` | `(df, n=5) → Series (bool)` | True at local minima (lowest low in ±n candle window). |
| `find_swing_points_candles()` | `(candles, n=5) → (List[Candle], List[Candle])` | Candle-API version: detects swings from a list of `Candle` objects. |

### `backend/app/core/scanner.py`

| Item | Signature | Purpose |
|---|---|---|
| `LiveScanner` | Singleton class | Manages all live analysis sessions. |
| `start_session()` | `(session_id, symbol, strategy_names) → None` | Starts WebSocket for symbol across all required timeframes, backfills historical data, ensures S/R zones, begins listening to kline events. Max 10 sessions, no duplicate symbols. |
| `stop_session()` | `(session_id) → None` | Closes WebSocket for the session, expires all watching setups. |
| `stop_all()` | `() → None` | Closes all WebSockets, expires all watching setups across all sessions. |
| `get_active_sessions()` | `() → List` | Returns metadata for all active sessions. |
| `_on_candle_close()` | `(symbol, timeframe, candle) → None` | **The main loop**. Upserts candle, heals gaps, invalidates cache, refreshes S/R zones, computes indicators, fetches nearby zones, runs each strategy, creates watching setups on signals, pushes SSE events. |
| `_on_live_candle()` | `(symbol, timeframe, candle) → None` | Persists in-progress candle every ~5s. Checks for `run_on_live_candle` strategies every ~10s. |
| `_on_price_update()` | `(symbol, price, timestamp) → None` | Pushes SSE price event. Triggers OutcomeTracker and PriceAlertTracker checks. |
| `_backfill_historical_data()` | `(symbol, timeframe) → None` | If DB has < `CANDLE_WARMUP` rows, fetches ~480 candles from REST API. |
| `_detect_and_heal_gap()` | `(symbol, timeframe, open_time) → None` | Compares incoming candle timestamp against last stored candle. If gap > 500ms, backfills missing candles via REST. |
| `_run_strategies_on_close()` | `(symbol, timeframe) → None` | For each strategy in the session: runs `StrategyRunner.run_single_scan()`, handles signal creation. |
| `_run_live_tick_strategies()` | `(symbol, timeframe) → None` | Runs `run_on_live_candle=True` strategies on the latest in-progress candle. |

### `backend/app/core/watching.py`

| Item | Signature | Purpose |
|---|---|---|
| `WatchingManager` | Singleton class | Manages the WATCHING → CONFIRMED/REJECTED/EXPIRED lifecycle. |
| `create_or_update_setup()` | `(session_id, strategy_name, symbol, timeframe, signal) → WatchingSetup` | Creates or updates a watching setup. Deduplicates by `(session_id, strategy_name, symbol, timeframe, status=WATCHING)`. Updates confidence, notes, gates if already exists. |
| `tick_candle_close()` | `(session_id) → None` | Increments `candles_since_detected` on all WATCHING setups. Expires any that reach `expiry_candles` threshold. |
| `expire_all_for_session()` | `(session_id) → None` | Marks all WATCHING setups for a session as EXPIRED. |
| `confirm_setup()` | `(setup_id, data) → ConfirmedSignal` | Converts WATCHING → CONFIRMED. Creates `ConfirmedSignal` record. |
| `reject_setup()` | `(setup_id, reason) → RejectedSignal` | Converts WATCHING → REJECTED. Creates `RejectedSignal` record. |

### `backend/app/core/data_utils.py`

| Item | Signature | Purpose |
|---|---|---|
| `get_finalized_candles()` | `(symbol, timeframe, count=400) → DataFrame` | Fetches finalized (closed) candles from DB. Includes staleness guard — raises if newest candle is > 2 × timeframe old. |

### `backend/app/core/config.py`

| Item | Signature | Purpose |
|---|---|---|
| `CANDLE_WARMUP` | Constant `= 400` | Minimum candles for reliable indicator computation. |
| `SUPPORTED_SYMBOLS` | List `= ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT']` | Symbols available for analysis. |

### `backend/app/core/confluence.py`

| Item | Signature | Purpose |
|---|---|---|
| `check_htf_alignment()` | `(symbol, ltf_timeframe, direction) → bool` | Checks if the higher timeframe trend matches the lower timeframe signal direction. Uses EMA 100 slope and regime. |
| `check_sr_confluence()` | `(signal_entry, zones, direction) → bool` | Checks if the signal entry is at or near a confirmed S/R zone. |

---

## LLM Integration

### `backend/app/core/llm_client.py`

| Item | Signature | Purpose |
|---|---|---|
| `LLMClient` | Class | Builds prompts and sends to LLM provider. |
| `evaluate_signal()` | `(context_payload) → LLMVerdict` | Builds system prompt + structured user prompt, calls provider, parses JSON response into verdict. |
| `_build_system_prompt()` | `() → str` | Returns the role/framework instruction for the LLM. |
| `_build_user_prompt()` | `(context) → str` | Structures the 8-dimension context into a readable prompt. |
| `_parse_response()` | `(raw_text) → dict` | Extracts JSON from LLM output, validates against `LLMVerdictSchema`. |

### `backend/app/core/llm_context_builder.py`

| Item | Signature | Purpose |
|---|---|---|
| `LLMContextBuilder` | Class | Builds the structured context payload sent to the LLM. |
| `build_llm_context()` | `(signal, candles, htf_candles, market_data) → dict` | Assembles the full 8-dimensional context: (1) signal metadata, (2) risk metrics, (3) market structure, (4) indicators, (5) volume, (6) HTF context, (7) recent price action, (8) classified candlesticks. |
| `_describe_market_structure()` | `(df) → str` | Summarizes S/R zones, OB, FVG, BOS, CHoCH near current price. |
| `_describe_price_action()` | `(df) → str` | Narrates recent price action: last N candles, trend characterization. |
| `_classify_candlesticks()` | `(df) → str` | Classifies recent candles (doji, engulfing, hammer, shooting star, marubozu, etc.). |

### `backend/app/core/llm_queue.py`

| Item | Signature | Purpose |
|---|---|---|
| `LLMQueueManager` | Class | Background worker for async LLM evaluation. |
| `enqueue_signal()` | `(signal, setup_id) → None` | Adds a signal to the processing queue. |
| `_run_worker()` | `() → None` | Background thread: dequeues signals, fetches HTF data and market data, builds context, calls `LLMClient.evaluate_signal()`, handles verdict, retries on failure (max 3). |
| `_handle_verdict()` | `(setup_id, verdict) → None` | CONFIRM/MODIFY → calls `WatchingManager.confirm_setup()` + Telegram + SSE. REJECT → calls `reject_setup()` + Telegram + SSE. |

### `backend/app/core/llm_providers/factory.py`

| Item | Signature | Purpose |
|---|---|---|
| `get_llm_provider()` | `(provider_name) → BaseLLMProvider` | Factory: returns appropriate provider based on `LLM_PROVIDER` env var. Supports: `lm_studio`, `groq`, `openrouter`, `openai`, `vertex_ai`. |

### `backend/app/core/llm_providers/base.py`

| Item | Signature | Purpose |
|---|---|---|
| `BaseLLMProvider` | Abstract class | Interface for LLM providers. |
| `call()` | `@abstractmethod (system_prompt, user_prompt, max_tokens) → str` | Sends prompt, returns raw response text. |

### `backend/app/core/llm_providers/openai_compatible.py`

| Item | Signature | Purpose |
|---|---|---|
| `OpenAICompatibleProvider(BaseLLMProvider)` | Class | Generic OpenAI-compatible API client. Used by `lm_studio`, `groq`, `openrouter`, `openai` providers — just different `base_url` and `api_key`. |
| `call()` | `(system_prompt, user_prompt, max_tokens) → str` | POST to `/v1/chat/completions`, returns `choices[0].message.content`. |

### `backend/app/core/llm_providers/vertex_ai.py`

| Item | Signature | Purpose |
|---|---|---|
| `VertexAIProvider(BaseLLMProvider)` | Class | Google Vertex AI native client (uses `google-cloud-aiplatform`). |
| `call()` | `(system_prompt, user_prompt, max_tokens) → str` | Calls Gemini model via Vertex AI SDK, returns response text. Supports `thinking_level` parameter. |

---

## Telegram

### `backend/app/core/telegram_client.py`

| Item | Signature | Purpose |
|---|---|---|
| `TelegramClient` | Singleton class | Synchronous Telegram Bot API HTTP client. |
| `send_message()` | `(text, parse_mode='HTML') → bool` | Sends a message via `https://api.telegram.org/bot<TOKEN>/sendMessage`. |

### `backend/app/core/telegram_formatter.py`

| Item | Signature | Purpose |
|---|---|---|
| `format_watching_alert()` | `(signal, setup) → str` | Formats a "watching" detection alert with strategy name, symbol, TF, direction, entry, SL, TP, confidence, gates. |
| `format_confirmed_alert()` | `(signal, verdict) → str` | Formats a confirmed signal with LLM reasoning. |
| `format_rejected_alert()` | `(signal, verdict) → str` | Formats a rejected signal with LLM reason. |
| `format_outcome_alert()` | `(signal, outcome) → str` | Formats a TP/SL hit notification. |
| `format_price_alert()` | `(alert, current_price) → str` | Formats a price alert trigger notification. |

### `backend/app/core/telegram_queue.py`

| Item | Signature | Purpose |
|---|---|---|
| `TelegramDeliveryManager` | Class | Background worker for async Telegram message delivery. |
| `enqueue()` | `(message, priority='normal') → None` | Adds a message to the delivery queue. Rate-limited to 20 msgs/min to respect Telegram API limits. |
| `_run_worker()` | `() → None` | Background thread: dequeues messages, sends via `TelegramClient.send_message()`, retries on failure (max 3, exponential backoff). |

---

## Outcome & Alert Tracking

### `backend/app/core/outcome_tracker.py`

| Item | Signature | Purpose |
|---|---|---|
| `OutcomeTracker` | Singleton class | Tracks active signals against live prices. |
| `rebuild_cache()` | `() → None` | Loads all `ConfirmedSignal` records with `trade_outcome='ACTIVE'` into memory. Called at startup. |
| `check_price()` | `(symbol, price, timestamp) → None` | Checks current price against all cached signals' SL, TP1, TP2 levels. On hit: updates DB, dispatches Telegram, pushes SSE. |
| `add_to_cache()` | `(signal) → None` | Adds a newly confirmed signal to the in-memory cache. |
| `_expire_signals()` | `() → None` | Expires signals that exceed their time limit (favorable: tf_minutes × 24; unfavorable: tf_minutes × 8). |

### `backend/app/core/price_alert_tracker.py`

| Item | Signature | Purpose |
|---|---|---|
| `PriceAlertTracker` | Singleton class | Tracks user-defined price alerts against live prices. |
| `rebuild_cache()` | `() → None` | Loads all active `PriceAlert` records into memory. Called at startup. |
| `check_price()` | `(symbol, price, timestamp) → None` | Checks current price against all cached alerts. Tracks crossing state (WAS_ABOVE / WAS_BELOW). On trigger: dispatches Telegram, pushes SSE. Handles ONCE (deactivates after trigger) and EVERY_TIME alert types. |
| `add_alert()` | `(alert) → None` | Adds a new alert to the cache. |
| `remove_alert()` | `(alert_id) → None` | Removes an alert from the cache. |

---

## Scheduler

### `backend/app/core/scheduler.py`

| Item | Signature | Purpose |
|---|---|---|
| `init_scheduler()` | `(app) → None` | Registers APScheduler cron jobs: full S/R zone refresh every 4h at :01 UTC, minor swing update every 1h at :03 UTC. Starts the scheduler. |

---

## Data Utilities

### `backend/app/utils/binance.py`

| Item | Signature | Purpose |
|---|---|---|
| `fetch_klines()` | `(symbol, timeframe, start_ms=None, end_ms=None, limit=1000) → List[dict]` | Fetches historical klines from Binance Futures REST API. Auto-paginates. Returns dicts with `{symbol, timeframe, open_time, open, high, low, close, volume}`. |
| `BinanceStreamManager` | Class | WebSocket client for Binance Futures streams. |
| `__init__()` | `(callbacks) → None` | Accepts `on_price_update`, `on_live_candle`, `on_candle_close`, `on_reconnect` callbacks. |
| `start()` | `(symbol, timeframes) → None` | Opens WebSocket connection for combined stream across all timeframes. |
| `stop()` | `() → None` | Closes WebSocket connection. |
| `is_connected()` | `() → bool` | Returns connection state. |
| `_on_message()` | `(ws, raw_msg) → None` | Parses incoming WebSocket message, routes to kline or price callbacks based on stream name. |
| `_on_error()` | `(ws, error) → None` | Logs error, triggers reconnect with exponential backoff (1s→2s→...→60s, max 20 retries). |
| `_on_close()` | `(ws, close_status, close_msg) → None` | Triggers reconnect if not intentional close. |

### `backend/app/utils/csv_parser.py`

| Item | Signature | Purpose |
|---|---|---|
| `validate()` | `(filepath) → (bool, List[str])` | Validates CSV file: checks required columns (open_time, open, high, low, close, volume), validates data types, checks for chronological order. Returns (is_valid, errors). |
| `parse()` | `(filepath, symbol, timeframe) → List[dict]` | Parses a validated CSV file into candle dicts ready for DB upsert. |

### `backend/app/core/market_data.py`

| Item | Signature | Purpose |
|---|---|---|
| `fetch_funding_rate()` | `(symbol) → float` | Fetches current funding rate from Binance Futures premium index endpoint. |
| `fetch_oi_change()` | `(symbol) → float` | Fetches Open Interest % change over 5-minute period from Binance. |
| `get_trading_session()` | `() → str` | Returns current trading session based on UTC hour: Asian (0-7), London (7-12), NY (12-19), Transition (19-24). |

---

## Strategy Implementations

### `backend/app/strategies/trend_following.py`

| Item | Signature | Purpose |
|---|---|---|
| `TrendFollowing(BaseStrategy)` | Class | 1h strategy. Pullback entry in established trend. |
| `generate_signals()` | `(df) → DataFrame` | Gates: EMA 21 slope check (hard), EMA stack aligned (hard), price between EMA 9 and EMA 21 (soft), ADX ≥ 25 (hard), momentum move toward trend (soft), not at S/R zone (soft). |
| `get_gate_count()` | `() → int` | Returns 6 (total number of gates). |

### `backend/app/strategies/burner_9_20.py`

| Item | Signature | Purpose |
|---|---|---|
| `Burner920(BaseStrategy)` | Class | 1h strategy. Aggressive pullback to 9/20 EMA zone. |
| `generate_signals()` | `(df) → DataFrame` | Gates: price in 9-20 EMA zone (hard), 200 EMA macro filter (hard), EMA 20 slope aligned (soft), hidden divergence RSI vs price (soft), market trap detection — false breakout reversal (soft), volume confirmation (soft). |
| `get_gate_count()` | `() → int` | Returns 6. |

### `backend/app/strategies/breakout_retest.py`

| Item | Signature | Purpose |
|---|---|---|
| `BreakoutRetest(BaseStrategy)` | Class | 4h strategy. BOS/CHoCH breakout with successful retest. |
| `generate_signals()` | `(df) → DataFrame` | Gates: BOS or CHoCH event present (hard), price retests broken level (hard), rejection candle at retest (hard), volume decline on retest (soft), momentum shift post-retest (soft). |
| `get_gate_count()` | `() → int` | Returns 5. |

### `backend/app/strategies/liquidity_sweep.py`

| Item | Signature | Purpose |
|---|---|---|
| `LiquiditySweep(BaseStrategy)` | Class | 4h strategy. Stop hunt identification. |
| `generate_signals()` | `(df) → DataFrame` | Gates: wick beyond key swing level (hard), candle closes inside the range (hard), momentum shift in opposite direction (hard), volume above average (soft), HTF alignment check (soft). |
| `get_gate_count()` | `() → int` | Returns 5. |

### `backend/app/strategies/key_level_reversal.py`

| Item | Signature | Purpose |
|---|---|---|
| `KeyLevelReversal(BaseStrategy)` | Class | 15m strategy. Reversal at established S/R. |
| `generate_signals()` | `(df) → DataFrame` | Gates: at S/R zone (hard), zone touched ≥4 times (hard), engulfing candle ≥2× previous body (hard), RSI extreme <30 or >70 (soft), volume ≥2× average (soft), ADX weakening (soft). |
| `get_gate_count()` | `() → int` | Returns 6. |

### `backend/app/strategies/ema_cross_alert.py`

| Item | Signature | Purpose |
|---|---|---|
| `EMACrossAlert(BaseStrategy)` | Class | 30m/1h strategy. Imminent EMA 9/20 crossover alerts. |
| `generate_signals()` | `(df) → DataFrame` | Runs on live candle. Detects when EMA 9 and EMA 20 are converging and about to cross. Sends direct Telegram alert (bypasses Watching/Confirmed pipeline). `run_on_live_candle=True`. |
| `get_gate_count()` | `() → int` | Returns 3. |

---

## Backtest Engine

### `backend/app/core/backtest_engine.py`

| Item | Signature | Purpose |
|---|---|---|
| `BacktestEngine` | Class | Simulates trades over historical data. |
| `run()` | `(strategies, symbol, timeframes, candles, initial_capital, risk_percent) → BacktestRun` | Main entry point. Iterates through candles chronologically, runs `StrategyRunner.scan_historical()` for signals, simulates entries/exits with SL/TP logic, tracks equity curve, computes metrics. |
| `_simulate_trade()` | `(signal, df, signal_idx) → BacktestTrade` | Simulates a single trade from entry candle forward: walks through subsequent candles checking SL, TP1, TP2 hit order. |
| `_compute_metrics()` | `(trades, equity_curve) → dict` | Computes: total trades, win rate, avg win/loss, max drawdown, Sharpe ratio, profit factor, expectancy, CAGR. |
| `_export_csv()` | `(run) → str` | Exports backtest results as CSV string. |

---

## Models (Database)

### `backend/app/models/db.py`

All are SQLAlchemy `db.Model` subclasses. Column comments below are conceptual — actual columns are defined by declarative attributes.

| Model | Table | Purpose |
|---|---|---|
| `CandleModel` | `candles` | OHLCV. Composite PK `(symbol, timeframe, open_time)`. |
| `SRZoneModel` | `sr_zones` | S/R zones with detection method, price level, strength, upper/lower bounds. |
| `StrategyModel` | `strategies` | Strategy metadata: name, enabled, min_confidence. |
| `WatchingSetup` | `watching_setups` | Watching signals: status (WATCHING/CONFIRMED/REJECTED/EXPIRED), candles_since_detected, expiry_candles, notes, gates_passed/failed. |
| `AnalysisSession` | `analysis_sessions` | Session records: symbol, strategy_names (JSON), status, started_at, ended_at. |
| `ConfirmedSignal` | `confirmed_signals` | LLM-approved signals: entry, sl, tp1, tp2, llm_verdict (JSON), trade_outcome (ACTIVE/HIT_TP1/HIT_TP2/HIT_SL/EXPIRED). |
| `RejectedSignal` | `rejected_signals` | LLM-rejected signals: rejection_reason, llm_verdict (JSON). |
| `BacktestRun` | `backtest_runs` | Backtest metadata: symbol, timeframes, strategies, config, summary metrics, equity_curve (JSON). |
| `BacktestTrade` | `backtest_trades` | Individual trades in a backtest: entry, exit, pnl, pnl_pct, exit_reason, bars_held. FK to `backtest_runs`. |
| `PriceAlert` | `price_alerts` | User-defined alerts: price, direction (ABOVE/BELOW), alert_type (ONCE/EVERY_TIME), is_active, crossing_state. |
| `LLMPromptLog` | `llm_prompt_logs` | Full LLM interaction: system_prompt, user_prompt, response, verdict (JSON), provider, model, latency_ms. |

---

## Context Serialization

### `backend/app/core/context_serializer.py`

| Item | Signature | Purpose |
|---|---|---|
| `serialize_context()` | `(signal, candles, htf_candles, market_data) → dict` | Converts the current signal context into a JSON-serializable dict for storage in `ConfirmedSignal.context_data`. |

---

## SSE (Server-Sent Events)

### `backend/app/core/sse.py`

| Item | Signature | Purpose |
|---|---|---|
| `SSEManager` | Class | Publish/subscribe manager for SSE events. |
| `subscribe()` | `(channel=None) → queue.Queue` | Returns a queue that will receive events. If `channel` is `None`, receives all events (broadcast). |
| `unsubscribe()` | `(queue) → None` | Removes a subscriber queue. |
| `publish()` | `(event_type, data, channel=None) → None` | Pushes an event to subscriber queues. `channel=None` broadcasts to all. |
| `generate()` | `(queue) → Generator` | Flask-SSE compatible generator: yields formatted SSE messages from the queue. |

---

## Frontend

### `frontend/src/App.tsx`

| Item | Purpose |
|---|---|
| `App` | React Router v6 with layout: Header, Navigation (7 pages: SignalFeed, Charts, Backtest, BacktestAnalyzer, HistoricalData, LLMPrompts, PriceAlerts). |

### `frontend/src/api/client.ts`

| Item | Purpose |
|---|---|
| Axios-based API client | All backend API calls as async functions. TypeScript interfaces for all request/response types: `AnalysisSession`, `WatchingSetup`, `ConfirmedSignal`, `RejectedSignal`, `BacktestConfig`, `BacktestResult`, `BacktestTrade`, `PriceAlert`, `Candle`, `IndicatorData`, `SRZone`, `StrategyInfo`, `LLMPromptLog`. |

### `frontend/src/hooks/useSSE.ts`

| Item | Purpose |
|---|---|
| `useSSE()` | Hook managing EventSource connection to `/api/signals/events`. Auto-reconnects on close. Returns `{ events, connected }`. |

### `frontend/src/hooks/useAnalysisSessions.ts`

| Item | Purpose |
|---|---|
| `useAnalysisSessions()` | Hook for session CRUD: `startSession()`, `stopSession()`, `fetchSessions()`. Returns `{ sessions, activeSession, ... }`. |

### Pages

All pages are under `frontend/src/pages/`:

| Page | Purpose |
|---|---|
| `SignalFeed/` | Main dashboard: session controls, watching/confirmed/rejected card feeds, SSE integration. |
| `Charts/` | Lightweight-charts candlestick chart with indicator overlays. |
| `Backtest/` | Backtest configuration form + results table. |
| `BacktestAnalyser/` | Per-trade drill-down, equity curve visualization, metrics dashboard. |
| `HistoricalData/` | Binance data import form + CSV upload. |
| `LLMPrompts/` | LLM interaction log table with prompt/response expansion. |
| `PriceAlerts/` | Alert CRUD table with status indicators. |

### Components

All components are under `frontend/src/components/`:

| Component | Purpose |
|---|---|
| `WatchingCard/` | Displays a WATCHING setup: strategy, entry, SL/TP, confidence bars, gates breakdown, confirm/reject buttons. |
| `ConfirmedCard/` | Displays a confirmed signal: LLM verdict, risk metrics, outcome status. |
| `RejectedCard/` | Displays a rejected signal: rejection reason, verdict summary. |

### Types

All types are under `frontend/src/types/`:

| File | Purpose |
|---|---|
| `signals.ts` | `AnalysisSession`, `WatchingSetup`, `ConfirmedSignal`, `RejectedSignal`, `SSEEvent`, etc. |
| `backtest.ts` | `BacktestConfig`, `BacktestResult`, `BacktestTrade`, `BacktestMetrics`. |
| `backtestFile.ts` | Export file types. |
| `alerts.ts` | `PriceAlert`, `AlertType`, `AlertDirection`. |
