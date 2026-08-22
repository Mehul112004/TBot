# Pivot points

The pivot engine calculates horizontal reference lines from the **prior completed** daily or weekly candle. Pivots are a chart/analysis overlay and are calculated on request; they are not persisted as `SRZone` records.

## Variants

| Variant | Output |
| --- | --- |
| Standard | Pivot point plus support/resistance ladder derived from prior high, low, and close |
| Camarilla | Camarilla support/resistance ladder derived from the same prior completed candle |
| All | Both standard and Camarilla sets in one response |

`GET /api/sr-zones/pivots` accepts a symbol and period/variant options. The endpoint picks the latest available completed reference candle; where enough local history exists, this means it intentionally avoids forming-period data.

## Relationship to S/R zones

S/R zones are persisted ATR-width reaction bands built from swings and psychological levels. Pivots are deterministic point-in-time lines. The chart can show either or both; they should not be conflated in strategy code or database assumptions.

Relevant files: `backend/app/core/pivot_engine.py`, `backend/app/blueprints/sr_zones_bp.py`, and the chart data hook/components under `frontend/src/pages/Charts/`.
