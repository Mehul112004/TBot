# TBot — crypto trade-signal intelligence

TBot is a personal signal-intelligence system for Binance USDT perpetual markets. It does **not** execute trades or connect to an exchange account. It consumes market data, finds rule-based candidate setups, asks an LLM to validate eligible setups, and delivers the resulting lifecycle to a React dashboard and Telegram.

The current implementation is a Flask/PostgreSQL backend with background workers and a Vite/React frontend.

## What happens to a live signal

```text
Binance REST + WebSocket
        │
        ▼
PostgreSQL candles ──► indicators / S-R zones ──► strategy scan on closed candle
                                                        │
                                             WatchingSetup + dashboard/SSE + Telegram
                                                        │
                                           LLM queue (eligible strategies only)
                                                        │
                                      CONFIRM / MODIFY / REJECT persisted and announced
                                                        │
                                    active confirmed signal tracked against live prices
```

`EMA Cross Alert` is deliberately different: it evaluates live candles and sends its own Telegram alert. It does not create a watching setup or enter the LLM confirmation flow.

## Repository guide

| Path | Role |
| --- | --- |
| `backend/app/` | Flask app, models, API blueprints, live scanner, strategy/LLM/Telegram services |
| `backend/app/strategies/` | The six currently discovered built-in strategies |
| `backend/app/strategies/archive/` | Historical strategies and the legacy SMC extraction code; not auto-discovered as live strategies |
| `backend/tests/` | Unit and integration-style coverage for indicators, data, S/R, strategy contracts, live sessions, LLM, notifications, and backtesting |
| `frontend/src/` | React dashboard: data import, charts, signal feed, backtesting, prompt log, price alerts |
| `backtests/` | Dated JSON outputs from previous research runs; snapshots, not application configuration |
| `docs/` | Current system docs plus clearly labelled implementation history and future designs |

Start with the [documentation index](docs/README.md). It separates current references from historical plans so that a future change starts from the correct model of the system.

## Local development

Prerequisites: Python 3.10+, Node.js, npm, Docker, PostgreSQL (the supplied Compose file starts it), and network access to Binance for imports/live market data. An LLM provider and Telegram are optional for working on the non-notification parts of the product.

1. Start PostgreSQL from the repository root:

   ```bash
   docker compose up -d
   ```

2. Configure `backend/.env`. Use [backend/app.yaml.example](backend/app.yaml.example) as a deployment-oriented list of variables. Keep provider credentials and Telegram values outside version control.

3. Install backend dependencies and run the API:

   ```bash
   cd backend
   pip install -r requirements.txt
   python run.py
   ```

   The development server listens on `http://localhost:5001` by default. The app creates its tables and starts background services outside test mode.

4. In another terminal, start the dashboard:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

   The frontend defaults to `http://localhost:5001/api`. Override it with `VITE_API_BASE_URL` when needed.

## Operating model

- Import history from Binance or CSV before running historical analysis. A new live session also backfills its required candle window in the background.
- A live session has one symbol, selected strategies, and selected timeframes. At most ten sessions can be active in one process.
- Candidate setups have a short candle-based watching lifetime. Eligible candidates are evaluated by the single LLM queue worker.
- Confirmed signals are watched until a target, stop, or expiry outcome. Price alerts are an independent feature.
- Runtime sessions and tracker caches are in process; their database records persist, but a backend restart does not recreate streams automatically.

## Current strategy set

| Strategy | Primary timeframe(s) | Delivery path |
| --- | --- | --- |
| Trend Following | 1h | watching setup → LLM → outcome tracking |
| Burner 9/20 | 1h | watching setup → LLM → outcome tracking |
| Breakout & Retest | 4h | watching setup → LLM → outcome tracking |
| Liquidity Sweep | 4h | watching setup → LLM → outcome tracking |
| Key Level Reversal | 15m | watching setup → LLM → outcome tracking |
| EMA Cross Alert | 30m, 1h | direct live-candle Telegram alert |

See [the strategy catalog](docs/strategy-catalog.md) for conditions, contracts, and archive status.

## Documentation and research notes

- [Architecture and runtime](docs/architecture.md)
- [Operations and iteration guide](docs/operations.md)
- [Strategy catalog](docs/strategy-catalog.md)
- [Backtesting model](docs/backtesting.md)
- [API reference](docs/logic/api_endpoints.md)

Historical phase documents, walkthroughs, confluence plans, and the SMC v2 design remain in the repository for provenance. They are not a statement that their proposed features are currently running; the documentation index calls out their status explicitly.

## Safety note

TBot produces informational trade signals for manual review. Backtest output is a historical research artifact, not a promise of future performance. Evaluate strategy changes with realistic costs and held-out/walk-forward data before relying on them operationally.
