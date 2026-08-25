# Architecture and runtime model

**Reviewed against source on 2026-08-22.** This is the current implementation map for TBot.

## Purpose and boundaries

TBot is a manual-trading signal system. It watches Binance Futures market data, uses deterministic strategies to identify candidates, asks an LLM to approve, reject, or adjust eligible candidates, and publishes the lifecycle to the web dashboard and Telegram. It does not submit orders or manage exchange positions.

The two decision layers have intentionally different roles:

| Layer | Responsibility | Output |
| --- | --- | --- |
| Algorithmic layer | Screens finalized market candles using strategy rules, indicators, regime, and calculated risk levels | A candidate `SetupSignal` / persisted `WatchingSetup` |
| LLM layer | Reviews a bounded context for an eligible candidate | `CONFIRM`, `REJECT`, or `MODIFY` with structured reasoning |

## Service topology

```text
                    ┌───────────────────┐
Binance REST ──────►│ Candle persistence │◄──── Binance WebSocket
                    │    PostgreSQL      │            │
                    └─────────┬─────────┘            │ price / live candle / close
                              │                      ▼
                    ┌─────────▼────────────────────────────┐
                    │ Flask process                         │
                    │                                      │
                    │  LiveScanner ──► StrategyRunner       │
                    │       │                 │             │
                    │       │           WatchingManager     │
                    │       │                 │             │
                    │       │           LLMQueueManager     │
                    │       │                 │             │
                    │       └──────► OutcomeTracker         │
                    │                                      │
                    │  SREngine / IndicatorService          │
                    │  TelegramDeliveryManager              │
                    │  PriceAlertTracker / Scheduler        │
                    └───────────┬────────────────────┬──────┘
                                │ REST + SSE          │ Telegram Bot API
                                ▼                     ▼
                         React dashboard         Telegram chat
```

`backend/app/__init__.py` is the composition root. Outside test mode it initialises the database schema, synchronises the strategy registry, registers eight API blueprints, and starts the scanner-adjacent background services.

## Live signal lifecycle

1. The user creates a session through `POST /api/signals/sessions`, choosing one symbol, strategies, and timeframes. `LiveScanner` permits up to ten active sessions and rejects a duplicate live symbol.
2. The scanner records the session, backfills at least 400 candles for its required streams, derives or refreshes S/R zones, and starts a Binance combined stream.
3. On a **closed** candle, the scanner upserts the candle, fills detected temporal gaps from REST, invalidates cached indicators, refreshes applicable zones, and runs strategies selected for that timeframe.
4. `StrategyRunner` preprocesses finalized candle data and turns the last detected strategy row into a `SetupSignal` with entry, stop, targets, direction, confidence, and notes.
5. `WatchingManager` de-duplicates by session/strategy/symbol/timeframe, writes a `WatchingSetup`, publishes an SSE event, and queues a Telegram watching notification. Its normal expiry is candle-based (`SIGNAL_EXPIRY_CANDLES`, default three).
6. A strategy that opts into LLM confirmation is placed on the single `LLMQueueManager` worker. The worker adds current market/HTF context, calls the configured provider, stores the prompt log, and persists one outcome:
   - `CONFIRM` creates a `ConfirmedSignal` with the proposed levels.
   - `MODIFY` creates a `ConfirmedSignal` using LLM-adjusted levels.
   - `REJECT` creates a `RejectedSignal`.
7. A confirmed signal is queued for Telegram and loaded by `OutcomeTracker`. Subsequent live prices can mark its first terminal state: `HIT_TP1`, `HIT_TP2`, `HIT_SL`, or `EXPIRED`, then generate a Telegram/SSE outcome update.

The `EMA Cross Alert` strategy is not a candidate-to-LLM workflow. It is explicitly run from the live-candle path and sends a direct Telegram alert after its own cooldown check.

## Data and analysis pipeline

### Candles

- Historical candles arrive through the Binance REST import endpoint or CSV upload. Live sessions warm themselves from REST and then consume Binance Futures WebSocket updates.
- `Candle` records are keyed by `(symbol, timeframe, open_time)` and retain whether a bar is closed.
- `app/utils/data_utils.py` is the common finalized-candle boundary. Strategy and indicator work should use finalized bars rather than an in-progress bar unless a feature explicitly belongs to the live-candle path.
- `IndicatorService` computes a cached DataFrame of EMA 9/21/50/100/200, RSI, MACD, Bollinger/Keltner Bands, ATR, ADX, volume MA, and regime information from a warmup window.

### Levels

`SREngine` finds swing and psychological support/resistance zones, assigns ATR-sized bands, merges nearby levels, and scores strength from post-formation touches, timeframe, and recency. Zones are persisted. The periodic scheduler refreshes full higher-timeframe and minor lower-timeframe windows; a session's close handler also triggers appropriate refreshes.

The chart additionally requests calculated standard/Camarilla pivots. Pivots are derived from the prior completed daily/weekly candle and are not stored as S/R-zone rows.

The `/api/sr-zones/smc-zones` chart overlay uses the archived `app/strategies/archive/smc_v1/` extraction helpers. The separate `app/core/smc/` v2 package currently exposes its parameter registry but its context/engine public APIs are stubs; see the status note in [the documentation index](README.md).

## LLM decision model

`LLMClient` asks for schema-validated JSON rather than free-form advice. Its decision dimensions cover trend, momentum, structure, volume, price action, risk/reward, key-level context, and counter-signals. Parsed responses are stored in `LLMPromptLog` and converted into the persisted confirmation/rejection models described above.

Provider selection is configuration-driven:

- `lm_studio`: local OpenAI-compatible chat endpoint (the default).
- `vertex_ai`: Google Vertex AI through the `google-genai` client.
- `groq`, `openrouter`, or `openai`: OpenAI-compatible cloud endpoints.

The prompt context builder includes the candidate metadata/risk, price action, technical indicators, volume, higher-timeframe summary, and current Binance funding/open-interest/session data when available. See [LLM providers](logic/llm_providers.md) for the configuration surface.

## State ownership and persistence

| State | Primary owner | Persists across process restart? |
| --- | --- | --- |
| Candles, S/R zones, strategy preferences | PostgreSQL | Yes |
| Session records | PostgreSQL | Yes as records; streams are not re-created automatically |
| Active `AnalysisSession` objects and WebSocket streams | `LiveScanner` memory | No |
| Watching/confirmed/rejected signals, LLM logs, price alerts, backtest runs/trades, sealed research experiments/folds/outcomes | PostgreSQL | Yes |
| Indicator cache, SSE client queues, LLM/Telegram work queues | Process memory | No |
| Outcome and price-alert tracker indexes | Rebuilt from stored active records at startup | Yes, after cache rebuild |

This distinction matters when operating the service: stopping or restarting the backend ends live subscriptions; recreate sessions to resume live analysis.

## API and frontend integration

The backend exposes:

- REST under `/api/data`, `/api/indicators`, `/api/sr-zones`, `/api/strategies`, `/api/signals`, `/api/backtest`, `/api/research`, and `/api/alerts`.
- Server-Sent Events from `GET /api/signals/stream`.

The React app uses `frontend/src/api/client.ts` as its REST boundary and `frontend/src/hooks/useSSE.ts` for the live feed connection. Its primary routes are data import, signal feed, charts, server-side backtests, walk-forward validation, local JSON backtest comparison, LLM logs, and price alerts. The exact REST/SSE contract is maintained in [API reference](logic/api_endpoints.md).

## Source map for changes

| If you are changing… | Primary files/directories |
| --- | --- |
| App start-up, service composition, DB initialisation | `backend/app/__init__.py`, `backend/config.py`, `backend/run.py` |
| Data imports or Binance streams | `backend/app/blueprints/data.py`, `backend/app/utils/binance.py`, `backend/app/utils/csv_parser.py` |
| Candles/indicators/regime/S-R/pivots | `backend/app/core/indicators.py`, `regime.py`, `sr_engine.py`, `pivot_engine.py`, `utils/data_utils.py` |
| Live scan/session lifecycle | `backend/app/core/scanner.py`, `strategy_runner.py`, `watching_manager.py`, `sse_manager.py` |
| A built-in strategy | `backend/app/strategies/*.py`, `backend/app/core/base_strategy.py`, `strategy_loader.py` |
| LLM context/provider/queue | `backend/app/core/llm_context_builder.py`, `llm_client.py`, `llm_providers.py`, `llm_queue.py` |
| Telegram/price-outcome delivery | `telegram.py`, `telegram_delivery.py`, `outcome_tracker.py`, `price_alert_tracker.py` |
| Schema or persisted result shape | `backend/app/models/db.py` and corresponding blueprint/core manager |
| Walk-forward folds, candidate outcomes, and research gates | `backend/app/research/`, `backend/app/blueprints/research_bp.py`, `backend/scripts/run_walk_forward.py` |
| Dashboard/API consumption | `frontend/src/lib/api.ts`, page/component/hook that owns the surface |

## Test and artifact map

`backend/tests/` covers indicator math, S/R and pivot behavior, Binance parsing/stream behaviour, scanner/session lifecycle, strategy loading/running, watching setup management, LLM parsing, SSE, backtesting, and legacy extractor scenarios. The `backtests/` tree contains dated JSON artifacts from earlier research runs; they are not test fixtures or live configuration. Use [Backtesting model](backtesting.md) before generating or comparing new research outputs.
