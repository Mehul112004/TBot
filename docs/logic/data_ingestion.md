# Data ingestion and candle lifecycle

TBot operates on Binance USDT perpetual OHLCV stored in PostgreSQL. Historical data can be imported from Binance REST or a CSV; active live sessions warm themselves from REST and continue on the Binance WebSocket.

## Sources

| Source | Entry point | Behaviour |
| --- | --- | --- |
| Binance REST | `POST /api/data/import/binance` and scanner backfill | Paginates futures klines and upserts by symbol/timeframe/open time |
| CSV | `POST /api/data/import/csv` | Normalises recognized headers, validates OHLCV, then upserts |
| Binance WebSocket | `BinanceStreamManager` created per live session | Emits live prices/candles and a distinct closed-candle callback |

`GET /api/data/candles` exposes stored data for charts/backtests. `GET /api/data/datasets` lists local coverage; `GET /api/data/symbols` can obtain the current Binance Futures universe as well as local symbols.

## Finalized-candle rule

The active strategy and indicator path is designed around finalized bars. `app/utils/data_utils.py` filters in-progress candles according to timeframe duration and supports an as-of boundary. `LiveScanner` invokes its normal strategy loop on the closed-candle callback, not on each price update.

The scanner separately forwards in-progress candles to strategies that explicitly opt into `run_on_live_candle`; currently that distinction is used by `EMA Cross Alert`.

## Live-session data flow

1. Session start selects symbol/timeframes and starts a background warmup/top-up (at least the configured 400-candle window).
2. The combined Binance stream reports price updates and candle events.
3. A closed candle is persisted, temporal gaps are checked/fetched from REST, indicator cache is invalidated, and applicable S/R zones are refreshed before regular strategies run.
4. A reconnect triggers a background backfill/top-up so persisted history remains the basis for subsequent calculations.

Candles use the `(symbol, timeframe, open_time)` composite identity. The `is_closed` field distinguishes finalized database observations from an in-progress streamed bar.

## CSV expectations

The parser accepts Binance-shaped OHLCV exports and normalizes compatible headers. Required information is an open timestamp plus open, high, low, close, and volume. Timestamps can be epoch milliseconds or parseable datetimes. Validate a small import before relying on a large external file.

## Related files

- `backend/app/blueprints/data.py` — HTTP import/query handlers
- `backend/app/utils/binance.py` — REST pagination and combined WebSocket client
- `backend/app/utils/csv_parser.py` — header/data validation
- `backend/app/utils/data_utils.py` — finalized/as-of DataFrame boundaries
- `backend/app/models/db.py` — `Candle` persistence model
- `backend/scripts/verify_candle_data.py` — local-versus-Binance inspection/optional repair utility
