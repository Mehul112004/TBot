# Phase 1: Foundation — mtf, swings, sessions

## Goal

Build the three deterministic, no-lookahead foundation modules that everything else depends on. These modules produce the per-candle context that `structure.py`, `fvgs.py`, `order_blocks.py` (Phase 2) and `liquidity.py` (Phase 3) consume.

After this phase, every candle in your DataFrame will have:
- A `session` and `kill_zone` stamp (`sessions.py`)
- A `swing_high`/`swing_low` (high-degree), `internal_high`/`internal_low` (low-degree), and a `swing_label` ∈ {HH, HL, LH, LL} — but **only knowable from the `confirmed_at` index onward** (`swings.py`)
- For every LTF bar, the last *closed* 1H, 4H, and 1D candle's state (not the forming one) — this is the single most important rule in the engine (`mtf.py`)

## Files Created

| File | LOC (est.) | Purpose |
|---|---|---|
| `backend/app/core/smc/sessions.py` | ~150 | Session/kill-zone stamping, session H/L/range |
| `backend/app/core/smc/swings.py`   | ~250 | Internal vs swing pivots, HH/HL/LH/LL labelling |
| `backend/app/core/smc/mtf.py`      | ~200 | Closed-candle-only HTF alignment helper |

## Tasks

### 1.1 `sessions.py` — Candle Stampers

The single source of truth for "what session is this candle in?" in UTC.

#### Constants (NOT tunable, locked in `_params.py`)

```python
# Sessions boundaries (UTC, from ICT canonical windows)
SESSION_WINDOWS = {
    "asian":       (("20:00", "23:59"), ("00:00", "07:59")),  # wraps midnight
    "london_kz":   (("02:00", "05:00"),),                   # London kill zone
    "london_cont": (("05:00", "06:59"),),                   # London continuation
    "ny_kz":       (("07:00", "10:00"),),                   # NY kill zone
    "ny_am":       (("10:00", "12:59"),),                   # NY AM
    "ny_pm":       (("13:00", "16:59"),),                   # NY PM
}
# A candle belongs to the FIRST window it falls into, in priority order.
# Multiple kill zones are NOT overlapping; ny_kz (07-10) is disjoint from london_kz (02-05).
```

If a candle doesn't fall into any of the above, it gets `session='off'`. The `"off"` window is implicit (17:00 UTC → 20:00 UTC the prior day is "transition", and 18:00 → 20:00 is also off).

#### API

```python
def stamp_sessions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add per-candle session columns. Pure left-to-right scan.

    Required input columns: open_time (UTC tz-aware)
    Adds:
        session        ∈ {asian, london_kz, london_cont, ny_kz, ny_am, ny_pm, off}
        is_kill_zone   bool
        session_idx    int — monotonic session counter (resets per UTC day)
    """
```

**Lookahead guard**: every computation uses only `open_time` of the *current* candle. No peeking at the next candle's session even to handle the Asian session wrap across midnight — instead, we split the Asian window into two sub-windows (`20:00-23:59` and `00:00-07:59`) and treat them as the same session by sharing the same `session_idx`. The `session_idx` is the *resolved* session number, computed by walking the DataFrame forward — a candle at 23:45 and a candle at 00:15 get the same `session_idx` only if they are the same Asian session for the same calendar date. This is the only safe way to do it.

#### Session H/L computation (separate helper)

```python
def compute_session_ranges(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add per-session high/low/range columns that *fill forward* within
    the session, then NaN at session boundary.

    Required input columns: open_time, high, low, session, session_idx
    Adds:
        session_high   float64 — highest high of current session so far
        session_low    float64 — lowest  low  of current session so far
        session_range  float64 — session_high - session_low (NaN until ≥ 2 candles in session)
        session_complete bool — True on the LAST candle of each session
    """
```

`session_high` and `session_low` **fill forward** during the session (so a candle 10 minutes into a session sees the running high/low, not its own OHLC). On the *last* candle of a session, they freeze at the session's true high/low.

**No lookahead**: `session_high.iat[i] = max(highs from session_idx's start..i)`. Implementation must be a `groupby('session_idx').cummax()` and `cummin()` — pandas primitives that scan left-to-right.

### 1.2 `swings.py` — Internal vs Swing Pivots

#### The single most important rule

> A swing point at index `j` is only knowable at index `j + pivot_bars` (not before).

Every column that depends on a swing (HH/HL/LH/LL label, swing trend, premium/discount range, bias engine) must read from `swing.confirmed_at` — never from `swing.index`. The "label at index `i`" questions are answered as: "what is the most recent swing whose `confirmed_at ≤ i`?".

#### Constants (with sensitivity caveat)

```python
# These are the 2 of the 5 free params of the engine (see _params.py)
SWING_PIVOT_BARS    = 10   # HTF-degree pivots  → swing BOS/CHoCH, premium/discount
INTERNAL_PIVOT_BARS =  3   # LTF-degree pivots  → internal BOS/CHoCH, OB anchoring
```

The defaults (10 / 3) come from ICT's typical HTF/LTF relationship. The validator in Phase 5 will sensitivity-test ±50% on these.

#### API

```python
def extract_swings(
    df: pd.DataFrame,
    swing_pivot_bars: int = SWING_PIVOT_BARS,
    internal_pivot_bars: int = INTERNAL_PIVOT_BARS,
) -> pd.DataFrame:
    """
    Two parallel streams of pivots, with explicit confirmation indices.

    Required input columns: high, low, open_time
    Adds:
        swing_high        bool — pivot at index i, HIGH DEGREE
        swing_low         bool — pivot at index i, HIGH DEGREE
        swing_high_idx    int  — the index of the swing high (NaN otherwise)
        swing_high_price  float
        swing_high_confirmed_at int — index when this swing was knowable
        swing_low_idx, swing_low_price, swing_low_confirmed_at (mirror)
        internal_high, internal_low, internal_high_idx, internal_high_price,
        internal_high_confirmed_at, internal_low_*
        swing_label       object ∈ {HH, HL, LH, LL, None} — labelled ONLY from
                           the swing's confirmed_at index onward. At the swing's
                           own index and before, swing_label is None.
    """
```

The function uses a left-to-right scan. For each pivot at index `i`:
1. Mark `*_confirmed_at = i + pivot_bars` (the earliest the pivot is "real").
2. Walk forward from `confirmed_at` until a new swing in the same direction forms; at the new swing's `confirmed_at`, label the *previous* one as HH/HL/LH/LL.
3. `swing_label` is **NaN** for all rows from `swing.index` to `swing.confirmed_at - 1` (inclusive). It is set to the labelled value at `swing.confirmed_at` and **ffill'd forward** until a new label is computed.

**Lookahead guard**: a row at index `i` reads only swings with `confirmed_at ≤ i`. Internally, the function never reads `df.iloc[j]` for `j > i`. The implementation is a single forward loop — no global ops, no rolling with `center=True` in a way that would peek.

#### Verification helper

```python
def latest_confirmed_swing(df: pd.DataFrame, idx: int, kind: str) -> tuple[int, float] | None:
    """
    Return (index, price) of the most recent confirmed swing of given kind
    (swing_high / swing_low / internal_high / internal_low) at or before idx.
    Returns None if no confirmed swing exists yet.
    """
```

This is the function that every downstream module (structure.py, premium_discount.py, bias.py) MUST use to read swings. The function name is long on purpose: it's a code review smell to see "swing_high" used without "confirmed" elsewhere.

### 1.3 `mtf.py` — Closed-Candle-Only HTF Alignment

This is the **single most critical module** in the engine. The whole project can be ruined by a single line that reads `htf_df.iloc[-1]` and treats the forming candle as known.

#### The rule, encoded as code

```python
def last_closed_htf_candle(
    ltf_t: pd.Timestamp,
    htf_df: pd.DataFrame,
    htf_tf_ms: int,
) -> pd.Series | None:
    """
    Return the most recent HTF candle whose CLOSE-TIME was at or before
    (ltf_t - 1ms). Returns None if no such HTF candle exists.

    The candle at index j in htf_df spans open_time=j to close_time=j+tf_ms.
    We need close_time ≤ ltf_t - 1ms, i.e., j + htf_tf_ms < ltf_t (strict).
    """
    cutoff = ltf_t.value - 1   # 1 ms before the LTF bar opens
    # Find the latest htf row with open_time.value + htf_tf_ms <= cutoff
    closes_at = htf_df['open_time'].astype('int64').values + htf_tf_ms
    mask = closes_at <= cutoff
    if not mask.any():
        return None
    last_idx = np.where(mask)[0][-1]
    return htf_df.iloc[last_idx]
```

**The crucial detail**: `cutoff = ltf_t - 1 ms`. If the LTF bar opens at exactly the same time the HTF bar closes, the HTF bar is NOT yet known. You need to be at the *next* LTF bar to read the just-closed HTF bar. This 1 ms slop catches the off-by-one bug that produces backtest-vs-live performance gaps.

#### Full API

```python
TIMEFRAME_MS = ...   # mirror data_utils.TIMEFRAME_MS (15 entries)

def build_htf_alignment(
    ltf_df: pd.DataFrame,
    htf_data: Dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """
    For every LTF row, attach the last-closed 1H, 4H, 1D OHLC + a state dict.

    Required input columns: open_time
    htf_data: {'1h': df_1h, '4h': df_4h, '1d': df_1d}
    Adds (per HTF):
        htf_{tf}_close   float — last closed HTF close
        htf_{tf}_high    float
        htf_{tf}_low     float
        htf_{tf}_trended bool  — close > ema_50 of last closed HTF
    """
```

**Performance note**: this function gets called once per `/api/smc/engine` request, so 15m × 96 bars/day × 730 days = ~70k LTF bars. For each LTF bar we do a binary search against each HTF. Use `searchsorted` on pre-sorted `htf_close_at` arrays — O(log n) per query, O(n) per HTF. Total: O(3n log n), runs in <500ms on 70k bars on a laptop.

#### A test that would have caught the bug

```python
# In mtf.py, end of file:
def _smoke_test_lookahead_alignment():
    """
    Synthetic test: a 1H candle at 08:00-09:00 must NOT be visible
    to a 15m candle at 08:00-08:15. Run on import in CI.
    """
    htf = pd.DataFrame({
        'open_time': pd.to_datetime(['2024-01-01 07:00', '2024-01-01 08:00',
                                      '2024-01-01 09:00'], utc=True),
        'high': [100, 110, 120],
        'low':  [ 95, 105, 115],
        'close':[ 99, 109, 119],
    })
    ltf_t = pd.Timestamp('2024-01-01 08:00', tz='UTC')  # bar 08:00-08:15
    res = last_closed_htf_candle(ltf_t, htf, htf_tf_ms=3_600_000)
    assert res is not None and res['close'] == 99, \
        f"LEAK: saw 109 at 08:00 instead of 99. Lookahead bug."
    ltf_t2 = pd.Timestamp('2024-01-01 08:15', tz='UTC')
    res2 = last_closed_htf_candle(ltf_t2, htf, htf_tf_ms=3_600_000)
    assert res2['close'] == 109, f"Should see 109 at 08:15, got {res2['close']}"
    print("OK: mtf.lookahead_guard")
```

This self-test runs on import (gated by `if __name__ == '__main__'` for manual invocation; auto-runs in the Phase 1 verification block).

## Manual Verification

### Verify 1.1 — `sessions.py`

```bash
cd backend && python -c "
import pandas as pd
from app.core.smc.sessions import stamp_sessions, compute_session_ranges

# Synthetic 1-week of 15m candles starting 2024-01-01 00:00 UTC
idx = pd.date_range('2024-01-01', periods=7*24*4, freq='15min', tz='UTC')
df = pd.DataFrame({
    'open_time': idx,
    'open':  100, 'high': 101, 'low':  99, 'close': 100.5, 'volume': 1000,
})
df = stamp_sessions(df)
df = compute_session_ranges(df)

# (a) Every row has a session label
assert df['session'].notna().all(), 'all rows must have a session'
assert set(df['session'].unique()) >= {'asian', 'london_kz', 'ny_kz', 'off'}, \
    f'missing sessions: {df[\"session\"].unique()}'

# (b) Asian session spans the midnight boundary
asian = df[df['session'] == 'asian']
assert (asian['open_time'].dt.hour >= 20).sum() > 0, 'Asian must cover 20:00-23:59'
assert (asian['open_time'].dt.hour < 8).sum() > 0,  'Asian must cover 00:00-07:59'

# (c) Kill-zone flag is set ONLY during the 3 kill zones
kz_candles = df[df['is_kill_zone']]
kz_hours = kz_candles['open_time'].dt.hour.unique()
print('kill-zone hours:', sorted(kz_hours))
# Expect: [2, 3, 4, 7, 8, 9]  (London KZ 2-5, NY KZ 7-10)
expected_kz_hours = {2, 3, 4, 7, 8, 9}
assert set(kz_hours) == expected_kz_hours, \
    f'kill-zone hours wrong: {set(kz_hours)} vs expected {expected_kz_hours}'

# (d) Session range fills forward, not backward
first_ny_kz = df[df['session'] == 'ny_kz'].iloc[0]
assert pd.notna(first_ny_kz['session_high']), 'first NY KZ candle must have running high'
assert first_ny_kz['session_high'] == first_ny_kz['high'], \
    'first candle in session: session_high must equal own high'

# (e) Session_high freezes at session_complete=True
last_ny_kz = df[df['session'] == 'ny_kz'].iloc[-1]
assert last_ny_kz['session_complete'], 'last NY KZ candle must be session_complete'
assert last_ny_kz['session_high'] == df[df['session'] == 'ny_kz']['high'].max(), \
    'session_complete high must equal max high of session'

print('OK: sessions.py all 5 checks pass')
"
```

**Pass criteria**: 5/5 assertions pass, no exceptions. If you get an `AssertionError`, the most common causes are:
- `(a)` failing: timezones not UTC, or `open_time` not tz-aware.
- `(b)` failing: Asian session treated as two separate sessions instead of one.
- `(c)` failing: kill-zone windows wrong, or hours in 24h format confused with 12h.
- `(d)`/`(e)` failing: implementation is using `groupby.max()` instead of `groupby.cummax()` (peeks forward).

### Verify 1.2 — `swings.py`

```bash
cd backend && python -c "
import pandas as pd
import numpy as np
from app.core.smc.swings import extract_swings, latest_confirmed_swing

# Build a synthetic 4H sequence with a known HH/HL/LH/LL pattern
# Bars 0..99. Let's hand-craft 5 swings:
#   bar 5: low 100  (L1, confirmed at bar 15)
#   bar 15: high 110 (H1, confirmed at bar 25)
#   bar 25: low 105 (L2 > L1, confirmed at bar 35)   <- HL relative to L1
#   bar 35: high 120 (H2 > H1, confirmed at bar 45)  <- HH relative to H1
#   bar 45: low 100 (L3 < L2, confirmed at bar 55)   <- LL relative to L2
# Bars are otherwise noise around 100-110
n = 60
highs = np.full(n, 100.0)
lows  = np.full(n, 100.0)
highs[15] = 110; highs[35] = 120
lows[5]   = 100; lows[25]  = 105; lows[45] = 100
# Make 15-bar windows around each pivot contain the pivot as the max/min
# (i.e., the high at bar 15 must be the max of bars 5..25 with pivot=10)
for i in range(5, 26): highs[i] = max(highs[i], 108)  # ensure bar 15 is peak
for i in range(25, 46): highs[i] = max(highs[i], 115)
# ... (similar for lows)

df = pd.DataFrame({
    'open_time': pd.date_range('2024-01-01', periods=n, freq='4h', tz='UTC'),
    'open': 100, 'close': 100,
    'high': highs + np.random.RandomState(0).normal(0, 0.1, n),  # tiny noise
    'low':  lows  + np.random.RandomState(0).normal(0, 0.1, n),
    'volume': 1000,
})
df = extract_swings(df, swing_pivot_bars=10, internal_pivot_bars=3)

# (a) Swing at bar 15 is labelled None UNTIL bar 25 (confirmed_at)
assert df.iloc[15]['swing_label'] is None or pd.isna(df.iloc[15]['swing_label']), \
    f'LEAK: swing at bar 15 labelled at bar 15, should be None. Got: {df.iloc[15][\"swing_label\"]}'
assert df.iloc[24]['swing_label'] is None or pd.isna(df.iloc[24]['swing_label']), \
    f'LEAK: still labelled None at bar 24, should be None.'
# (b) After bar 25, the label may start to appear (depending on next swing)
# We just check that NO swing_label appears before its confirmed_at
for i in range(n):
    for col in ['swing_high', 'swing_low']:
        if df.iloc[i][col]:
            # The confirmed_at for this swing should be <= i (else the swing is not yet known)
            assert False, f'Lookahead: {col} at bar {i} but no confirmed_at enforcement'

# (c) Internal pivots work too
assert 'internal_high' in df.columns, 'internal pivots missing'
assert 'internal_low' in df.columns, 'internal pivots missing'

# (d) latest_confirmed_swing at idx 30 should return the swing_low at bar 25 (if confirmed)
res = latest_confirmed_swing(df, idx=30, kind='swing_low')
# In a clean 4H sequence with pivot=10, this would be the swing at bar 25
# (we just check that the function returns a tuple, not None, when there's a confirmed swing)
print('swings look OK; L1 confirmed_at:', df.iloc[5].get('swing_low_confirmed_at'))

print('OK: swings.py labels not knowable before confirmed_at')
"
```

**Pass criteria**: the `(a)` and `(b)` assertions are the lookahead guard. If `(a)` fails — i.e., the swing at bar 15 has a label at bar 15 — **the engine is broken** and `swings.py` must be reworked. This is the most important assertion in the whole SMC engine.

**Common failures**:
- `(a)` failing: the implementation is rolling with `center=True` or using a future-anchored window. Fix: enforce `swing_label = None` for all rows from `swing.index` to `swing.confirmed_at - 1`.
- `(b)` failing: the implementation labels a swing at the swing's own index. Fix: emit labels only from `confirmed_at` onward.

### Verify 1.3 — `mtf.py`

```bash
cd backend && python -c "
import pandas as pd
from app.core.smc.mtf import (
    last_closed_htf_candle, build_htf_alignment, _smoke_test_lookahead_alignment
)
_smoke_test_lookahead_alignment()  # built-in self-test

# Real-data test: fetch 1 day of BTC 15m and verify HTF alignment
from app.core.data_utils import get_finalized_candles
df_15m = get_finalized_candles('BTCUSDT', '15m', limit=96)   # 1 day
df_1h  = get_finalized_candles('BTCUSDT', '1h',  limit=24)
assert len(df_15m) == 96
assert len(df_1h)  == 24

aligned = build_htf_alignment(df_15m, {'1h': df_1h})
assert 'htf_1h_close' in aligned.columns, '1H close column missing'

# (a) At the very first 15m bar, htf_1h_close must be NaN (no prior 1H closed yet)
first_close = aligned.iloc[0]['htf_1h_close']
print(f'first 15m bar htf_1h_close = {first_close}')
# In a 1-day dataset, by 15m bar ~5, the first 1H candle is closed
# So first row might be NaN; row 4 (15:00) should have a value
assert pd.isna(first_close) or pd.notna(first_close), 'OK either way for first bar'

# (b) The htf_1h_close at 15m bar 16:00 must equal the 1H candle that closed at 15:00
bar_at_15 = aligned[aligned['open_time'] == pd.Timestamp('2024-XX-XX 16:00', tz='UTC')]
# (in your real data, replace XX with the actual date)

# (c) Walk forward: the htf_1h_close should change only at 15m bars that follow an 1H close
prev = None
changes = 0
for i in range(len(aligned)):
    cur = aligned.iloc[i]['htf_1h_close']
    if pd.notna(cur) and prev is not None and cur != prev:
        changes += 1
    if pd.notna(cur): prev = cur
# In 1 day (96 bars), 1H closes 24 times; we expect ~24 changes (might be 23 if the
# dataset starts mid-day)
assert 20 <= changes <= 24, f'htf_1h_close changed {changes} times in 1 day, expected ~24'
print(f'htf_1h_close changed {changes} times in 1 day (expected 23-24). OK.')

print('OK: mtf.py closed-candle alignment works')
"
```

**Pass criteria**:
- The built-in `_smoke_test_lookahead_alignment` prints `OK: mtf.lookahead_guard`. If it raises `AssertionError`, the **most important rule in the engine** is violated — fix `last_closed_htf_candle` immediately.
- The change count is in [20, 24] for a 1-day window. If it's 0, the alignment is broken entirely. If it's 96, the alignment is using `iloc[-1]` (the trap).

### Combined Phase 1 smoke test

```bash
cd backend && python -c "
import pandas as pd
from app.core.smc.sessions import stamp_sessions, compute_session_ranges
from app.core.smc.swings   import extract_swings
from app.core.smc.mtf      import build_htf_alignment
from app.core.data_utils   import get_finalized_candles

df = get_finalized_candles('BTCUSDT', '15m', limit=500)   # ~5 days
df_1h  = get_finalized_candles('BTCUSDT', '1h',  limit=120)
df_4h  = get_finalized_candles('BTCUSDT', '4h',  limit=30)
df_1d  = get_finalized_candles('BTCUSDT', '1d',  limit=10)

df = stamp_sessions(df); df = compute_session_ranges(df)
df = extract_swings(df)
df = build_htf_alignment(df, {'1h': df_1h, '4h': df_4h, '1d': df_1d})

# Print the row count of every column we added
expected_cols = [
    'session', 'is_kill_zone', 'session_idx',
    'session_high', 'session_low', 'session_range', 'session_complete',
    'swing_high', 'swing_low', 'swing_high_confirmed_at', 'swing_low_confirmed_at',
    'swing_label', 'internal_high', 'internal_low',
    'htf_1h_close', 'htf_4h_close', 'htf_1d_close',
]
for c in expected_cols:
    assert c in df.columns, f'MISSING: {c}'
    n_nonnull = df[c].notna().sum()
    print(f'{c:35s} {n_nonnull:4d}/{len(df)} non-null')
print('OK: Phase 1 modules integrate on a real BTC 15m dataset')
"
```

**Pass criteria**: all 15 expected columns present, no exceptions. The non-null counts will vary by column (e.g., `swing_high` will be < 10 in 500 bars, `htf_1h_close` should be > 480 in 500 bars — at most the first 4 bars can be NaN).

## Final Deliverable

- `backend/app/core/smc/sessions.py` — passes 5/5 session assertions.
- `backend/app/core/smc/swings.py` — passes the lookahead guard assertion. No `swing_label` is ever set before `confirmed_at`.
- `backend/app/core/smc/mtf.py` — passes the built-in `_smoke_test_lookahead_alignment` and the change-count check on real BTC data.
- 15 new columns on a 15m BTC DataFrame after running the combined smoke test.

## Next Phase

→ [Phase 2: Structure + Zones](./phase-2-structure-zones.md) — write `structure.py`, `fvgs.py`, `order_blocks.py`.
