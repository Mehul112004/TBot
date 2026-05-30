# Crypto Signal Intelligence Platform (C_helper)

## What it is
A personal, local crypto signal intelligence tool that watches BTC, ETH, SOL, and XRP across multiple timeframes, identifies high-quality trade setups using advanced technical analysis and pattern recognition, and delivers LLM-confirmed signals to a web UI and Telegram. No automated trading — this is an analyst, not a bot.

## My Role
Sole developer — designed and built the entire platform end-to-end from scratch, including architecture, backend, frontend, strategy engine, LLM integration pipeline, real-time WebSocket infrastructure, backtesting engine, and Telegram notification system.

## Timeline
Apr 2026 – May 2026 (6 weeks)

## Tech Stack
- **Backend:** Python 3.10, Flask (REST API + SSE streaming), SQLAlchemy, PostgreSQL + TimescaleDB, APScheduler, pandas, numpy, websocket-client
- **Frontend:** React 19, Vite 8, TypeScript 6, Tailwind CSS v4, Lightweight Charts (TradingView library), Lucide React, react-router-dom v7, axios, date-fns
- **Market Data:** Binance Futures REST API + WebSocket streams (primary data source)
- **LLM:** LM Studio (local, OpenAI-compatible) + OpenRouter (cloud fallback) — pluggable provider system with pydantic-validated verdict schema
- **Notifications:** Telegram Bot API (async delivery with retry queue)
- **Infrastructure:** Docker Compose (PostgreSQL + TimescaleDB), fully local single-user architecture
- **Dev Tools:** ESLint, PostCSS, Autoprefixer, 14+ test files

## Key Features / What I built
- **9-Phase Build Pipeline** — Architected and executed a structured roadmap spanning data ingestion, indicators, strategy engine, live scanning, LLM confirmation, Telegram notifications, backtesting, and charts.
- **Gate-Based Strategy Engine** — Designed an abstract `BaseStrategy` class with a gated confidence system (hard gates = must pass, soft gates = quality contributors). 6 active strategies: Trend Following, Breakout & Retest, Key Level Reversal, Liquidity Sweep, Burner 9/20, and EMA Cross Alert. Confidence = fraction of gates passed, giving transparent signal quality scoring.
- **Smart Money Concepts (SMC) Engine** — Built a 727-line S/R zone detection engine (swing highs/lows, round psychological numbers, previous day/week levels) with zone merging and strength scoring. Added a 565-line market structure engine detecting Fair Value Gaps (FVGs), Order Blocks (OBs), Change of Character (CHoCH), Break of Structure (BOS), Volume Climax, and Liquidity Sweeps with multi-zone tracking, forward-fill persistence, and mitigation kill-switches.
- **Multi-Timeframe Confluence System** — Validates lower-timeframe signals against higher-timeframe context (trend alignment, structural levels, market regime) to filter out low-quality setups.
- **Real-Time Live Scanner** — Singleton managing up to 10 concurrent analysis sessions with WebSocket streams, automatic gap detection and healing (detects missing candles, backfills via REST API), cold-start protection (pre-populates S/R zones before WebSocket connection), and reconnection handling with immediate gap backfill.
- **LLM Confirmation Pipeline** — Built a 6-dimension structured context builder (signal metadata, market structure, indicators, volume, HTF context, 20-candle price action) feeding an OpenAI-compatible LLM client. Pluggable provider system supports LM Studio (local) and OpenRouter (cloud). Verdicts are pydantic-validated (CONFIRM/REJECT/MODIFY with confidence_score 1–10). Full prompt/response logging to DB for audit.
- **Asynchronous Notification System** — SSE pub/sub for real-time frontend updates (setup_detected, price_update, candle_close, signal_confirmed, outcome events). Telegram async queue with retry for signal delivery and outcome follow-ups.
- **Full Backtesting Engine** (685 lines) — Simulates trades with realistic next-bar-open entry, cooldown between trades, same-bar conflict resolution (SL wins), and RR filtering. Computes total trades, win rate, PnL, Sharpe/Sortino ratios, max drawdown, profit factor, and equity curves. Results persisted to DB with CSV export.
- **Interactive Charting Dashboard** — Lightweight Charts integration with indicator overlays (EMA, Bollinger Bands, Keltner Channels), S/R zone visualization, FVG/OB display, and live candle streaming (~5s updates).
- **Historical Data Management** — Binance REST API and CSV import pipelines with validation, pagination, and cleanup utilities. Data stored in TimescaleDB hypertables for efficient time-series queries.
- **Signal Lifecycle Management** — Full pipeline from setup detection → watching (with configurable expiry) → LLM confirmation → signal publication → outcome tracking (TP1/TP2/SL hit monitoring with follow-up notifications to Telegram).

## Challenges / What I'm proud of
- **WebSocket Candle Gap Healing System** — One of the toughest problems solved: detecting missing data on server restart or WebSocket disconnection, automatically backfilling gaps via REST API, healing cold-start sessions by pre-populating S/R zones before connecting, and ensuring no stale or duplicate candles. Required careful state management across the scanner, indicator cache, and database layers.
- **LLM Hallucination Mitigation** — The LLM frequently produced invalid JSON or hallucinated trade levels. Solved by implementing Chain-of-Thought prompting, pydantic-validated structured output parsing, strict schema enforcement, and fallback logic when verdicts were malformed. Multiple iterations to get reliable, production-grade LLM outputs.
- **Strategy Architecture Refactoring** — Migrated from ad-hoc signal generation to a clean gate-based confidence system. Each strategy exposes exactly which gates passed/failed, giving full transparency on why a signal was generated or skipped. This made debugging, tuning, and backtesting dramatically easier.
- **Win Rate Optimization Sprint** — Systematically improved strategy performance across multiple commits: tuned cooldown methods, added Keltner Channels to Bollinger Bands strategy, implemented exhaustion filters, improved SMC liquidity sweep to 45% win rate at 2.3 RR, and achieved competitive EMA crossover win rate and RR through iterative backtesting.
- **Race Condition in Live Scanning** — Diagnosed and fixed a subtle race condition where WebSocket candle callbacks could overwrite in-progress indicator computations, causing inconsistent signal generation. Implemented thread-safe locking in the scanner's indicator caching layer.
- **Time Offset / Timezone Bugs** — Candle timestamps from Binance (UTC) vs. local DB storage vs. TimeScaleDB partitioning required careful handling. Fixed multiple issues where 1D/1d discrepancies and timezone offsets caused candles to be stored under wrong partitions or S/R zones to be calculated on misaligned candles.
- **Cold Start & Gap Healing Architecture** — Built a robust initialization sequence: on session start, backfill historical candles for indicator warmup, generate S/R zones on-demand, then connect WebSocket. On reconnect, detect the gap duration, backfill missing candles, recompute indicators, and resume scanning — all without manual intervention.

## Links
GitHub: private
Live / Demo: none (local-only application)
