# Indicators and market regime

`IndicatorService` builds a cached analysis DataFrame from the latest finalized candles for a `(symbol, timeframe)` pair. It uses a warmup target of 400 candles (`CANDLE_WARMUP`) and caches by the latest candle timestamp until invalidated.

## Computed surface

| Family | Current calculations |
| --- | --- |
| Trend | EMA 9, 21, 50, 100, 200 |
| Momentum | RSI (Wilder), MACD line/signal/histogram |
| Volatility | Bollinger Bands, Keltner Channels, ATR |
| Trend strength | ADX |
| Volume | Volume moving average / relative-volume inputs |
| Regime | Directional trend/ranging/choppy classification, strength, volatility, structural bias, trend-exhaustion state |

The pure indicator calculations are in `backend/app/core/indicators.py`; service caching/assembly is in `backend/app/core/indicator_service.py`; regime logic is in `backend/app/core/regime.py`.

## Regime model

The regime detector uses EMA ordering/price position and ADX thresholds to distinguish trending up/down from non-trending states, with hysteresis around later EMA/ADX conditions. It also derives a volatility descriptor from Bollinger-band percentile behaviour and records trend-exhaustion evidence such as RSI, ADX, fast-EMA, MACD, and volume changes.

Strategies decide how to consume these fields. The scanner invalidates the relevant indicator cache after a closed candle is persisted; it does not independently make a trade decision from the regime service.

## API

`GET /api/indicators?symbol=...&timeframe=...` returns the current indicator package. It can return series data for chart consumers. `POST /api/indicators/invalidate` clears an entry so it recomputes on next use. Current allowed API timeframes are `5m`, `15m`, `30m`, `1h`, `4h`, and `1d`.

## Change notes

An indicator or regime change affects both live scanning and historical strategy preprocessing. Update focused tests, audit each strategy feature dependency, and document the resulting semantic change in the strategy/backtest references.
