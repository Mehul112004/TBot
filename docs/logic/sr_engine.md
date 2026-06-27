# Support/Resistance Engine Logic

The S/R detection engine lives in `app/core/sr_engine.py` and discovers horizontal support/resistance **zones** (price bands with an upper/lower bound, not single lines) from candle data.

> **v2.0 (de-bloated):** The engine was rewritten to produce a small, clean set of high-quality zones instead of the cluttered "wall of lines" the original produced. Key changes: wider swing lookback (12), touch-gated strength scoring with recency decay, large-grain-only round numbers, prev-day/week H/L removed (replaced by the richer Pivot Points layer — see [pivot_points.md](./pivot_points.md)), aggressive merging (0.75×ATR), and a full-wipe-on-refresh that prunes stale-scored rows.

---

## Detection Methods

Each method returns a raw list of candidate zone dicts.

### `detect_swing_points(df, lookback=12)`
*   **Description:** Finds structural peaks and valleys in price action.
*   **How it Works:** Iterates through the candle array. A "Swing High" requires the candle's high to be the maximum of the `±lookback` window **and** the center candle must be the *first* occurrence of that maximum (`np.argmax == lookback`). This eliminates duplicate zones when multiple candles share the same high within a window. "Swing Lows" perform the inverse check using `np.argmin`. Each detected zone records its `_formation_idx` (the DataFrame index of the candle that formed it) so that `score_zone()` can count only *post-formation* touches.
*   **Why lookback=12 (was 5):** A wider window flags structural pivots, not micro-noise. With lookback=5, a 500-candle chart flagged dozens of minor swing points, bloating the chart. Lookback=12 (~2× a typical 1h holding period) produces ~5–10 high-quality swing zones.
*   **Input:** Pandas DataFrame of candles, `lookback` (int, default 12).
*   **Output:** List of zone dicts (`price_level`, `zone_type`, `detection_method='swing'`, `_formation_idx`).

### `detect_round_numbers(symbol, current_price, range_pct=0.15, price_range=None, grain='large')`
*   **Description:** Defines zones at psychologically significant round numbers (e.g., Bitcoin at $60,000 or $65,000).
*   **How it Works:** Looks up the symbol in `ROUND_NUMBER_CONFIG` (BTC/ETH/SOL only) or falls back to `get_round_grains()` which derives grains dynamically from the current price (~1% small, ~5% large) using the nearest "nice" increment (1, 2, or 5 × 10^k). Uses an integer step counter (`start + n * increment`) to avoid floating-point drift. The `grain` parameter controls density: `'large'` (default, sparse — for chart clarity), `'small'` (dense), or `'both'`.
*   **Config (explicit):**
    *   `BTCUSDT`: small=$1000, large=$5000
    *   `ETHUSDT`: small=$100, large=$500
    *   `SOLUSDT`: small=$10, large=$50
*   **Dynamic fallback:** Any other symbol gets grains derived from its price via `_auto_grain(price, pct)`. This ensures a $204 coin (BCHUSDT) gets $10-grain levels, not the old $500 default which was bigger than its entire price range.
*   **Input:** `symbol` (str), `current_price` (float), `range_pct` (float), `price_range` (optional tuple), `grain` (str).
*   **Output:** List of zone dicts marked `round_number`.

### ~~`detect_prev_period_hl(symbol)`~~ (removed from pipeline)
*   Previous day/week H/L is no longer emitted by the S/R engine. That role is filled by the richer **Pivot Points** layer (see [pivot_points.md](./pivot_points.md)) which computes a full set of forecast levels from the previous completed period's H/L/C. The method is retained in the class for reference but not called by `detect_zones` or `detect_zones_df`.

---

## Processing & Refinement Methods

### `calculate_zone_width(price_level, atr)`
*   **How it Works:** Zone width = `price_level ± (0.25 × ATR)`. If volatility is high, the zone is wide; if low, it's tight.

### `merge_zones(zones, atr)`
*   **Description:** Deduplicates zones clustered tightly together.
*   **How it Works:** Multi-pass approach (up to 10 iterations, converges in 2–3). Each pass sorts by price and collapses adjacent zones within **`0.75 × ATR`** (was 0.5×ATR — wider threshold merges more near-equal levels, reducing chart clutter). When merging, keeps the higher `touch_count` and more recent `timestamp`. If `resistance` and `support` merge, the zone type becomes `both`.
*   **Input:** Overlapping zone dicts, current ATR.
*   **Output:** Consolidated, unique zone dicts.

### `score_zone(zone, df, timeframe, formation_idx=None, max_bar=None)`
*   **Description:** Assigns a strength score based on post-formation touches and recency.
*   **Touch semantics (FIX-SR-LOOK):** A touch = any candle **after** the zone formed whose high/low range intersects the zone band. Touches are counted from `formation_idx + 1` to `max_bar` (or end of df). Counting only post-formation touches is both semantically correct (a zone can only be "tested" once it exists) and consistent across the DB and DataFrame detection paths.
*   **Strength formula (touch-gated + recency-decayed):**
    ```
    if touches < 2:
        strength = 0                    # a single touch is not S/R
    else:
        base = min(1.0, (touches - 1) * 0.12 + tf_weight * 0.5)
        age = bars since zone was last tested
        strength = base * exp(-age / 150)   # recency decay (halflife ~104 bars)
    ```
*   **Why touch-gated:** The old formula `touches * 0.15 + tf_weight` gave every 0-touch zone a baseline of `tf_weight` (e.g. 0.28 for 4h). The frontend's `min_strength=0.2` filter couldn't exclude them, so single-touch swing points rendered as full S/R. The new formula requires ≥2 touches for a non-zero score.
*   **Why recency decay:** A zone tested 200 bars ago is far less relevant than one tested 5 bars ago. The exponential decay `exp(-age/150)` means a zone untested for ~104 bars loses half its strength, and one untested for ~300 bars is near zero.
*   **Timeframe weights** (`TIMEFRAME_WEIGHTS`): `1w: 0.50`, `1d: 0.40`, `12h: 0.35`, `8h: 0.32`, `6h: 0.30`, `4h: 0.28`, `2h: 0.22`, `1h: 0.20`, `30m: 0.15`, `15m: 0.10`, `5m: 0.07`, `3m: 0.05`, `1m: 0.03`.
*   **`max_bar` parameter:** If set, only counts touches in `df[formation_idx+1 : max_bar]`. Used by backtests to avoid lookahead. Defaults to `None` (= end of df, live snapshot).

---

## Workflow Orchestrators

### `detect_zones(symbol, timeframe, swing_lookback=12)`
*   **Description:** Master function that sequences the full pipeline.
*   **Pipeline:**
    1. Fetches 500 most recent candles from DB.
    2. Computes ATR(14) for zone-width calculations.
    3. Runs detection methods: swing points (lookback=12) + round numbers (large grain only).
    4. ~~Prev day/week H/L~~ (removed — covered by Pivot Points layer).
    5. Establishes zone boundaries: `price_level ± 0.25 × ATR`.
    6. Passes pool into `merge_zones()` (0.75×ATR threshold).
    7. Re-calculates bounds on merged entities.
    8. Calls `score_zone()` on finalists.
    9. **Drops zones with <2 touches** (not real S/R — never persisted, never charted).
*   **Output:** Final list of polished zone dicts ready for DB insertion.

### `detect_zones_df(df, symbol, timeframe, swing_lookback=12, max_bar=None)`
*   **Description:** Same pipeline but operates on an in-memory DataFrame and appends `sr_*` columns (used by strategies via `base_strategy.pre_process`).
*   **Appends columns:** `sr_active`, `sr_support_upper/lower/strength`, `sr_resistance_upper/lower/strength`.
*   **Temporal masking:** Zones only appear after their formation candle (prevents lookahead bias in backtests when `max_bar` is set).
*   **Touch consistency:** Scores using `formation_idx+1 → max_bar` — consistent with `detect_zones`. The old DF path scored `df.iloc[:form_idx]` (backwards), the DB path scored all candles; both were wrong.

### `persist_zones(symbol, timeframe, zones, prune_stale=False)`
*   **How it Works:** Attempts PostgreSQL `insert...on_conflict_do_update` first. Falls back to standard SQLAlchemy ORM if PG dialect unavailable (e.g. SQLite in tests). A shared `_build_zone_record()` helper normalizes zone dicts.
*   **`prune_stale=True` (used by `full_refresh`):** Wipes **ALL** existing rows for the symbol/timeframe before persisting the freshly-detected set. This guarantees every DB row reflects CURRENT scoring — no leftover stale scores from older regimes survive. `minor_update` keeps `prune_stale=False` so it never wipes incremental state.
*   **Defensive filter:** Never persists zones with `<2 touches`, regardless of caller.

### `full_refresh(symbol, timeframe)`
*   Calls `detect_zones` → `persist_zones(prune_stale=True)`.
*   Uses per-symbol lock.
*   Triggered by scheduler (4h/1d candle close), scanner, and the `POST /api/sr-zones/refresh` endpoint.

### `minor_update(symbol, timeframe)`
*   Swing-only detection on recent 50-candle window (lookback=12).
*   Adds new swing points without full recalculation.
*   Filters to ≥2 touches before persisting.
*   Invalidates IndicatorService cache after zone changes.

---

## Thread Safety: Per-Symbol Refresh Locks
*   `SREngine` maintains a `_refresh_locks` dict of `threading.Lock` objects, one per symbol.
*   `full_refresh()` and `minor_update()` acquire the lock before detecting and persisting.
*   `LiveScanner._on_candle_close()` acquires the same lock before reading zones from the DB.
*   Prevents the scheduler from committing mid-cycle while the scanner reads.

---

## Configuration

*   `ROUND_NUMBER_CONFIG` (in `sr_engine.py`): explicit grains for BTC/ETH/SOL only.
*   `get_round_grains(symbol, current_price)`: dynamic fallback for any other symbol.
*   `SUPPORTED_SYMBOLS` lives in `app/core/config.py`.

---

## Background Scheduler (`app/core/scheduler.py`)

The S/R engine utilizes `apscheduler` inside the Flask context to automate zone tracking. All jobs filter to **active sessions only**.

| Job | Trigger | Timeframes | Mode |
|-----|---------|------------|------|
| `full_zone_refresh_4h` | cron every 4h at `:01` UTC | `4h` | Full refresh + prune |
| `full_zone_refresh_1d` | cron daily at `:02` UTC | `1d` | Full refresh + prune |
| `minor_zone_update` | cron hourly at `:03` UTC | `1h`, `15m` | Minor update (swing only) |
| `startup_full_refresh` | date (once on boot) | all supported TFs | Full refresh + prune |

All jobs have `coalesce=True` and `max_instances=1` to prevent thundering herd.

### Event-Driven Refresh (Primary for Live Sessions)

*   `4h` / `1d` candle close → `SREngine.full_refresh()`
*   `1h` / `15m` candle close → `SREngine.minor_update()`

---

## API Endpoints (`app/blueprints/sr_zones_bp.py`)

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/sr-zones` | GET | Fetch stored S/R zones with MTF confluence + optional round numbers |
| `/api/sr-zones/refresh` | POST | Manually trigger full refresh + prune for a symbol |
| `/api/sr-zones/pivots` | GET | Compute pivot-point levels (Camarilla/Standard) from prev period |
| `/api/sr-zones/smc-zones` | GET | Compute FVG/OB zones on-the-fly (separate concept) |

### MTF (Multi-Timeframe) Stacking

`GET /api/sr-zones` returns zones for the viewed timeframe **plus the next 2 higher timeframes** up the canonical ladder:

```
HTF_LADDER = ['15m', '1h', '4h', '1d', '1w']
```

Example: viewing `1h` returns zones from `1h` + `4h` + `1d`. Each zone is tagged with its origin `timeframe`. Confluence is flagged when a viewed-TF zone's band overlaps an HTF zone's band.

### Parameters

| Param | Default | Description |
|---|---|---|
| `symbol` | (required) | Trading pair |
| `timeframe` | (required) | Viewed timeframe |
| `min_touches` | 3 | Minimum touches to include |
| `limit` | 8 | Top-N zones per timeframe by strength |
| `include_htf` | true | Stack higher-timeframe zones |
| `htf_depth` | 2 | How many HTFs to stack |
| `include_round_numbers` | false | Emit separate `round_numbers` array |
| `near_price` | — | Only zones within ±3% of this price |

### Round-Numbers Sub-Layer

When `include_round_numbers=true`, the response includes a separate `round_numbers` array (large-grain psychological levels only, ~6 nearest to price). These are **not** part of the S/R band layer — they render as faint dotted lines on the chart with their own toggle.