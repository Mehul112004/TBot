# File Manifest — Complete List of Changes

## New Files (22)

### Backend — Providers (4)
| File | Description |
|---|---|
| `backend/app/providers/__init__.py` | Provider registry + `get_provider()` factory |
| `backend/app/providers/base.py` | `AbstractMarketProvider` ABC + `AbstractStreamManager` ABC |
| `backend/app/providers/binance_provider.py` | Binance provider (refactored from `utils/binance.py`) |
| `backend/app/providers/angelone_provider.py` | Angel One Smart API provider |

### Backend — Blueprints (1)
| File | Description |
|---|---|
| `backend/app/blueprints/market_bp.py` | Market status, instrument search, option chain endpoints |

### Backend — Strategies (3)
| File | Description |
|---|---|
| `backend/app/strategies/indian_orb.py` | Opening Range Breakout for Indian intraday |
| `backend/app/strategies/indian_vwap_reversal.py` | VWAP mean reversion strategy |
| `backend/app/strategies/indian_gap_fill.py` | Gap fill strategy (first 60 min) |

### Backend — Migrations (1)
| File | Description |
|---|---|
| `backend/migrations/add_market_type.sql` | Standalone SQL migration for reference |

### Frontend — Contexts (1)
| File | Description |
|---|---|
| `frontend/src/contexts/MarketContext.tsx` | Market type context provider with persistence |

### Frontend — Components (1)
| File | Description |
|---|---|
| `frontend/src/components/MarketBadge/MarketBadge.tsx` | Market type badge for signal cards |

### Docs (7 — this directory)
| File | Description |
|---|---|
| `docs/indian_market/README.md` | Master plan index |
| `docs/indian_market/broker-comparison.md` | Broker analysis |
| `docs/indian_market/database-changes.md` | Schema migration spec |
| `docs/indian_market/backend-architecture.md` | Backend design |
| `docs/indian_market/frontend-changes.md` | Frontend design |
| `docs/indian_market/strategies.md` | Trading strategies |
| `docs/indian_market/implementation-phases.md` | Phased rollout |

---

## Modified Files (22)

### Backend — Models (1)
| File | Changes |
|---|---|
| `backend/app/models/db.py` | Add `market_type` to all 9 models; add `IndianInstrument` model |

### Backend — Core (7)
| File | Changes |
|---|---|
| `backend/app/core/config.py` | Indian symbols, round numbers, market hours config |
| `backend/app/core/scanner.py` | `AnalysisSession.market_type`; market-aware `start_session()`; market hours gating in `_on_candle_close()`; provider-based stream creation |
| `backend/app/core/strategy_runner.py` | `run_single_scan()` gains `market_type` param |
| `backend/app/core/strategy_loader.py` | `BaseStrategy.allowed_market_types` support; market-filtered `get_strategies_for_market()` |
| `backend/app/core/base_strategy.py` | Add `allowed_market_types` class attribute |
| `backend/app/core/data_utils.py` | `get_finalized_candles()` gains `market_type` param |
| `backend/app/core/sr_engine.py` | Indian round number config; `market_type` awareness |

### Backend — Blueprints (2)
| File | Changes |
|---|---|
| `backend/app/blueprints/signals_bp.py` | All endpoints accept `market_type` filter |
| `backend/app/blueprints/data.py` | New `POST /import/angelone`; `GET /candles` includes market_type |

### Backend — Utils (1)
| File | Changes |
|---|---|
| `backend/app/utils/binance.py` | Re-export from `providers/binance_provider.py` (backward compat) |

### Backend — App (1)
| File | Changes |
|---|---|
| `backend/app/__init__.py` | Register `market_bp`; init Angel One provider; market_type ALTER migrations |

### Backend — Config (1)
| File | Changes |
|---|---|
| `backend/requirements.txt` | Add `smartapi-python`, `pyotp` |

### Frontend — Pages (5)
| File | Changes |
|---|---|
| `frontend/src/App.tsx` | Market toggle in sidebar; market-aware title; `MarketStatusBadge` |
| `frontend/src/main.tsx` | Wrap app in `MarketProvider` |
| `frontend/src/pages/SignalFeed/SignalFeed.tsx` | Market-aware: API calls, SSE filtering, Quick Start |
| `frontend/src/pages/SignalFeed/SessionPanel.tsx` | Market-aware: symbol/timeframe selectors; market_type in startSession |
| `frontend/src/pages/HistoricalData/HistoricalData.tsx` | Indian market import tab |

### Frontend — Components (2)
| File | Changes |
|---|---|
| `frontend/src/components/WatchingCard/WatchingCard.tsx` | MarketBadge |
| `frontend/src/components/ConfirmedCard/ConfirmedCard.tsx` | MarketBadge |

### Frontend — Types & API (2)
| File | Changes |
|---|---|
| `frontend/src/types/signals.ts` | Add `MarketType`; add `market_type` to all interfaces |
| `frontend/src/api/client.ts` | Add `marketType` params; new Indian API functions |

---

## Files NOT Changing

These files remain untouched (either no market-specific logic, or consumed by other changed files):

- `backend/app/core/indicators.py` — Pure math, market-agnostic
- `backend/app/core/market_structure.py` — Works on any OHLCV data
- `backend/app/core/events.py` — Works on any OHLCV data
- `backend/app/core/market_regime.py` — Works on any OHLCV data
- `backend/app/core/llm_client.py` — Agnostic; context builder handles market specifics
- `backend/app/core/llm_context_builder.py` — Enhanced later (Phase E) but core unchanged
- `backend/app/core/llm_queue.py` — No changes needed
- `backend/app/core/telegram_client.py` — No changes needed
- `backend/app/core/telegram_formatter.py` — May add market badge in messages (cosmetic)
- `backend/app/core/telegram_queue.py` — No changes needed
- `backend/app/core/watching.py` — May get `market_type` param internally
- `backend/app/core/outcome_tracker.py` — May get `market_type` param internally  
- `backend/app/core/sse.py` — No changes (data carries market_type naturally)
- `backend/app/core/scheduler.py` — Add Indian market open/close schedule entries
- `backend/app/core/backtest_engine.py` — May get `market_type` param
- `backend/app/core/confluence.py` — Agnostic
- All existing strategy files — Add `allowed_market_types = ['CRYPTO']` (one line each)
- `backend/app/blueprints/backtest_bp.py` — May add market_type filter
- `backend/app/blueprints/indicators_bp.py` — May add market_type filter
- `backend/app/blueprints/sr_zones_bp.py` — May add market_type filter
- `backend/app/blueprints/alerts_bp.py` — May add market_type filter
- `frontend/src/components/RejectedCard/` — Add MarketBadge
- `frontend/src/pages/Charts/` — Market-aware symbol selector
- `frontend/src/pages/Backtest/` — Market-aware options
- `frontend/src/pages/BacktestAnalyser/` — Market-aware
- `frontend/src/pages/LLMPrompts/` — Market filter
- `frontend/src/pages/PriceAlerts/` — Market-aware
