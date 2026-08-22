# Support/resistance engine

`SREngine` creates and persists support/resistance **bands** for a symbol/timeframe. It is used by live analysis and the chart API; it is not an order-execution component.

## Detection and scoring model

1. Swing points are detected with a default 12-bar lookback on either side.
2. Psychological round-number candidates are generated at symbol/price-appropriate grain sizes.
3. Each candidate becomes an ATR-scaled band (default half-width: 0.25 × ATR).
4. Nearby zones are merged using an ATR-relative threshold. A merged support/resistance pair is labelled `both`.
5. Post-formation tests/touches, timeframe weight, and recency contribute to strength; untested/single-touch candidates are excluded from meaningful scored output.

The persisted model records centre/bounds, support/resistance/both type, detection method, strength, touch count, and timestamps. A per-symbol lock coordinates refresh work.

## Refresh behaviour

- A full refresh calculates zones over the available recent window and replaces the stored set for its symbol/timeframe.
- A minor refresh recalculates a recent lower-timeframe window.
- Live scanner closed-candle processing and the scheduler initiate refreshes at different timeframes; manual refresh is `POST /api/sr-zones/refresh`.

`GET /api/sr-zones` returns the viewed timeframe and an optional higher-timeframe ladder (`15m → 1h → 4h → 1d → 1w`), filters by touches/top-N, and labels overlapping cross-timeframe bands as confluence. It can include round-number display levels on request.

## Chart overlays

The S/R chart layer uses persisted zone bands. Pivots are calculated independently by `pivot_engine.py`; legacy FVG/order-block overlays come from `/api/sr-zones/smc-zones`. The visual reading guide is [S/R zones and pivots](../knowledge_base/sr_zones_and_pivots.md).

Relevant files: `backend/app/core/sr_engine.py`, `backend/app/models/db.py`, `backend/app/blueprints/sr_zones_bp.py`, and `backend/tests/test_sr_engine.py`.
