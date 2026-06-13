# Indian Market Integration — Master Plan

This directory contains the complete implementation plan for adding Indian stock market trading (intraday equities + Nifty/Sensex/BankNifty options) alongside the existing crypto trading capabilities.

## Document Index

| Document | Description |
|---|---|
| [broker-comparison.md](broker-comparison.md) | Analysis of Upstox, ICICIdirect Breeze & Angel One Smart API |
| [database-changes.md](database-changes.md) | All schema migrations, new columns, new tables |
| [backend-architecture.md](backend-architecture.md) | Provider abstraction layer, scanner changes, API routes |
| [frontend-changes.md](frontend-changes.md) | Market toggle, UI adaptations, new components |
| [strategies.md](strategies.md) | Indian market intraday & options strategies |
| [implementation-phases.md](implementation-phases.md) | Phased rollout with timeline and milestones |
| [file-manifest.md](file-manifest.md) | Complete list of files to create and modify |

## Key Decision

**Broker**: Angel One Smart API — free, no static IP, Python SDK, widely used in Indian retail algo trading.

**Architecture**: Abstract market provider pattern — `BinanceProvider` and `AngelOneProvider` both implement `AbstractMarketProvider`, making the scanner market-agnostic.
