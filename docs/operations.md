# Operations and iteration guide

This guide is for running TBot locally and for finding the right boundary when improving it. It describes the current Flask process and React dashboard; it does not prescribe a production deployment architecture.

## Local services

| Service | Default | Role |
| --- | --- | --- |
| PostgreSQL 15 | `localhost:5432` via `docker-compose.yml` | Candles, zones, sessions, signals, prompt logs, alerts, backtests |
| Flask backend | `http://localhost:5001` in development | REST/SSE API and background workers |
| React/Vite frontend | Vite-selected development port | Browser dashboard |
| Binance Futures | External REST/WebSocket endpoints | Historical and live market data |
| LLM provider | Configuration-dependent | Candidate confirmation only |
| Telegram Bot API | Configuration-dependent | Signal and price-alert delivery |

`docker-compose.prod.yml` builds the backend image, while `backend/Dockerfile` runs Gunicorn on `$PORT` (default `8080`). The local development command is still `python backend/run.py` from the `backend` directory.

## First local run

```bash
# repository root
docker compose up -d

# terminal 1
cd backend
pip install -r requirements.txt
python run.py

# terminal 2
cd frontend
npm install
npm run dev
```

The first backend startup creates known SQLAlchemy tables and applies a small set of backwards-compatible column additions. The process starts its background services unless `TESTING=True`.

### Minimum configuration categories

Create `backend/.env` locally. Do not put access tokens, provider keys, or chat IDs in source-controlled documentation.

| Category | Variables used by the application |
| --- | --- |
| Database | `DATABASE_URL` |
| Flask | `SECRET_KEY`, `FLASK_ENV` |
| LLM selection | `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_MAX_TOKENS`, `LLM_TIMEOUT`, `LLM_TEMPERATURE` |
| Vertex AI option | `VERTEX_PROJECT_ID`, `VERTEX_LOCATION`, `VERTEX_MODEL`, `VERTEX_MAX_TOKENS`, `VERTEX_TEMPERATURE`, `VERTEX_THINKING_LEVEL` |
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Signal lifetime | `SIGNAL_EXPIRY_CANDLES` |

`backend/app.yaml.example` is a safe deployment-shaped example with placeholder values. The current default LLM provider is `lm_studio`; use `vertex_ai`, `groq`, `openrouter`, or `openai` only with the corresponding configured endpoint/credentials. See [LLM providers](logic/llm_providers.md) for the behaviour rather than copying values from a deployed config.

The browser client defaults to `http://localhost:5001/api`. Set `VITE_API_BASE_URL` before starting Vite when the backend has a different address.

## Daily operating workflow

1. Confirm that the data page lists the intended stored symbol/timeframe history. Import Binance data or upload CSV if it does not.
2. Start a Signal Feed analysis session. Choose one symbol and a compatible strategy/timeframe set; the backend performs its own warmup backfill before its stream settles into normal operation.
3. Watch candidate cards transition through `WATCHING`, then (for LLM-eligible strategies) `CONFIRMED` or `REJECTED`.
4. Treat a confirmation as an informational manual-trade setup. A confirmed record is tracked for first terminal target/stop/expiry outcome while the backend process is alive.
5. Stop the session when it is no longer needed. Stopping a session expires its watching setups and closes its stream.

### Process restart behaviour

The backend persists records but not live streams or `AnalysisSession` objects. After a restart, recreate the live sessions you want to scan. Persisted active confirmed signals and price alerts are reloaded into their tracker caches; SSE connections and queued in-flight work are process-local.

## Operational controls in the UI/API

| Need | UI/API owner |
| --- | --- |
| Add historical data | Historical Data page; `/api/data/import/binance` or `/api/data/import/csv` |
| Start/stop real-time analysis | Signal Feed; `/api/signals/sessions` |
| Tune discovered strategy enablement/confidence | Strategy API; `/api/strategies` |
| Inspect decisions | Signal Feed and `/api/signals/{watching,confirmed,rejected,llm_logs}` |
| Inspect raw LLM exchanges | LLM Prompts page; `/api/signals/llm_logs` |
| Refresh/query chart levels | Charts; `/api/indicators`, `/api/sr-zones`, pivot/legacy-SMC subroutes |
| Create/cancel price alert | Price Alerts; `/api/alerts` |
| Run/review a server-side backtest | Backtest page; `/api/backtest` |

## Iterating without losing the system model

Use a narrow change path and update its adjacent documentation/tests with the change.

| Change type | Start in | Also inspect/update |
| --- | --- | --- |
| New strategy or changed entry rule | `backend/app/strategies/`, `base_strategy.py` | `strategy-catalog.md`, strategy runner/backtest tests, backtest assumptions |
| Indicator or regime change | `core/indicators.py`, `core/regime.py` | Indicator tests, all strategy dependencies, current logic docs |
| S/R or pivot change | `core/sr_engine.py`, `core/pivot_engine.py` | S/R tests, chart overlays, current logic docs |
| LLM rubric or context change | `llm_client.py`, `llm_context_builder.py`, `llm_queue.py` | LLM tests, `llm_providers.md`, prompt log compatibility |
| Signal state/delivery change | Models, watching/queue/tracker, signals blueprint | SSE/Telegram consumers, Signal Feed, architecture and API docs |
| Backtest rule/cost change | `core/backtest_engine.py`, `backtest_bp.py` | Backtest docs, artifact schema, new controlled experiment output |
| Chart/API UI change | frontend route/component plus `src/lib/api.ts` | Backend contract and API docs |

## Useful scripts

Run these from `backend/` so imports resolve in the application context. Check command-line help before passing mutating flags.

| Script | Purpose |
| --- | --- |
| `scripts/run_comprehensive_backtest.py` | Sync selected Binance history and generate dated multi-run backtest JSON artifacts |
| `scripts/verify_candle_data.py` | Compare local candle coverage/data with Binance; its repair option changes local data |
| `run_ema_alert_backtest.py` | Historical experiment for the direct EMA alert idea |
| `scripts/manual_test_llm.py` | Manual LLM decision exercise |
| `scripts/queue_watching_setups.py` | Queue existing watching candidates for LLM processing |
| `test_telegram.py` | Manual Telegram delivery check |
| `clear_candles.py`, `fix_db.py` | Maintenance utilities; read and scope their target before executing |

The usual regression suite lives in `backend/tests/`. The repository also has root-level `test_db.py`; it is a standalone database connectivity check rather than the main pytest suite.

## Documents to keep in sync

- End-to-end state changes: [architecture](architecture.md)
- Strategy semantics and direct-alert differences: [strategy catalog](strategy-catalog.md)
- Simulation/record layout: [backtesting](backtesting.md)
- Endpoint/event contract: [API reference](logic/api_endpoints.md)
- Source-of-truth and historical-plan status: [documentation index](README.md)
