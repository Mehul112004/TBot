# Phase 2: Structure + Zones — BOS, CHoCH, MSS, FVGs, Order Blocks

## Goal

Reimplement the v1 BoS/CHoCH engines (from archived `events.py` and `market_structure.py`) as a single, cleaner `structure.py`, then build on the Phase 1 foundation to add **multi-slot FVGs with fill %** (`fvgs.py`) and **multi-slot Order Blocks with mitigation ledger** (`order_blocks.py`).

The most important deliverable is **parity with v1**: the v1 `/api/sr-zones/smc-zones` endpoint produced a known signal count on a fixed dataset. The new modules must produce *at least* the same event count, on the same dataset, before they ship. Any silent regression means the v1 logic is being subtly different — and v1 was battle-tested against live signals.

## Files Created

| File | LOC (est.) | Purpose |
|---|---|---|
| `backend/app/core/smc/structure.py`     | ~350 | Internal BOS, Swing BOS, Internal CHoCH, Swing CHoCH, MSS |
| `backend/app/core/smc/fvgs.py`          | ~300 | Multi-slot FVG with fill % tracking |
| `backend/app/core/smc/order_blocks.py`  | ~400 | Multi-slot OB ledger with mitigation status, displacement grading |

## Tasks

### 2.1 `structure.py` — The Consolidator

Two parallel BoS/CHoCH implementations exist in v1 (`events.detect_choch` and `market_structure.extract_market_structure_events`). They produce different column sets and have subtle differences. v2 consolidates into a single engine with five event types.

#### Event taxonomy (locked)

| Event | Definition | Use case |
|---|---|---|
| `internal_bos_bull` | Body close > last confirmed **internal** swing high, while internal trend = up | Continuation (low-conviction) |
| `internal_bos_bear` | Mirror | Continuation (low-conviction) |
| `swing_bos_bull` | Body close > last confirmed **swing** (high-degree) high, while swing trend = up | Continuation (high-conviction) |
| `swing_bos_bear` | Mirror | Continuation (high-conviction) |
| `internal_choch_bull` | Body close > last confirmed internal high, while internal trend was *down* | Minor reversal |
| `internal_choch_bear` | Mirror | Minor reversal |
| `swing_choch_bull` | Body close > last confirmed swing high, while swing trend was *down* | Major reversal (the one to trade) |
| `swing_choch_bear` | Mirror | Major reversal (the one to trade) |
| `mss_bull` | A swing CHoCH where the prior trend was well-established (≥ 2 swing BOS in same direction previously) AND the breaking candle forms an FVG on the opposite side | Highest-confidence reversal |
| `mss_bear` | Mirror | Highest-confidence reversal |

#### API

```python
def extract_structure(
    df: pd.DataFrame,
    swing_pivot_bars: int = SWING_PIVOT_BARS,        # re-imported from swings.py
    internal_pivot_bars: int = INTERNAL_PIVOT_BARS,
) -> pd.DataFrame:
    """
    Required input columns (added by Phase 1):
        swing_high, swing_low, internal_high, internal_low,
        swing_high_confirmed_at, swing_low_confirmed_at,
        internal_high_confirmed_at, internal_low_confirmed_at,
        open, close

    Adds:
        struct_internal_event ∈ {None, 'IBOS_UP', 'IBOS_DOWN',
                                       'ICHOCH_UP', 'ICHOCH_DOWN'}
        struct_swing_event    ∈ {None, 'SBOS_UP', 'SBOS_DOWN',
                                       'SCHOCH_UP', 'SCHOCH_DOWN'}
        struct_mss            ∈ {None, 'MSS_UP', 'MSS_DOWN'}
        struct_trend_internal ∈ {-1, 0, 1}   (0 = neutral)
        struct_trend_swing    ∈ {-1, 0, 1}
        struct_trend_maturity int  — count of BOS in current trend direction
                                     (resets on CHoCH). Used to gate MSS.
    """
```

#### Critical implementation rules

1. **The state machine uses *confirmed* swings only** — call `latest_confirmed_swing(df, i, 'swing_high')` from `swings.py`, never read `df['swing_high']` directly to find the break level.
2. **BOS rule is `body_high > last_swing_high.price`** (not wick). `body_high = max(open, close)`. This is in the constants table (`_params.CONSTANTS`).
3. **After a break, the swing level is consumed** — set `last_confirmed_swing_high = None` after the break so the same level doesn't fire repeatedly on the same condition.
4. **MSS gate** — only fire `MSS_UP` if:
   - Prior `struct_trend_swing == -1` for ≥ 2 swing BOS events (`struct_trend_maturity >= 2`)
   - The breaking candle's `open_time` falls within a kill zone (`is_kill_zone == True`) — *OR* the engine's `bias.py` agrees. (This is a tightening that the validator will check for in Phase 5.)

#### Parity backtest: re-run v1 against the same input

Before v2 ships, this comparison must run cleanly:

```python
# backend/app/core/smc/_parity_test.py  (test scaffolding, not shipped in prod)
def parity_test_choch():
    """
    Same DataFrame in, compare:
        v1 events.detect_choch(df) → event_choch_bullish / event_choch_bearish counts
        v2 events.extract_structure(df) → struct_swing_event counts (SCHOCH_UP/DOWN only)
    The v2 count must be >= v1 count (v2 may detect internal CHoCHs v1 missed,
    but must not miss any swing CHoCHs v1 found).
    """
```

**Pass criteria**: on a 12-month BTC 15m dataset, `v2.swing_choch_up + v2.swing_choch_down >= v1.event_choch_bullish + v1.event_choch_bearish`. Allow v2 to have more (internal CHoCHs) but not fewer (regressions).

### 2.2 `fvgs.py` — Multi-Slot FVG with Fill %

The v1 FVG extraction (`market_structure.py:45-199`) is the best part of the v1 code — the 5-slot multi-zone tracking is solid. v2 **inherits the architecture** and adds:
- Explicit `fill_pct` column
- Explicit `fill_at` timestamp
- No change to the 5-slot limit (it's in `_params.py`).

#### API

```python
def extract_fvgs(
    df: pd.DataFrame,
    mitigation_type: str = 'wick',   # constant; 'wick' or 'body'
    lookback: int = 50,
    max_zones: int = 5,              # constant from _params
) -> pd.DataFrame:
    """
    Required input columns: open, high, low, close, volume, open_time
    Adds (per-slot):
        fvg_{slot}_active        bool
        fvg_{slot}_upper, _lower float
        fvg_{slot}_fill_pct      float ∈ [0, 1]    0=untouched, 1=fully filled
        fvg_{slot}_fill_at       timestamp (set on full mitigation)
        fvg_{slot}_direction     ∈ {bullish, bearish}
        fvg_{slot}_volume, _created_at, _distance_to_close

    Plus aggregate:
        fvg_active, fvg_upper, fvg_lower, fvg_fill_pct (avg over active slots),
        fvg_zone_count, fvg_nearest_distance_atr
    """
```

#### The `fill_pct` calculation (the new piece)

For a bullish FVG (lower < close < upper, gap is between high[i-2] and low[i]):

```python
# partial fill: only a wick has pierced into the gap
# body still above the gap (close > upper)  → fill_pct = 0
# wick into the gap, body still above      → fill_pct = (upper - wick_low) / (upper - lower)
# body inside the gap, close > lower       → fill_pct = (upper - close) / (upper - lower)
# wick reached lower, body > lower         → fill_pct = 1 (fully filled)
# body close <= lower                      → fill_pct = 1, fill_at = bar, active = False
```

Mirror for bearish.

The implementation uses `np.clip(fill_pct, 0, 1)` to prevent overshoot from wicks that briefly exceed the gap (a wick that pokes through the lower bound of a bullish FVG still counts as fill_pct=1, not > 1).

#### Why `fill_pct` matters

A v1 FVG zone is just a price rectangle. A v2 FVG with `fill_pct > 0.5` is a zone that price has *engaged with* but not finished — a different trade. v2 distinguishes:
- **Fresh FVG, fill_pct=0**: classic ICT entry at the FVG midpoint, expecting a reaction.
- **Engaged FVG, 0.3 ≤ fill_pct < 0.7**: confluence zone, weaker entry signal but tight SL.
- **Filled FVG, fill_pct=1**: dead zone, ignore.

The validator in Phase 5 will IC-test whether "fresh FVGs at 50% premium with HTF bullish bias" has different forward returns than "engaged FVGs" — the split must be measurable or the feature is noise.

### 2.3 `order_blocks.py` — Multi-Slot Ledger

v1 OBs are the weakest part of the v1 code (`market_structure.py:204-395`):
- Single-slot (only the most recent unmitigated OB is tracked).
- Mitigation is implicit (OB silently dropped on body-close through boundary).
- No historical ledger (can't ask "what OBs were mitigated last week?").

v2 fixes all three.

#### API

```python
def extract_order_blocks(
    df: pd.DataFrame,
    impulse_min: int = 2,
    impulse_max: int = 5,
    atr_displacement: float = 1.5,           # = atr_displacement_mult from _params
    pivot_bars: int = 3,                     # for BOS validation
    max_zones: int = 5,
    ob_max_age_bars: int = 200,              # mitigation ledger holds 200 bars
) -> pd.DataFrame:
    """
    Required input columns: open, high, low, close, volume, open_time, atr,
                            swing_high, swing_low, swing_high_confirmed_at,
                            swing_low_confirmed_at
    Adds (per-slot):
        ob_{slot}_active              bool
        ob_{slot}_upper, _lower       float
        ob_{slot}_direction           ∈ {bullish, bearish}
        ob_{slot}_displacement_atr    float — impulse size in ATR units
        ob_{slot}_volume, _created_at
        ob_{slot}_mitigated           bool   — explicit, not implicit
        ob_{slot}_mitigated_at        timestamp
        ob_{slot}_mitigation_pct      float ∈ [0, 1]
        ob_{slot}_test_count          int    — how many times price has retouched
        ob_{slot}_last_tested_at      timestamp
        ob_{slot}_impulse_quality     ∈ {A, B, C}   — graded by displacement

    Plus aggregate:
        ob_active, ob_upper, ob_lower, ob_zone_count,
        ob_nearest_distance_atr
    """
```

#### The state machine

```python
# Pseudocode for the per-bar state machine
for i in range(n):
    # Step 1: promote pending OB (formed at bar i-1) to active at bar i
    #         (shift+1, lookahead-bias prevention, same as v1)
    if pending_ob is not None:
        active_slots[pending_ob.slot] = pending_ob

    # Step 2: for every active slot, update mitigation/test counters
    for slot, ob in active_slots.items():
        if ob.mitigated:
            continue   # mitigated OBs don't update further; they age out by bar count
        # test: did the current candle touch the OB?
        if candle_touches_zone(ob, current_candle):
            ob.test_count += 1
            ob.last_tested_at = current_open_time
        # update mitigation
        if ob.direction == 'bullish' and close < ob.lower:
            ob.mitigated = True
            ob.mitigated_at = current_open_time
            ob.mitigation_pct = 1.0
        elif ob.direction == 'bearish' and close > ob.upper:
            ob.mitigated = True
            ob.mitigated_at = current_open_time
            ob.mitigation_pct = 1.0
        elif ob.direction == 'bullish' and low < ob.lower:
            # wick into the OB; not yet mitigated
            ob.mitigation_pct = max(ob.mitigation_pct,
                                     (ob.lower - low) / (ob.upper - ob.lower))
        elif ob.direction == 'bearish' and high > ob.upper:
            ob.mitigation_pct = max(ob.mitigation_pct,
                                     (high - ob.upper) / (ob.upper - ob.lower))

    # Step 3: try to detect a NEW OB at bar i (similar to v1 logic but with slots)
    # ... (impulse detection, BOS validation, slot allocation)
```

The slot allocation strategy is FIFO: if all 5 slots are full, the *oldest* (by `created_at`) is dropped. Mitigated OBs continue to occupy their slot for `ob_max_age_bars=200` bars, then are aged out (this allows "mitigated and ran" retest patterns to be detected by strategies — a different concept from "live unmitigated OB").

#### Impulse quality grading

`ob_{slot}_impulse_quality ∈ {A, B, C}`:
- **A**: displacement ≥ 2.5 × ATR (large, high-confidence impulse — most likely to create a tradeable OB)
- **B**: displacement 1.5–2.5 × ATR (default grade)
- **C**: displacement 1.0–1.5 × ATR (weak, low-confidence)

Only A and B grade OBs are emitted as `ob_active=True`; C-grade OBs go to a separate `ob_c_grade_active` column for the strategy to optionally consider. This is one of the 5 free parameters (`atr_displacement_mult` in `_params.py`); the C-grade cutoff is derived from it (e.g., C if displacement < 1.0 × `atr_displacement_mult`).

#### Parity backtest

```python
def parity_test_ob():
    """
    Compare v1 single-slot OB vs v2 multi-slot.
    On a 12-month BTC 15m dataset:
        v1 produces N ob_active=True bars
        v2 produces >= N ob_active=True bars  (v2 may detect more due to multi-slot)
        AND the FIRST OB detected by v1 in each run must be detected by v2
           (regression test: v2 should never miss the OB v1 found)
    """
```

## Manual Verification

### Verify 2.1 — `structure.py` parity

```bash
cd backend && python -c "
import pandas as pd
from app.core.data_utils import get_finalized_candles
from app.strategies.archive.smc_v1.events import detect_choch as v1_detect
from app.core.smc.swings import extract_swings
from app.core.smc.structure import extract_structure
from app.core.smc.sessions import stamp_sessions, compute_session_ranges

# 12 months of BTC 15m = ~35,000 rows
df = get_finalized_candles('BTCUSDT', '15m', limit=35_000)
assert len(df) > 30_000, f'need 12 months of 15m, got {len(df)}'

# v1 path
df_v1 = v1_detect(df.copy())
v1_choch_count = df_v1['event_choch_bullish'].sum() + df_v1['event_choch_bearish'].sum()
v1_bos_count   = df_v1['event_bos_bullish'].sum()   + df_v1['event_bos_bearish'].sum()
print(f'v1: choch={v1_choch_count}, bos={v1_bos_count}')

# v2 path (need Phase 1 first)
df_v2 = stamp_sessions(df.copy())
df_v2 = compute_session_ranges(df_v2)
df_v2 = extract_swings(df_v2)
df_v2 = extract_structure(df_v2)
v2_schoch = ((df_v2['struct_swing_event'] == 'SCHOCH_UP').sum()
           + (df_v2['struct_swing_event'] == 'SCHOCH_DOWN').sum())
v2_sbos   = ((df_v2['struct_swing_event'] == 'SBOS_UP').sum()
           + (df_v2['struct_swing_event'] == 'SBOS_DOWN').sum())
v2_ichoch = ((df_v2['struct_internal_event'] == 'ICHOCH_UP').sum()
           + (df_v2['struct_internal_event'] == 'ICHOCH_DOWN').sum())
v2_ibos   = ((df_v2['struct_internal_event'] == 'IBOS_UP').sum()
           + (df_v2['struct_internal_event'] == 'IBOS_DOWN').sum())
v2_mss    = df_v2['struct_mss'].notna().sum()
print(f'v2: schoch={v2_schoch}, sbos={v2_sbos}, ichoch={v2_ichoch}, ibos={v2_ibos}, mss={v2_mss}')

# (a) v2 SCHOCH >= v1 CHoCH (regression test: must not miss any)
assert v2_schoch >= v1_choch_count, f'REGRESSION: v2 schoch={v2_schoch} < v1 choch={v1_choch_count}'
# (b) v2 SBOS >= v1 BoS
assert v2_sbos >= v1_bos_count, f'REGRESSION: v2 sbos={v2_sbos} < v1 bos={v1_bos_count}'
# (c) MSS is a STRICT SUBSET of SCHOCH (MSS is gated by maturity)
assert v2_mss <= v2_schoch, f'MSS must be <= SCHOCH, got mss={v2_mss}, schoch={v2_schoch}'
# (d) Internal event count > 0 (we use them; should be non-trivial)
assert v2_ichoch + v2_ibos > 100, f'expected many internal events, got {v2_ichoch + v2_ibos}'
# (e) struct_trend_swing ∈ {-1, 0, 1}
assert set(df_v2['struct_trend_swing'].unique()) <= {-1, 0, 1}, 'trend values out of range'
print('OK: structure.py parity backtest passes')
"
```

**Pass criteria**: all 5 assertions. The `(a)` and `(b)` are the **regression gates** — if v2 detects fewer swing CHoCHs or swing BoS events than v1 on the same data, you have a silent regression that would degrade live signal quality.

**Common failures**:
- `(a)` failing: v2 might be using `swing_high_confirmed_at` too aggressively (e.g., requiring `confirmed_at + 1` instead of `confirmed_at`). Check that the comparison `body_high > last_confirmed_swing_high.price` uses the LATEST confirmed swing, not the LATEST *forming* swing.
- `(c)` failing: MSS gate is being applied to internal events, not swing events. The gate must look at `struct_trend_swing` maturity, not `struct_trend_internal`.

### Verify 2.2 — `fvgs.py` parity + fill %

```bash
cd backend && python -c "
import pandas as pd
import numpy as np
from app.core.data_utils import get_finalized_candles
from app.strategies.archive.smc_v1.market_structure import extract_fvgs as v1_extract
from app.core.smc.fvgs import extract_fvgs as v2_extract

df = get_finalized_candles('BTCUSDT', '15m', limit=35_000)

# v1
df_v1 = v1_extract(df.copy())
v1_active_bars = df_v1['fvg_active'].sum()
v1_total_zones_created = (df_v1['fvg_zone_count'] > 0).sum()
print(f'v1: active bars={v1_active_bars}, zone_created_bars={v1_total_zones_created}')

# v2
df_v2 = v2_extract(df.copy())
v2_active_bars = df_v2['fvg_active'].sum()
v2_total_zones_created = (df_v2['fvg_zone_count'] > 0).sum()
print(f'v2: active bars={v2_active_bars}, zone_created_bars={v2_total_zones_created}')

# (a) v2 active bars >= v1 (v2 may have more due to fill% keeping partial zones alive)
assert v2_active_bars >= v1_active_bars, f'v2 active={v2_active_bars} < v1={v1_active_bars}'
# (b) v2 total created zones >= v1 (same logic)
assert v2_total_zones_created >= v1_total_zones_created, \
    f'v2 created={v2_total_zones_created} < v1 created={v1_total_zones_created}'

# (c) fill_pct is in [0, 1] for all active zones
active_fvg = df_v2[df_v2['fvg_active'] == True]
assert (active_fvg['fvg_fill_pct'] >= 0).all() and (active_fvg['fvg_fill_pct'] <= 1).all(), \
    f'fill_pct out of range: min={active_fvg[\"fvg_fill_pct\"].min()}, max={active_fvg[\"fvg_fill_pct\"].max()}'

# (d) Construct a synthetic FVG that should be fully filled
# Bullish FVG at rows 5,6,7: lows[7] > highs[5]
synth = pd.DataFrame({
    'open':  [100, 101, 102, 105, 110, 115, 120, 120, 120, 120, 100],
    'high':  [101, 102, 103, 106, 111, 116, 125, 121, 121, 121, 101],
    'low':   [100, 100, 100, 100, 100, 100, 121, 118, 105, 100, 99],
    'close': [100, 101, 102, 105, 110, 115, 124, 120, 110, 100, 99],
    'volume':[1000]*11,
    'open_time': pd.date_range('2024-01-01', periods=11, freq='15min', tz='UTC'),
})
out = v2_extract(synth)
# FVG created at bar 7 (low=121 > high of bar 5 = 111, gap 111-121)
# Bar 8: wick at 118, close 120, body above 121 → fill_pct = (121-118)/(121-111) = 0.3
# Bar 9: low at 105, close 110, body inside gap → fill_pct = (121-110)/(121-111) = 1.0+? clip → 1.0
# Bar 10: low 100, close 100, fully filled → fill_pct = 1.0, active = False
for i in range(7, 11):
    print(f'bar {i}: active={out.iloc[i][\"fvg_active\"]}, fill_pct={out.iloc[i][\"fvg_fill_pct\"]:.2f}')
# bar 7: 0, bar 8: 0.3, bar 9: 1.0, bar 10: 1.0 (but active=False)
# Allow loose bounds — the test is that fill_pct is monotonically non-decreasing
fp = out['fvg_fill_pct'].iloc[7:11].values
diffs = np.diff(fp)
assert (diffs >= -0.01).all(), f'fill_pct should be non-decreasing, got: {fp}'
print('OK: fvgs.py parity + fill% behaviour')
"
```

**Pass criteria**:
- `(a)` and `(b)` are regression gates.
- `(c)` checks the `fill_pct` is in [0, 1] — this is the contract.
- The synthetic test verifies that `fill_pct` is **monotonically non-decreasing** within an FVG's lifetime. If `fill_pct` jumps down (e.g., back to 0 after being 0.7), the implementation is buggy.

### Verify 2.3 — `order_blocks.py` parity + mitigation

```bash
cd backend && python -c "
import pandas as pd
from app.core.data_utils import get_finalized_candles
from app.strategies.archive.smc_v1.market_structure import extract_order_blocks as v1_extract
from app.core.smc.order_blocks import extract_order_blocks as v2_extract
from app.core.smc.swings import extract_swings

df = get_finalized_candles('BTCUSDT', '15m', limit=35_000)

# v1
df_v1 = v1_extract(df.copy())
v1_ob_bars = df_v1['ob_active'].sum()
print(f'v1: ob_active bars = {v1_ob_bars}')

# v2 (needs swings from Phase 1)
df_v2 = extract_swings(df.copy())
df_v2 = v2_extract(df_v2)
v2_ob_bars = df_v2['ob_active'].sum()
print(f'v2: ob_active bars = {v2_ob_bars}')

# (a) v2 should detect AT LEAST as many OB-active bars as v1
# (multi-slot means v2 may keep OBs active longer)
assert v2_ob_bars >= v1_ob_bars, f'v2 ob={v2_ob_bars} < v1 ob={v1_ob_bars}'

# (b) Every mitigated OB has a mitigation_pct == 1.0
mitigated = df_v2[(df_v2['ob_0_mitigated'] == True) | (df_v2['ob_1_mitigated'] == True)]
for i, row in mitigated.iterrows():
    for slot in range(5):
        if row[f'ob_{slot}_mitigated']:
            assert row[f'ob_{slot}_mitigation_pct'] == 1.0, \
                f'row {i} slot {slot}: mitigated but pct={row[f\"ob_{slot}_mitigation_pct\"]}'

# (c) The first OB detected by v1 in a slice should be detected by v2
# Find the first v1 ob_active row
v1_first = df_v1[df_v1['ob_active']].index[0]
v1_first_ts = df_v1.iloc[v1_first]['open_time']
# In a 50-bar window around v1_first, v2 should also have an ob_active
window = df_v2[(df_v2['open_time'] >= v1_first_ts - pd.Timedelta('4h'))
             & (df_v2['open_time'] <= v1_first_ts + pd.Timedelta('4h'))]
assert window['ob_active'].any(), \
    f'v1 detected OB at {v1_first_ts}, v2 missed within ±4h window'

# (d) Impulse quality distribution
qualities = []
for slot in range(5):
    qcol = f'ob_{slot}_impulse_quality'
    if qcol in df_v2.columns:
        qualities.extend(df_v2[qcol].dropna().tolist())
from collections import Counter
qdist = Counter(qualities)
print(f'impulse quality distribution: {dict(qdist)}')
assert qdist.get('A', 0) > 0, 'expected some A-grade OBs (large displacement)'
assert qdist.get('C', 0) > 0, 'expected some C-grade OBs (weak displacement)'

# (e) ob_zone_count ∈ {0..5} always
assert df_v2['ob_zone_count'].max() <= 5, 'ob_zone_count exceeds MAX_ZONES'
assert df_v2['ob_zone_count'].min() >= 0, 'ob_zone_count negative'

print('OK: order_blocks.py parity + mitigation ledger')
"
```

**Pass criteria**:
- `(a)` is the regression gate.
- `(b)` is a contract check.
- `(c)` is a specific regression: v1's first OB in a window must be found by v2. If v2 missed it, the BOS validation or impulse detection is wrong.
- `(d)` checks the quality grading works — if all OBs are grade B, the displacement thresholds need tuning. A and C are needed for the validator to have something to test.
- `(e)` checks the slot count.

### Combined Phase 2 smoke test

```bash
cd backend && python -c "
import pandas as pd
from app.core.smc.sessions import stamp_sessions, compute_session_ranges
from app.core.smc.swings   import extract_swings
from app.core.smc.mtf      import build_htf_alignment
from app.core.smc.structure import extract_structure
from app.core.smc.fvgs      import extract_fvgs
from app.core.smc.order_blocks import extract_order_blocks
from app.core.data_utils    import get_finalized_candles

df = get_finalized_candles('BTCUSDT', '15m', limit=500)
df_1h  = get_finalized_candles('BTCUSDT', '1h',  limit=120)
df_4h  = get_finalized_candles('BTCUSDT', '4h',  limit=30)
df_1d  = get_finalized_candles('BTCUSDT', '1d',  limit=10)

df = stamp_sessions(df); df = compute_session_ranges(df)
df = extract_swings(df)
df = build_htf_alignment(df, {'1h': df_1h, '4h': df_4h, '1d': df_1d})
df = extract_structure(df)
df = extract_fvgs(df)
df = extract_order_blocks(df)

# Check all expected new columns from Phase 2
expected = [
    'struct_internal_event', 'struct_swing_event', 'struct_mss',
    'struct_trend_internal', 'struct_trend_swing', 'struct_trend_maturity',
    'fvg_active', 'fvg_zone_count', 'fvg_fill_pct',
    'fvg_0_active', 'fvg_0_fill_pct', 'fvg_0_fill_at',
    'ob_active', 'ob_zone_count',
    'ob_0_active', 'ob_0_mitigated', 'ob_0_mitigated_at', 'ob_0_mitigation_pct',
    'ob_0_impulse_quality',
]
for c in expected:
    assert c in df.columns, f'MISSING: {c}'

# Quick sanity: there should be SOME events
print(f'struct_swing_event non-null: {df[\"struct_swing_event\"].notna().sum()}/500')
print(f'fvg_active True: {df[\"fvg_active\"].sum()}/500')
print(f'ob_active True: {df[\"ob_active\"].sum()}/500')
assert df['struct_swing_event'].notna().sum() > 0, 'no swing events in 500 bars'
assert df['fvg_active'].sum() > 0, 'no FVG-active bars in 500 bars'
print('OK: Phase 2 modules integrate on real BTC 15m data')
"
```

**Pass criteria**: all 15 expected new columns present, at least some events detected in 500 bars (we expect ~30-60 swing events and ~80-150 FVG-active bars in 500 15m bars of BTC).

## Final Deliverable

- `structure.py` — passes parity backtest (no regression vs v1), 5 event types + MSS.
- `fvgs.py` — multi-slot FVG with `fill_pct` ∈ [0, 1], monotonically non-decreasing.
- `order_blocks.py` — multi-slot OB with explicit `mitigated`/`mitigated_at`/`mitigation_pct` ledger, A/B/C impulse grading.
- No new lookahead bugs introduced (parity backtest is the regression guard).

## Next Phase

→ [Phase 3: Liquidity + Bias + Premium/Discount](./phase-3-liquidity-bias-pd.md) — the net-new modules that close the spec gaps.
