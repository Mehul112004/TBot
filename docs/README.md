# TBot documentation index

**Reviewed against source on 2026-08-22.** The source under `backend/app/` and `frontend/src/` is authoritative when this documentation and implementation diverge.

## Start here — current system references

| Document | Use it for |
| --- | --- |
| [Architecture and runtime](architecture.md) | End-to-end signal lifecycle, processes, data ownership, repository map, SSE model |
| [Operations and iteration guide](operations.md) | Local setup, configuration categories, session operations, safe change paths |
| [Strategy catalog](strategy-catalog.md) | The live strategy set, strategy contract, LLM/direct-alert distinction, archive status |
| [Backtesting model](backtesting.md) | Simulation semantics, artifacts, scripts, and research workflow |
| [Signal quality roadmap](signal-quality-roadmap.md) | Proposed implementation plan for research validation, evidence snapshots, calibration, LLM guardrails, and manual-review feedback |
| [API reference](logic/api_endpoints.md) | Current Flask REST and SSE surface |
| [Data ingestion](logic/data_ingestion.md) | Binance/CSV data path and candle-finalization rules |
| [Indicators and regime](logic/indicators.md) | Current indicator and market-regime calculation surface |
| [Live analysis](logic/live_analysis.md) | Scanner, watching setup, confirmation, and outcome lifecycle |
| [LLM providers](logic/llm_providers.md) | Provider configuration and structured LLM decision model |
| [S/R engine](logic/sr_engine.md) and [Pivot points](logic/pivot_points.md) | Level calculation and chart overlays |

## Documentation status by directory

| Location | Status | How to use it |
| --- | --- | --- |
| `docs/` and `docs/logic/` | Current | Working reference for the implementation reviewed on the date above. |
| `docs/signal-quality-roadmap.md` | Proposed delivery roadmap | Implementation plan for the manual signal platform; it does not describe a live feature inventory. |
| `docs/knowledge_base/sr_zones_and_pivots.md` | Current explanatory guide | UI-oriented explanation of chart overlays; it complements the engine reference. |
| `docs/knowledge_base/overview.md`, `blueprint.md` | Redirects | Kept for old inbound links; point to the current references. |
| `docs/phases/`, `docs/walkthroughs/`, `docs/fixes/` | Historical implementation records | Useful provenance, but descriptions can reflect the state at the time they were written. |
| `docs/confluence_plans/` | Historical design plan | Documents an earlier restructuring proposal, not a live feature inventory. |
| `docs/SMC-Engine/` | Future SMC v2 design | `backend/app/core/smc/` currently contains a parameter registry plus unimplemented public stubs; the charts use the archived `smc_v1` extractor path. |
| `backtests/` | Research artifacts | Dated JSON run outputs. Read their embedded configuration and date before comparing them. |
| `graphify-out/` | Generated code graph | A dated generated snapshot, useful for navigation only; confirm behavior in source. |

## Keeping this documentation useful

When changing the system, update the relevant current document in the same change:

- New/changed REST or SSE payload: `logic/api_endpoints.md` and `architecture.md`.
- Strategy condition, timeframe, or delivery path: `strategy-catalog.md` and `logic/strategy_engine.md`.
- Scanner/LLM/Telegram lifecycle: `architecture.md`, `logic/live_analysis.md`, and `operations.md`.
- Backtest execution or performance schema: `backtesting.md`.
- Environment variable or deployment behavior: `operations.md` and the top-level `README.md`.

Do not silently promote a plan or historical result to the current docs. If work is proposed but not wired into the application, describe it as planned and link to its design material.
