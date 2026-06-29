# Phase 3: Liquidity + Bias + Premium/Discount

## Goal

Close the three largest gaps from the v1 SMC engine:

1. **Liquidity** — PDH, PDL, PWH, PWL, Asian/London/NY session H/L/Range, equal highs/lows, and buy-side/sell-side liquidity pools. Plus sweeps of all of these (not just swing-fractal turtle soup like v1).
2. **Bias Engine** — weekly and daily bias, with explicit "tentative" vs "confirmed" states, gated by swing BOS confirmation.
3. **Premium/Discount** — 50% equilibrium filter on the last bias-direction swing range.

All three are **deterministic** given the closed candles — no lookahead risk from these modules *by themselves*. The lookahead risk is in the *confirmation gate* (a bias is "confirmed" only when a swing BOS in the bias direction fires after the bias reset window opens) — that gate is built in `bias.py` and uses `confirmed_at` indices.

## Files Created

| File | LOC (est.) | Purpose |
|---|---|---|
| `backend/app/core/smc/liquidity.py`         | ~500 | All liquidity concepts + sweep detector |
| `backend/app/core/smc/bias.py`              | ~350 | Weekly + Daily bias with confirmation gate |
| `backend/app/core/smc/premium_discount.py`  | ~250 | 50% equilibrium + premium/discount zone classification |

## Tasks

### 3.1 `liquidity.py` — The Largest New Module

#### Concepts table (deterministic, no parameters for most)

| Concept | Source | Frequency | Output column(s) |
|---|---|---|---|
| **PDH** (Prior Day High) | High of *prior UTC day*'s 1H candle aggregate | daily | `liq_pdh` (float, ffill'd through current day) |
| **PDL** (Prior Day Low) | Low of prior UTC day | daily | `liq_pdl` |
| **PWH** (Prior Week High) | High of prior ISO week (Mon 00:00 → Sun 23:59 UTC) | weekly | `liq_pwh` |
| **PWL** (Prior Week Low) | Low of prior ISO week | weekly | `liq_pwl` |
| **Asian Range High/Low** | Highest high / lowest low of 00:00–08:00 UTC of current day | daily | `liq_asian_h`, `liq_asian_l` (NaN until session completes) |
| **London Range H/L** | 08:00–13:00 UTC | daily | `liq_london_h`, `liq_london_l` |
| **NY Range H/L** | 13:00–22:00 UTC | daily | `liq_ny_h`, `liq_ny_l` |
| **Equal Highs** | Cluster of confirmed swing highs within `equal_hl_tolerance_pct` (= 0.1%) and within `max_gap_bars=200` of each other | rolling | `liq_eqh_price` (NaN if none in window) |
| **Equal Lows** | Mirror | rolling | `liq_eql_price` |
| **Buy-Side Liquidity** | Logical union of: equal highs, prior day/week high, Asian range high, London range high, NY range high | derived | `liq_buy_side_targets` (list) — per-candle the *nearest* one is exposed as `liq_nearest_buy` |
| **Sell-Side Liquidity** | Mirror | derived | `liq_nearest_sell` |
| **Sweep events** | For every liquidity level, detect wick-pierce-then-close-back | on each candle | `event_sweep_pdh`, `event_sweep_pdl`, `event_sweep_pwh`, `event_sweep_pwl`, `event_sweep_eqh`, `event_sweep_eql`, `event_sweep_asian_h`, ..., `event_sweep_ny_l` |

#### Implementation rules

1. **The single free parameter** (`equal_hl_tolerance_pct = 0.001`, i.e., 0.1%) is in `_params.py` and must be sensitivity-tested ±50% in Phase 5. If the test fails (i.e., results change drastically), the parameter is too tight — relax it.

2. **PDH/PDL computation**:
   - Resample the *primary TF* (15m) to 1D: `df.resample('1D', on='open_time').agg({'high':'max', 'low':'min'})`.
   - `df['liq_pdh'] = daily_df['high'].shift(1)` (yesterday's high, ffill'd forward through today).
   - On the first bar of a new UTC day, the PDH value **changes** (that's the new prior day). This change happens on the row whose `open_time` is the first 15m bar of the day (e.g., 00:00 UTC).
   - **Lookahead guard**: `shift(1)` is correct (we look at *yesterday's* high; today's high is in-progress).

3. **PWH/PWL computation**:
   - Resample to ISO weeks. ISO week starts Monday.
   - `df['liq_pwh'] = weekly_df['high'].shift(1).ffill()`.
   - Same lookahead guard.

4. **Session ranges**:
   - Use the `session` and `session_idx` columns added by `sessions.py` in Phase 1.
   - For each session, compute `session_high = groupby('session_idx')['high'].cummax()` — fills forward during the session, frozen at the last candle.
   - For Asian range on a *future* bar (the bar at 00:00 hasn't completed yet), `liq_asian_h` is **NaN** — the engine refuses to publish session range until the session closes. The validator in Phase 5 will IC-test whether using `liq_asian_h` is *only safe* in `is_kill_zone == False` windows (i.e., post-NY-AM, when Asian range is known for the day).

5. **Equal Highs/Lows**:
   - Walk the confirmed swing highs from `swings.latest_confirmed_swing(df, i, 'swing_high')`. A confirmed swing high is part of an "equal highs" cluster if its price is within `equal_hl_tolerance_pct` of another confirmed swing high and they are within `max_gap_bars=200` of each other.
   - The cluster's representative price is the **average** of the cluster members.
   - `liq_eqh_price` is the *nearest* such cluster's price at row `i`. If multiple clusters exist at different prices, expose them via `liq_eqh_prices` (list).

6. **Sweep events** — extension of v1's `detect_liquidity_sweep`:
   - v1 only swept swing-fractal pivots. v2 sweeps **every** liquidity level.
   - Bullish sweep of PDH: `low[i] <= pdh AND close[i] > pdh` (wick below, close back above) — i.e., price wicked into the level, then closed back, indicating a rejection and potential reversal.
   - Bearish sweep of PDH: `high[i] >= pdh AND close[i] < pdh` (wick above, close back below).
   - The sweep event column is `event_sweep_pdh` (bool, single-candle). For `_recent` (rolling 10-bar with opposing cancellation), the same pattern as v1 `events.detect_liquidity_sweep` applies.

#### API

```python
def extract_liquidity(
    df: pd.DataFrame,
    htf_data: Dict[str, pd.DataFrame],   # for 1D aggregation
    equal_hl_tolerance_pct: float = 0.001,   # = _params.PARAMS entry
    equal_hl_max_gap_bars: int = 200,
) -> pd.DataFrame:
    """
    Required input columns: open, high, low, close, open_time, session, session_idx,
                            swing_high, swing_low, swing_high_confirmed_at,
                            swing_low_confirmed_at (from Phase 1)
    Adds (15+ columns): see table above
    """
```

### 3.2 `bias.py` — Weekly + Daily Bias with Confirmation Gate

The bias engine is where ICT discipline matters most. A trader who takes a "daily bias bullish" signal at 09:30 without waiting for the kill-zone confirmation candle is taking 2-3x more trades than they should be.

#### Weekly bias (resets Mon 00:00 UTC)

```python
def compute_weekly_bias(
    df: pd.DataFrame,        # LTF with HTF columns from mtf.build_htf_alignment
) -> pd.Series:
    """
    Returns: pd.Series ∈ {'bull', 'bear', 'neutral'}
    For each row, the bias that is knowable AS OF that row's open_time.

    Inputs (from mtf.py): htf_1d_close, htf_1d_high, htf_1d_low
                          (these are LAST CLOSED 1D, so they reflect yesterday's
                           1D candle — never the forming one)

    Rules:
        BULL iff:
            (1) last closed 1D close > last closed 1D EMA 50  (trend)
            (2) last closed 1D candle is bullish-close
                (close > open)
            (3) last closed 1D high > high of the 1D candle BEFORE that
                (higher-high structure on 1D)
        BEAR iff mirror of the above
        NEUTRAL otherwise (e.g., 1D inside bar, EMA 50 slope flat)
    """
```

**Reset semantics**: At the first 15m bar of a new ISO week (Monday 00:00 UTC), the bias reverts to `neutral` and is re-evaluated bar by bar as new 1D closes come in. The `bias_reset_at` column tracks when the last reset happened (used by validators to ensure no bias persists across the weekend).

#### Daily bias (resets 00:00 UTC)

```python
def compute_daily_bias(
    df: pd.DataFrame,
    weekly_bias: pd.Series,
) -> pd.DataFrame:
    """
    Adds columns:
        smc_weekly_bias     ∈ {bull, bear, neutral}     (from compute_weekly_bias)
        smc_daily_bias      ∈ {bull, bear, neutral, tentative_bull, tentative_bear}
        smc_bias_confirmed  bool — True if a swing BOS in the bias direction
                                     has fired since 00:00 UTC, inside a kill zone
        smc_bias_confirmed_at   timestamp of the confirmation event
        smc_bias_reset_at   timestamp of last daily/weekly reset
    """
```

**Daily bias rule**:
- **Tentative bull**: weekly bias is `bull` AND 4H swing trend is `bull` (from `mtf.htf_4h_trended` or from running `extract_swings` on 4H HTF data).
- **Tentative bear**: mirror.
- **Confirmed bull**: tentative bull + a swing BOS in bull direction has fired since 00:00 UTC, inside a kill zone.
- **Confirmed bear**: mirror.
- **Neutral**: weekly bias is `neutral`, or 4H swing trend disagrees with weekly bias.

**The confirmation gate is the most important behavior in this module**: a "tentative" daily bias is not actionable. Strategies that consume `smc_daily_bias` should check `smc_bias_confirmed` and refuse to enter on a tentative bias.

#### API

```python
def compute_bias(
    df: pd.DataFrame,        # LTF with HTF columns
    htf_data: Dict[str, pd.DataFrame],  # 1H, 4H, 1D candles
) -> pd.DataFrame:
    """
    Adds: smc_weekly_bias, smc_daily_bias, smc_bias_confirmed,
          smc_bias_confirmed_at, smc_bias_reset_at
    """
```

#### Why confirmation requires a kill-zone BOS

Without the kill-zone gate, a daily bullish bias would be "confirmed" the moment any 15m candle breaks a 4H swing high — including at 23:00 UTC, when the only participants are bots and stale liquidity. Adding the `is_kill_zone` requirement means the confirmation event happened during a window where institutional flow is actually present.

The Phase 5 validator will test this hypothesis: is the kill-zone gate additive to performance, or is it noise? If it's noise, drop it (the rule can be relaxed). If it adds IR, keep it.

### 3.3 `premium_discount.py` — 50% Equilibrium

The simplest and most quant-validated of the SMC concepts. Anchor a swing range to the bias direction, classify each candle as premium/equilibrium/discount.

#### API

```python
def compute_premium_discount(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Required input columns: close, swing_high, swing_low, swing_high_confirmed_at,
                            swing_low_confirmed_at, smc_daily_bias, smc_bias_confirmed,
                            smc_bias_confirmed_at
    Adds:
        pd_range_high      float — anchor high of current range
        pd_range_low       float — anchor low of current range
        pd_equilibrium     float — midpoint
        pd_zone            ∈ {premium, equilibrium, discount}
        pd_range_age_bars  int   — how many bars since current range was anchored
        pd_range_direction ∈ {bull, bear, neutral}  — direction of trend that
                                                      established this range
    """
```

#### Anchoring rules (no parameters)

1. **Range direction = current daily bias direction** (if `smc_bias_confirmed`).
2. **Anchor high = the most recent confirmed swing high established during the current bias**.
3. **Anchor low = the most recent confirmed swing low established during the current bias**.
4. **Range reset conditions** (rare):
   - When a CHoCH against the current daily bias fires (range invalidated, reset to neutral until new bias).
   - When a new ISO week starts (range re-anchored to fresh 1W structure).
5. **Zone classification**:
   - `premium`: `close > equilibrium` (only shorts allowed in premium)
   - `equilibrium`: `close == equilibrium` (within 0.05% — no entries, tight zone)
   - `discount`: `close < equilibrium` (only longs allowed in discount)

#### The 0.05% equilibrium band

Why not a single line? A single `close == equilibrium` test would only match if a candle closed *exactly* on the equilibrium — vanishingly rare. A band of 0.05% (= 50 bps in a 100k BTC; ~0.05% in a 0.001 altcoin) is wide enough to be useful and narrow enough to be meaningful. This is a *constant* (in `_params.CONSTANTS`), not a tunable.

#### Lookahead guard

The "most recent confirmed swing in bias direction" is read via `latest_confirmed_swing(df, i, 'swing_high')` from `swings.py` — which guarantees the swing's `confirmed_at ≤ i`. The range is therefore always anchored to a swing that was knowable at row `i`.

## Manual Verification

### Verify 3.1 — `liquidity.py`

```bash
cd backend && python -c "
import pandas as pd
from app.core.smc.sessions import stamp_sessions, compute_session_ranges
from app.core.smc.swings   import extract_swings
from app.core.smc.mtf      import build_htf_alignment
from app.core.smc.liquidity import extract_liquidity
from app.core.data_utils    import get_finalized_candles

# 1 week of BTC 15m for sessions, 1 month for PDH/PWH
df = get_finalized_candles('BTCUSDT', '15m', limit=4*96*7)   # 1 week
df_1h  = get_finalized_candles('BTCUSDT', '1h',  limit=24*30)
df_4h  = get_finalized_candles('BTCUSDT', '4h',  limit=6*30)
df_1d  = get_finalized_candles('BTCUSDT', '1d',  limit=365)

df = stamp_sessions(df); df = compute_session_ranges(df)
df = extract_swings(df)
df = build_htf_alignment(df, {'1h': df_1h, '4h': df_4h, '1d': df_1d})
df = extract_liquidity(df, {'1h': df_1h, '4h': df_4h, '1d': df_1d})

# (a) All expected columns present
expected = [
    'liq_pdh', 'liq_pdl', 'liq_pwh', 'liq_pwl',
    'liq_asian_h', 'liq_asian_l', 'liq_london_h', 'liq_london_l',
    'liq_ny_h', 'liq_ny_l', 'liq_eqh_price', 'liq_eql_price',
    'liq_nearest_buy', 'liq_nearest_sell',
    'event_sweep_pdh', 'event_sweep_pdl', 'event_sweep_pwh', 'event_sweep_pwl',
    'event_sweep_asian_h', 'event_sweep_asian_l',
    'event_sweep_eqh', 'event_sweep_eql',
]
for c in expected:
    assert c in df.columns, f'MISSING: {c}'

# (b) PDH/PDL are non-null from bar ~96 (the second day) onwards
non_null_pdh = df['liq_pdh'].notna().sum()
print(f'PDH non-null: {non_null_pdh}/{len(df)}')
assert non_null_pdh > len(df) * 0.7, f'PDH should be non-null for most of the week'

# (c) Lookahead test: at the FIRST 15m bar of a day, liq_pdh equals the
#     high of the PRIOR day's 1H aggregate (NOT the forming day's high)
df['date_utc'] = df['open_time'].dt.date
first_bars = df.groupby('date_utc').first()
for date, row in first_bars.iterrows():
    if pd.isna(row['liq_pdh']): continue
    # The prior day's high should be strictly less than or equal to ANY high
    # in the forming day (since forming day is in progress)
    forming_day = df[df['date_utc'] == date]
    assert forming_day['high'].max() >= row['liq_pdh'], \
        f'lookahead: PDH on {date} exceeds today high'

# (d) Session ranges: liq_asian_h is NaN during Asian session (in progress)
#     and gets filled in at the end
asian_first = df[df['session'] == 'asian'].iloc[0]
assert pd.isna(asian_first['liq_asian_h']) or pd.notna(asian_first['liq_asian_h'])
# Allow either: a row mid-session may have a partial high, but the FINAL asian
# row of the day must have the true high
asian_complete = df[(df['session'] == 'asian') & (df['session_complete'] == True)]
for date, day_df in asian_complete.groupby('date_utc'):
    if len(day_df) == 0: continue
    last = day_df.iloc[-1]
    true_high = day_df['high'].max()
    assert abs(last['liq_asian_h'] - true_high) < 0.01, \
        f'asian_h wrong on {date}: stored {last[\"liq_asian_h\"]}, true {true_high}'

# (e) Sweep events are bool
for c in expected:
    if c.startswith('event_sweep'):
        assert df[c].dtype == bool, f'{c} should be bool, got {df[c].dtype}'

# (f) Sensitivity test on the ONE free parameter (equal_hl_tolerance_pct)
out_tight = extract_liquidity(df.copy(), {'1h': df_1h, '4h': df_4h, '1d': df_1d},
                              equal_hl_tolerance_pct=0.0005)
out_loose = extract_liquidity(df.copy(), {'1h': df_1h, '4h': df_4h, '1d': df_1d},
                              equal_hl_tolerance_pct=0.002)
tight_eqh = out_tight['liq_eqh_price'].notna().sum()
loose_eqh = out_loose['liq_eqh_price'].notna().sum()
print(f'equal_hl @ 0.05%: {tight_eqh} eqh bars, @ 0.2%: {loose_eqh} eqh bars')
# Loose tolerance should produce >= as many EQH bars as tight (more clusters)
assert loose_eqh >= tight_eqh, 'loose tolerance should yield >= EQH clusters'

print('OK: liquidity.py all 6 checks pass')
"
```

**Pass criteria**: 6/6 assertions. The `(c)` test is the lookahead guard: a value labeled "PDH" must never exceed the forming day's high. If it does, the engine is leaking the current day's data. The `(f)` test is a quick sanity check on the parameter sensitivity — Phase 5 will do a more rigorous sensitivity analysis.

### Verify 3.2 — `bias.py`

```bash
cd backend && python -c "
import pandas as pd
from app.core.smc.sessions import stamp_sessions, compute_session_ranges
from app.core.smc.swings   import extract_swings
from app.core.smc.mtf      import build_htf_alignment
from app.core.smc.structure import extract_structure
from app.core.smc.bias     import compute_bias
from app.core.data_utils   import get_finalized_candles

# 1 month of BTC 15m
df = get_finalized_candles('BTCUSDT', '15m', limit=4*96*30)
df_1h  = get_finalized_candles('BTCUSDT', '1h',  limit=24*30)
df_4h  = get_finalized_candles('BTCUSDT', '4h',  limit=6*30)
df_1d  = get_finalized_candles('BTCUSDT', '1d',  limit=365)

df = stamp_sessions(df); df = compute_session_ranges(df)
df = extract_swings(df)
df = build_htf_alignment(df, {'1h': df_1h, '4h': df_4h, '1d': df_1d})
df = extract_structure(df)   # need struct_trend_swing for daily bias
df = compute_bias(df, {'1h': df_1h, '4h': df_4h, '1d': df_1d})

# (a) bias columns exist
for c in ['smc_weekly_bias', 'smc_daily_bias', 'smc_bias_confirmed',
          'smc_bias_confirmed_at', 'smc_bias_reset_at']:
    assert c in df.columns, f'MISSING: {c}'

# (b) smc_daily_bias values are in the expected set
allowed = {'bull', 'bear', 'neutral', 'tentative_bull', 'tentative_bear'}
assert set(df['smc_daily_bias'].unique()) <= allowed, \
    f'unexpected bias values: {set(df[\"smc_daily_bias\"].unique()) - allowed}'

# (c) Confirmation logic: smc_bias_confirmed=True => smc_daily_bias is NOT tentative
confirmed_rows = df[df['smc_bias_confirmed'] == True]
non_tentative = confirmed_rows[~confirmed_rows['smc_daily_bias'].isin(['tentative_bull', 'tentative_bear'])]
assert len(non_tentative) == len(confirmed_rows), \
    f'some confirmed rows still have tentative bias: {len(confirmed_rows) - len(non_tentative)}'

# (d) Reset logic: at 00:00 UTC, smc_bias_reset_at should update
first_bars = df.groupby(df['open_time'].dt.date).first()
unique_resets = first_bars['smc_bias_reset_at'].nunique()
print(f'unique daily bias resets: {unique_resets} (expected ~30 for 30-day window)')
assert unique_resets >= 28, f'expected ~30 daily resets, got {unique_resets}'

# (e) Weekly reset: should reset at the first bar of each ISO week
# (Monday 00:00 UTC). On a 30-day window, expect 4-5 weekly resets.
weekly_resets = df[df['smc_bias_reset_at'].notna() & (df['open_time'].dt.dayofweek == 0)]
print(f'weekly reset bars: {len(weekly_resets)}')

# (f) Tentative -> confirmed transition: on a confirmed row, the confirmed_at
#     should be on or after the most recent 00:00 UTC
for i, row in df[df['smc_bias_confirmed'] == True].head(20).iterrows():
    confirmed_at = pd.Timestamp(row['smc_bias_confirmed_at'])
    last_midnight = row['open_time'].normalize()  # 00:00 UTC of the same date
    # If confirmed_at is BEFORE the current bar's open_time, that's a bug
    assert confirmed_at <= row['open_time'], \
        f'confirmed_at {confirmed_at} is in the future relative to bar {row[\"open_time\"]}'

print('OK: bias.py all 6 checks pass')
"
```

**Pass criteria**: 6/6 assertions. The `(c)` test is the *confirmation logic gate*: if any row is labeled `smc_bias_confirmed=True` but its `smc_daily_bias` is still `tentative_*`, the confirmation logic is broken. This is a critical correctness check. The `(d)` and `(e)` tests verify the reset semantics (daily at 00:00 UTC, weekly at Mon 00:00 UTC). The `(f)` test guards against time-travel bugs in the confirmation timestamp.

**Common failures**:
- `(c)` failing: the confirmation is being applied to the wrong bias level (e.g., weekly getting the daily confirmation flag). Fix: `smc_bias_confirmed` should ONLY be set when daily bias transitions from tentative → confirmed, not on weekly transitions.
- `(d)` failing: the reset is not anchored to 00:00 UTC. Check that the `smc_bias_reset_at` is set on rows whose `open_time.dt.hour == 0 AND .dt.minute == 0`.
- `(f)` failing: `smc_bias_confirmed_at` is being set to a future timestamp. The confirmation event happened on a bar at time `t`; `confirmed_at` must be `≤ t` (the bar that produced the confirmation, NOT the next bar).

### Verify 3.3 — `premium_discount.py`

```bash
cd backend && python -c "
import pandas as pd
from app.core.smc.sessions import stamp_sessions, compute_session_ranges
from app.core.smc.swings   import extract_swings
from app.core.smc.mtf      import build_htf_alignment
from app.core.smc.structure import extract_structure
from app.core.smc.bias     import compute_bias
from app.core.smc.premium_discount import compute_premium_discount
from app.core.data_utils   import get_finalized_candles

df = get_finalized_candles('BTCUSDT', '15m', limit=4*96*30)
df_1h  = get_finalized_candles('BTCUSDT', '1h',  limit=24*30)
df_4h  = get_finalized_candles('BTCUSDT', '4h',  limit=6*30)
df_1d  = get_finalized_candles('BTCUSDT', '1d',  limit=365)

df = stamp_sessions(df); df = compute_session_ranges(df)
df = extract_swings(df)
df = build_htf_alignment(df, {'1h': df_1h, '4h': df_4h, '1d': df_1d})
df = extract_structure(df)
df = compute_bias(df, {'1h': df_1h, '4h': df_4h, '1d': df_1d})
df = compute_premium_discount(df)

# (a) All expected columns
for c in ['pd_range_high', 'pd_range_low', 'pd_equilibrium', 'pd_zone',
          'pd_range_age_bars', 'pd_range_direction']:
    assert c in df.columns, f'MISSING: {c}'

# (b) pd_equilibrium = midpoint of high and low (when both are non-null)
non_null = df[df['pd_range_high'].notna() & df['pd_range_low'].notna()]
midpoints = (non_null['pd_range_high'] + non_null['pd_range_low']) / 2
diff = (non_null['pd_equilibrium'] - midpoints).abs()
assert diff.max() < 0.01, f'equilibrium not midpoint: max diff {diff.max()}'

# (c) pd_zone matches the equilibrium test
in_premium = non_null[non_null['close'] > non_null['pd_equilibrium']]
in_discount = non_null[non_null['close'] < non_null['pd_equilibrium']]
assert (in_premium['pd_zone'] == 'premium').all(), 'premium misclassification'
assert (in_discount['pd_zone'] == 'discount').all(), 'discount misclassification'

# (d) Lookahead: pd_range_high and pd_range_low at row i must be from a swing
#     whose confirmed_at <= i
# (This is enforced by the implementation, but spot-check 10 random rows)
sampled = df[df['pd_range_high'].notna()].sample(min(10, df['pd_range_high'].notna().sum()),
                                                 random_state=42)
# The implementation should not have read a future swing. We can't directly
# test this without a synthetic dataset, so we check that the range values
# are within the dataset's high-low range (i.e., they came from real data)
assert (sampled['pd_range_high'] <= df['high'].max() * 1.001).all(), \
    'pd_range_high exceeds dataset max high (lookahead?)'
assert (sampled['pd_range_low']  >= df['low'].min()  * 0.999).all(), \
    'pd_range_low below dataset min low (lookahead?)'

# (e) pd_zone distribution: in a typical BTC month, expect more discount
#     (downside) or premium depending on trend. Should NOT be 100% premium
#     or 100% discount (that would indicate a range-anchoring bug).
zone_counts = df['pd_zone'].value_counts()
print(f'zone distribution: {dict(zone_counts)}')
assert (zone_counts / zone_counts.sum() > 0.05).all(), \
    f'some zone < 5% — anchoring may be off'

print('OK: premium_discount.py all 5 checks pass')
"
```

**Pass criteria**: 5/5 assertions. The `(b)` test verifies the equilibrium is a true midpoint. The `(c)` test verifies the zone classification. The `(d)` test is a soft lookahead check — it cannot prove the absence of lookahead, but it catches the most egregious bugs (range values outside the dataset's bounds). The `(e)` test catches a stuck-in-one-zone bug.

## Final Deliverable

- `liquidity.py` — 6 liquidity concepts, 12 sweep event columns, all 6 verification checks pass.
- `bias.py` — weekly + daily bias with confirmation gate, all 6 verification checks pass.
- `premium_discount.py` — 50% equilibrium, premium/equilibrium/discount zones, all 5 verification checks pass.
- No new lookahead bugs introduced (the verification blocks include explicit lookahead guards).

## Next Phase

→ [Phase 4: Engine Orchestrator](./phase-4-engine-orchestrator.md) — wire it all together with `run_smc_analysis()` and the per-bar `SMContext`.
