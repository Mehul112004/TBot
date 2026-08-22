# Phase 4: Engine Orchestrator — context.py, engine.py

> **Future SMC v2 design.** This phase plan is not a record of completed runtime modules; see [the SMC design status](README.md).

## Goal

Wire the 8 modules from Phases 1-3 into a single public API: `run_smc_analysis(df_15m, htf_data) -> df_enriched`. Also produce a per-bar `SMContext` frozen dataclass that strategies consume for clean, immutable per-bar reads.

After this phase, calling `run_smc_analysis` should return a fully enriched DataFrame in a single call, with all the columns the live strategies and the `/api/smc/engine` endpoint need.

## Files Created

| File | LOC (est.) | Purpose |
|---|---|---|
| `backend/app/core/smc/context.py` | ~120 | `SMContext` frozen dataclass + per-bar builder |
| `backend/app/core/smc/engine.py`  | ~150 | `run_smc_analysis()` orchestrator |

## Tasks

### 4.1 `context.py` — Per-Bar Snapshot

The `SMContext` is the public interface strategies consume. It is a **frozen** dataclass — once built for bar `i`, it cannot be mutated. This prevents strategies from accidentally reading-and-mutating state, which is a class of bug that has burned me in the past.

#### Definition

```python
@dataclass(frozen=True)
class SMContext:
    """
    Per-bar Smart Money Concepts snapshot. Frozen.
    Built from a row of the enriched DataFrame produced by run_smc_analysis().
    """
    # Identity
    timestamp: pd.Timestamp
    symbol: str
    timeframe: str

    # Sessions (from sessions.py)
    session: str             # {asian, london_kz, london_cont, ny_kz, ny_am, ny_pm, off}
    is_kill_zone: bool
    session_high: float | None
    session_low: float | None
    session_complete: bool

    # Swings (from swings.py)
    swing_trend: int              # {-1, 0, 1}  (from struct_trend_swing)
    internal_trend: int           # {-1, 0, 1}  (from struct_trend_internal)
    last_swing_high: float | None
    last_swing_high_confirmed_at: int | None
    last_swing_low: float | None
    last_swing_low_confirmed_at: int | None

    # Structure (from structure.py)
    struct_swing_event: str | None     # {SBOS_UP, SBOS_DOWN, SCHOCH_UP, SCHOCH_DOWN, None}
    struct_internal_event: str | None
    struct_mss: str | None             # {MSS_UP, MSS_DOWN, None}

    # FVGs (from fvgs.py)
    active_fvgs: tuple[FVGZone, ...]   # up to 5, sorted by distance to close
    nearest_fvg: FVGZone | None
    nearest_fvg_distance_atr: float | None

    # OBs (from order_blocks.py)
    active_obs: tuple[OBZone, ...]
    nearest_ob: OBZone | None
    nearest_ob_distance_atr: float | None

    # Liquidity (from liquidity.py)
    nearest_buy_side: float | None    # nearest buy-side liquidity target above
    nearest_sell_side: float | None   # nearest sell-side liquidity target below
    pdl: float | None; pdh: float | None
    pwl: float | None; pwh: float | None
    eqh: float | None; eql: float | None
    last_sweep: SweepEvent | None

    # Bias (from bias.py)
    weekly_bias: str          # {bull, bear, neutral}
    daily_bias: str           # {bull, bear, neutral, tentative_bull, tentative_bear}
    bias_confirmed: bool

    # Premium/Discount (from premium_discount.py)
    pd_zone: str              # {premium, equilibrium, discount}
    equilibrium: float | None
    range_high: float | None
    range_low: float | None
```

The `FVGZone`, `OBZone`, and `SweepEvent` are also frozen dataclasses (defined in their respective modules). They carry `slot`, `direction`, `upper`, `lower`, `fill_pct` / `mitigation_pct`, etc.

#### Per-bar builder

```python
def smc_context_from_row(row: pd.Series, symbol: str, timeframe: str) -> SMContext:
    """
    Build an SMContext from a single row of the enriched DataFrame.
    Pure function: same row in => same context out. No global state, no I/O.
    """
```

The function reads from row columns (which were set by `run_smc_analysis`). It is **purely a column-to-dataclass translator** — no logic, no validation. If a column is missing, the field is `None` (or 0 for trend fields, 'unknown' for session fields). This means a strategy can iterate over an enriched DataFrame and call `smc_context_from_row` per row without side effects.

### 4.2 `engine.py` — The Orchestrator

This is the public entry point. It runs all 8 modules in dependency order, returning a single enriched DataFrame.

#### Pipeline order (locked)

```python
def run_smc_analysis(
    df: pd.DataFrame,
    htf_data: Dict[str, pd.DataFrame] | None = None,
    symbol: str = '',
    timeframe: str = '15m',
) -> pd.DataFrame:
    """
    The single public entry point for the SMC engine.

    Pipeline (each module is pure df in -> df out):

        1. mtf.build_htf_alignment        (adds htf_*_close/high/low/trended)
        2. sessions.stamp_sessions        (adds session, is_kill_zone, session_idx)
        3. sessions.compute_session_ranges (adds session_high/low/range/complete)
        4. swings.extract_swings          (adds swing_*, internal_*, swing_label)
        5. structure.extract_structure    (adds struct_*_event, struct_*_trend)
        6. fvgs.extract_fvgs              (adds fvg_* and per-slot columns)
        7. order_blocks.extract_order_blocks (adds ob_* and per-slot columns)
        8. liquidity.extract_liquidity    (adds liq_*, event_sweep_*)
        9. bias.compute_bias              (adds smc_*_bias, smc_bias_confirmed)
       10. premium_discount.compute_premium_discount (adds pd_*)

    Args:
        df: primary LTF DataFrame (15m), with at least
            open_time, open, high, low, close, volume columns
        htf_data: dict mapping timeframe string to DataFrame for HTFs.
                  Default = {'1h': df_1h, '4h': df_4h, '1d': df_1d} for 15m
                  operating TF. For other operating TFs, the caller should
                  pass appropriate HTFs.
        symbol: symbol for context (used in SMContext)
        timeframe: operating TF (default '15m')

    Returns:
        The same df, enriched with all 80+ SMC columns. No DB writes.
    """
    htf_data = htf_data or _auto_fetch_htf(symbol, timeframe)  # see note below
    df = df.copy()

    df = mtf.build_htf_alignment(df, htf_data)
    df = sessions.stamp_sessions(df)
    df = sessions.compute_session_ranges(df)
    df = swings.extract_swings(df)
    df = structure.extract_structure(df)
    df = fvgs.extract_fvgs(df)
    df = order_blocks.extract_order_blocks(df)
    df = liquidity.extract_liquidity(df, htf_data)
    df = bias.compute_bias(df, htf_data)
    df = premium_discount.compute_premium_discount(df)

    return df
```

#### The `_auto_fetch_htf` helper (with caching)

The default for `htf_data` is to fetch from the DB via `get_finalized_candles`. For a 15m operating TF, the HTFs are 1H, 4H, 1D. For other operating TFs, the HTF ladder is:

| Operating TF | HTF stack (auto) |
|---|---|
| 1m, 3m, 5m | 15m, 1h, 4h |
| 15m, 30m | 1h, 4h, 1d |
| 1h, 2h, 4h | 4h, 1d, 1w |
| 1d | 1w, 1w (only 2 HTFs) |

The helper:

```python
_HTF_LADDER = {
    '1m':  ['15m', '1h', '4h'],
    '3m':  ['15m', '1h', '4h'],
    '5m':  ['15m', '1h', '4h'],
    '15m': ['1h', '4h', '1d'],
    '30m': ['1h', '4h', '1d'],
    '1h':  ['4h', '1d', '1w'],
    '2h':  ['4h', '1d', '1w'],
    '4h':  ['1d', '1w', '1w'],
    '1d':  ['1w', '1w', '1w'],
    # 3d, 1w not supported as operating TF in this engine
}

def _auto_fetch_htf(symbol: str, timeframe: str) -> Dict[str, pd.DataFrame]:
    htf_tfs = _HTF_LADDER.get(timeframe, ['1h', '4h', '1d'])
    return {tf: get_finalized_candles(symbol, tf, limit=200) for tf in htf_tfs}
```

**Caching**: the engine does **not** cache `htf_data` internally. The caller is responsible for caching if the same `(symbol, timeframe)` is being processed in a tight loop. (This is intentional — the engine is a pure function, not a service.)

#### Module load order (for `__init__.py`)

`backend/app/core/smc/__init__.py` exposes:

```python
from .engine import run_smc_analysis
from .context import SMContext, smc_context_from_row
from . import mtf, swings, sessions, structure, fvgs, order_blocks, liquidity, bias, premium_discount
```

Phase 4 replaces the placeholder `__init__.py` from Phase 0 with the real one. After this, `from app.core.smc import run_smc_analysis` works from anywhere.

## Manual Verification

### Verify 4.1 — `SMContext` builder

```bash
cd backend && python -c "
import pandas as pd
from app.core.smc.engine import run_smc_analysis
from app.core.smc.context import SMContext, smc_context_from_row
from app.core.data_utils import get_finalized_candles

df = get_finalized_candles('BTCUSDT', '15m', limit=200)
df_enriched = run_smc_analysis(df, symbol='BTCUSDT', timeframe='15m')
print(f'enriched columns: {len(df_enriched.columns)} (was {len(df.columns)})')
assert len(df_enriched.columns) >= 80, f'expected 80+ cols, got {len(df_enriched.columns)}'

# Build a context from the last row
ctx = smc_context_from_row(df_enriched.iloc[-1], symbol='BTCUSDT', timeframe='15m')

# (a) Context is a SMContext
assert isinstance(ctx, SMContext), f'expected SMContext, got {type(ctx)}'

# (b) Context is FROZEN
try:
    ctx.session = 'hacked'
    assert False, 'frozen dataclass should not allow attribute assignment'
except (AttributeError, dataclasses.FrozenInstanceError):
    print('  frozen OK')

# (c) All fields populated (no None that shouldn't be)
assert ctx.symbol == 'BTCUSDT'
assert ctx.timeframe == '15m'
assert isinstance(ctx.timestamp, pd.Timestamp)
assert ctx.session in {'asian', 'london_kz', 'london_cont', 'ny_kz', 'ny_am', 'ny_pm', 'off'}
assert ctx.swing_trend in {-1, 0, 1}
assert ctx.internal_trend in {-1, 0, 1}
assert ctx.weekly_bias in {'bull', 'bear', 'neutral'}
assert ctx.daily_bias in {'bull', 'bear', 'neutral', 'tentative_bull', 'tentative_bear'}
assert ctx.pd_zone in {'premium', 'equilibrium', 'discount'}

# (d) active_fvgs and active_obs are tuples (immutable)
assert isinstance(ctx.active_fvgs, tuple), f'active_fvgs should be tuple, got {type(ctx.active_fvgs)}'
assert isinstance(ctx.active_obs, tuple), f'active_obs should be tuple, got {type(ctx.active_obs)}'

# (e) Iterate the DataFrame, build a context per row, verify all builds succeed
n_fail = 0
for i in range(len(df_enriched)):
    try:
        smc_context_from_row(df_enriched.iloc[i], 'BTCUSDT', '15m')
    except Exception as e:
        n_fail += 1
        if n_fail <= 3:
            print(f'row {i} FAILED: {e}')
assert n_fail == 0, f'{n_fail} rows failed to build SMContext'
print('OK: SMContext builder works for all 200 rows')
"
```

**Pass criteria**:
- The enriched DataFrame has 80+ columns.
- `SMContext` is frozen (you cannot assign to its fields).
- All categorical fields have values in the expected sets.
- `active_fvgs` and `active_obs` are tuples, not lists (immutability).
- 200/200 rows build successfully.

### Verify 4.2 — `engine.run_smc_analysis` end-to-end

```bash
cd backend && python -c "
import pandas as pd
import time
from app.core.smc.engine import run_smc_analysis
from app.core.data_utils import get_finalized_candles

# (a) Single-symbol, single-TF, no explicit htf_data (auto-fetch)
df = get_finalized_candles('BTCUSDT', '15m', limit=1000)
t0 = time.time()
df_enr = run_smc_analysis(df, symbol='BTCUSDT', timeframe='15m')
elapsed = time.time() - t0
print(f'1000 bars: {elapsed:.2f}s, enriched cols: {len(df_enr.columns)}')
assert elapsed < 5.0, f'engine too slow: {elapsed:.2f}s for 1000 bars'
assert len(df_enr.columns) >= 80

# (b) Explicit htf_data
df_1h  = get_finalized_candles('BTCUSDT', '1h',  limit=200)
df_4h  = get_finalized_candles('BTCUSDT', '4h',  limit=200)
df_1d  = get_finalized_candles('BTCUSDT', '1d',  limit=200)
t0 = time.time()
df_enr2 = run_smc_analysis(df, htf_data={'1h': df_1h, '4h': df_4h, '1d': df_1d},
                            symbol='BTCUSDT', timeframe='15m')
elapsed = time.time() - t0
print(f'1000 bars + explicit htf: {elapsed:.2f}s')
assert elapsed < 5.0

# (c) Output is the same shape as input (no rows added/removed)
assert len(df_enr) == len(df), f'rows added/removed: was {len(df)}, now {len(df_enr)}'
assert all(df_enr['open_time'] == df['open_time']), 'open_time column changed'

# (d) All Phase 1-3 columns are present
for col in [
    'session', 'is_kill_zone', 'session_idx',           # Phase 1: sessions
    'swing_high', 'swing_label', 'internal_high',      # Phase 1: swings
    'htf_1h_close', 'htf_4h_close', 'htf_1d_close',    # Phase 1: mtf
    'struct_swing_event', 'struct_mss',                 # Phase 2: structure
    'fvg_active', 'fvg_fill_pct', 'fvg_zone_count',     # Phase 2: fvgs
    'ob_active', 'ob_zone_count', 'ob_0_mitigated',     # Phase 2: obs
    'liq_pdh', 'liq_pdl', 'liq_eqh_price',              # Phase 3: liquidity
    'event_sweep_pdh', 'event_sweep_pdl',               # Phase 3: sweeps
    'smc_weekly_bias', 'smc_daily_bias',                # Phase 3: bias
    'pd_zone', 'pd_equilibrium',                        # Phase 3: premium/discount
]:
    assert col in df_enr.columns, f'MISSING from engine output: {col}'

# (e) Idempotency: running the engine twice on the same input gives the same output
df_enr3 = run_smc_analysis(df, htf_data={'1h': df_1h, '4h': df_4h, '1d': df_1d},
                            symbol='BTCUSDT', timeframe='15m')
# All numeric columns should match
for col in df_enr.select_dtypes(include='number').columns:
    if col in df_enr3.columns:
        diff = (df_enr[col] - df_enr3[col]).abs()
        # Allow floating point noise
        non_null_diff = diff[df_enr[col].notna() & df_enr3[col].notna()]
        if len(non_null_diff) > 0:
            max_diff = non_null_diff.max()
            assert max_diff < 1e-9, f'engine not idempotent on {col}: max diff {max_diff}'

print('OK: engine.run_smc_analysis end-to-end')
"
```

**Pass criteria**:
- 1000 bars process in < 5 seconds.
- Explicit `htf_data` and auto-fetched `htf_data` produce equivalent outputs (the difference should be only the LIMIT of the auto-fetched HTFs).
- No rows are added/removed; `open_time` is preserved.
- All 20+ columns from Phases 1-3 are present.
- **Idempotency**: running the engine twice on the same input gives numerically identical output. This is a hard correctness check — if the engine is non-idempotent, something is reading from mutable global state.

### Verify 4.3 — Pipeline performance on full 2-year dataset

```bash
cd backend && python -c "
import pandas as pd
import time
from app.core.smc.engine import run_smc_analysis
from app.core.data_utils import get_finalized_candles

# Full 2-year BTC 15m = ~70k bars
df = get_finalized_candles('BTCUSDT', '15m', limit=70_000)
df_1h  = get_finalized_candles('BTCUSDT', '1h',  limit=20_000)
df_4h  = get_finalized_candles('BTCUSDT', '4h',  limit=5_000)
df_1d  = get_finalized_candles('BTCUSDT', '1d',  limit=1_000)
print(f'input: {len(df)} 15m bars, {len(df_1h)} 1h, {len(df_4h)} 4h, {len(df_1d)} 1d')

t0 = time.time()
df_enr = run_smc_analysis(df, htf_data={'1h': df_1h, '4h': df_4h, '1d': df_1d},
                           symbol='BTCUSDT', timeframe='15m')
elapsed = time.time() - t0
print(f'full 2y: {elapsed:.1f}s for {len(df_enr)} bars')
assert elapsed < 30.0, f'too slow for live use: {elapsed:.1f}s'

# Memory sanity
import sys
print(f'enriched df memory: {df_enr.memory_usage(deep=True).sum() / 1e6:.1f} MB')
"
```

**Pass criteria**:
- Full 2-year BTC 15m processes in < 30 seconds. The `/api/smc/engine` endpoint is expected to run this on every chart load, so 30s is the upper bound. If it's > 30s, we have a performance problem that needs a fix before Phase 6 (integration).

If the engine is too slow, the most likely culprit is `liquidity.extract_liquidity` doing a per-row O(n) scan for sweep events. Fix: pre-compute the array of liquidity levels once and broadcast.

## Final Deliverable

- `context.py` — `SMContext` frozen dataclass, `smc_context_from_row` builder.
- `engine.py` — `run_smc_analysis` orchestrator with the locked 10-step pipeline, `_auto_fetch_htf` helper, `_HTF_LADDER` constant.
- `__init__.py` — replaces the Phase 0 stub with the real public API.
- All 80+ SMC columns produced in a single `run_smc_analysis` call.
- Idempotent, < 5s on 1000 bars, < 30s on 2 years of 15m data.

## Next Phase

→ [Phase 5: Validators](./phase-5-validators.md) — the ship gate. Lookahead audit, IC tests, walk-forward, regime coverage.
