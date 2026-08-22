# API reference

**Current Flask surface, reviewed 2026-08-22.** All routes below are rooted at `/api`. The React client is `frontend/src/lib/api.ts`; update it alongside any contract change.

## Data — `/api/data`

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/import/binance` | Fetch paginated Binance Futures klines for a symbol/timeframe/date interval and upsert them |
| `POST` | `/import/csv` | Validate/upload supported OHLCV CSV and upsert candles |
| `GET` | `/candles` | Query stored OHLCV by symbol, timeframe, limit/date bounds (limit capped at 5,000) |
| `GET` | `/datasets` | List stored symbol/timeframe combinations |
| `GET` | `/symbols` | List symbols from Binance, local storage, or both |

## Indicators — `/api/indicators`

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Retrieve current indicator/regime values, optionally including series, for a symbol/timeframe |
| `POST` | `/invalidate` | Drop cached indicator data for a symbol/timeframe so the next use recomputes it |

The active public timeframe set for indicator retrieval is `5m`, `15m`, `30m`, `1h`, `4h`, `1d`.

## Support/resistance and chart levels — `/api/sr-zones`

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Multi-timeframe persisted S/R zones; supports higher-timeframe depth, touch filtering, top-N, confluence, and optional round levels |
| `GET` | `/pivots` | Calculate standard, Camarilla, or both pivot sets from prior completed daily/weekly data |
| `POST` | `/refresh` | Refresh persisted zones for a symbol/timeframe selection |
| `GET` | `/smc-zones` | On-the-fly legacy SMC FVG/order-block/event overlay data for charts |

`/smc-zones` is under the S/R blueprint; it is not `/api/smc-zones` or the planned SMC v2 API.

## Strategies — `/api/strategies`

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | List discovered strategies and persisted settings |
| `GET` | `/<name>` | Fetch one strategy's metadata/settings |
| `POST` | `/<name>/toggle` | Change persisted enabled state |
| `POST` | `/<name>/confidence` | Change persisted minimum confidence |

## Signals and sessions — `/api/signals`

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/sessions` | List active in-memory live-analysis sessions |
| `POST` | `/sessions` | Start a session for one symbol with selected strategies/timeframes |
| `DELETE` | `/sessions/<session_id>` | Stop a session and expire its watching setups |
| `GET` | `/watching` | List watching candidates, optionally scoped by session |
| `GET` | `/watching/<setup_id>` | Fetch one watching setup |
| `GET` | `/confirmed` | List persisted confirmed signals, optionally scoped by session |
| `GET` | `/rejected` | List persisted rejected candidates, optionally scoped by session |
| `GET` | `/export/confirmed` | Export confirmed signal records as JSON |
| `GET` | `/lm-studio-status` | Legacy-named generic configured-provider availability/status check |
| `GET` | `/llm_logs` | Paginated persisted LLM prompt/response logs |
| `GET` | `/stream` | SSE connection for live signal/session/price events |

### SSE event families

The server emits event names including `session_started`, `session_stopped`, `setup_detected`, `setup_updated`, `setup_expired`, `setup_rejected`, `signal_confirmed`, `signal_outcome_update`, `price_update`, `live_candle`, `candle_close`, `price_alert_created`, `price_alert_cancelled`, and `price_alert_triggered`. Consumers should tolerate future event types and reconnect behaviour.

## Backtests — `/api/backtest`

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/run` | Run/persist a historical simulation with symbol, timeframe, date range, strategies, capital, risk, and optional slippage |
| `GET` | `/history` | List persisted runs |
| `GET` | `/<run_id>` | Retrieve one run and its details |
| `GET` | `/<run_id>/export` | Export a run in JSON form |

## Price alerts — `/api/alerts`

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | List price alerts |
| `POST` | `/` | Create an above/below price alert with once/every-time behaviour and optional note |
| `GET` | `/<alert_id>` | Retrieve one alert |
| `DELETE` | `/<alert_id>` | Cancel an alert |

## Contract discipline

The API carries mutable market and signal state. For any endpoint/event change, update the backend blueprint, `frontend/src/lib/api.ts`, the owning frontend feature, relevant tests, and [architecture](../architecture.md). Keep sensitive configuration out of payload examples and documentation.
