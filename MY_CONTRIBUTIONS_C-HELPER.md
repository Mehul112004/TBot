# TBot — implementation summary

## What it is

TBot is a personal crypto trade-signal intelligence platform for Binance USDT perpetual markets. It identifies deterministic candidate setups, optionally validates them through a structured LLM review, and delivers the lifecycle to a React dashboard and Telegram. It does not execute trades or manage exchange accounts.

## Current implementation

- **Backend:** Python/Flask, SQLAlchemy/PostgreSQL, background scanner/queue workers, pandas/numpy/scipy, APScheduler, and Binance Futures REST/WebSocket connectivity.
- **Frontend:** React 19, Vite, TypeScript, Lightweight Charts, Axios, and Server-Sent Events.
- **Signal lifecycle:** closed-candle strategy candidate → persisted watching setup → optional LLM `CONFIRM`/`MODIFY`/`REJECT` → Telegram/dashboard notification → live-price outcome tracking.
- **Live strategy registry:** Trend Following, Burner 9/20, Breakout & Retest, Liquidity Sweep, Key Level Reversal, and the direct-alert EMA Cross Alert.
- **Analysis:** EMA/RSI/MACD/Bollinger/Keltner/ATR/ADX/volume calculations, market regime/exhaustion logic, persisted S/R zones, pivot overlays, and chart-only legacy SMC overlays.
- **Research:** server-side historical backtesting with next-bar-open entries, position/risk sizing, configured slippage, exit/outcome simulation, persisted metrics/equity/trades, plus dated JSON research artifacts.
- **Delivery:** SSE for the dashboard, queued Telegram watching/confirmation/rejection/outcome/price-alert messages, and configured local or cloud LLM providers.

## Design characteristics

- Single Flask process with in-memory live-session and queue state backed by persisted market/signal records.
- Binance data gap detection/backfill for live sessions and an explicit finalized-candle boundary for normal strategies.
- Rule-based strategy layer is separate from LLM judgement; the LLM does not continuously scan the market.
- No exchange trading credentials or order-placement workflow are part of the application.

## Documentation

The maintained project references are in [docs/README.md](docs/README.md), especially [architecture](docs/architecture.md), [strategy catalog](docs/strategy-catalog.md), and [backtesting model](docs/backtesting.md). Historical phase plans and walkthroughs are retained for provenance and explicitly labelled in that index.
