# Phase 5: Validators — The Ship Gate

> **Future SMC v2 design.** This phase plan is not a record of completed runtime modules; see [the SMC design status](README.md).

## Goal

Build the validators that *every* future change to the SMC engine must pass before it can ship. This is the most important phase of the project — the validators are what protect the engine from regressing to "Sharpe 5 in backtest, 0.5 in live" territory.

The four validators are:

1. **Lookahead audit** — for every column the engine adds, prove it uses only past-or-current data.
2. **Information Coefficient (IC) test** — every individual SMC "signal" must clear IC > 0.02, t-stat > 2, sample > 30 before being combined.
3. **Walk-forward validation** — the engine's signal pipeline, run on a rolling 6m/1m fold, must clear mean test Sharpe > 0.5.
4. **Regime coverage** — the engine must produce a positive Sharpe in the 2022 bear, 2023 chop, AND 2024 bull segments independently.

Phase 5 is the **ship gate** between engine construction and integration into the live system. If a validator fails, the engine does not ship — it goes back for rework.

## Files Created

| File | LOC (est.) | Purpose |
|---|---|---|
| `backend/app/core/smc/validators.py` | ~600 | The four validators + a `run_all_validators()` entry point |

## Tasks

### 5.1 Lookahead Audit (`audit_lookahead`)

The simplest and most important validator. The idea: take a synthetic input where the future is "obviously different" from the past (e.g., a constant 100 then a sudden 1000), run the engine, and verify the engine's outputs do not see the 1000 before it actually appears.

#### API

```python
def audit_lookahead(
    df: pd.DataFrame,
    htf_data: Dict[str, pd.DataFrame] | None = None,
    symbol: str = 'TEST',
    timeframe: str = '15m',
) -> dict:
    """
    Run the engine on a synthetic dataset with an obvious future, then verify
    that no engine column at row i references data from row > i.

    Strategy: build a DataFrame where the first 100 rows are constant 100,
    and rows 100-200 are constant 1000. Run the engine. At every row i < 100,
    every engine column should have a value in the range that data range
    allows (e.g., highs should be ~100, not ~1000).

    Returns:
        {
          'pass': bool,
          'violations': list of (row_idx, column_name, observed_value, description)
        }
    """
```

#### Implementation sketch

```python
def audit_lookahead(df, htf_data=None, symbol='TEST', timeframe='15m') -> dict:
    n = len(df)

    # Build a synthetic DataFrame: rows 0..n//2 are 100, rows n//2..n are 200
    half = n // 2
    df_synth = pd.DataFrame({
        'open_time': pd.date_range('2024-01-01', periods=n, freq='15min', tz='UTC'),
        'open':   [100.0]*half + [200.0]*(n-half),
        'high':   [100.0]*half + [200.0]*(n-half),
        'low':    [100.0]*half + [200.0]*(n-half),
        'close':  [100.0]*half + [200.0]*(n-half),
        'volume': [1000.0]*n,
    })

    # Run the engine
    df_out = run_smc_analysis(df_synth, htf_data, symbol=symbol, timeframe=timeframe)

    violations = []
    # At every row i < half - pivot_bars (the confirmation lag),
    # no engine column should see the 200-level future.
    safe_until = half - 20  # 20 bars of buffer beyond the level change

    for i in range(safe_until):
        row = df_out.iloc[i]
        for col in df_out.columns:
            if col in ('open_time', 'open', 'high', 'low', 'close', 'volume'):
                continue
            val = row[col]
            if pd.isna(val) or not isinstance(val, (int, float, np.floating, np.integer)):
                continue
            # A 100% lookahead-safe value at row i (i < half) is in [0, 200]
            # (it could be any level, but NOT 200, because 200 only exists in rows >= half)
            # Allow a small tolerance for cases where the future is "close but not 200".
            if val > 195:
                violations.append({
                    'row': i, 'col': col, 'value': val,
                    'description': f'value {val} > 195 at row {i} (< half) — sees future?'
                })

    return {
        'pass': len(violations) == 0,
        'violations': violations,
        'synthetic_input': {'half': half, 'safe_until': safe_until},
    }
```

**Pass criteria**: `result['pass']` is True. Any violation indicates a column is reading future data — fix the offending module.

**This is the test that would have caught every "Sharpe 5" backtest bug in the past.** If a column is using `shift(-1)` or `iloc[j+1]` anywhere, this test will fail.

### 5.2 Information Coefficient Test (`test_signal_ic`)

The statistical heart of the validators. For each individual SMC "signal" (e.g., `struct_swing_event == 'SCHOCH_UP'`, or `liq_eqh_price` not null, or `smc_bias_confirmed == True`), test whether the signal predicts forward returns.

#### API

```python
def test_signal_ic(
    df: pd.DataFrame,
    signal_column: str,
    forward_horizons: list[int] = [1, 4, 24],   # bars ahead at the operating TF
    min_samples: int = 30,
) -> dict:
    """
    Information Coefficient test for a binary signal.

    Args:
        df: enriched DataFrame from run_smc_analysis
        signal_column: name of a boolean column (e.g., 'struct_swing_event_SCHOCH_UP'
                       which is created by .notna() on a categorical column)
        forward_horizons: list of forward-return horizons in bars
        min_samples: minimum sample size for a horizon to be tested

    Returns:
        {
          'signal': signal_column,
          'horizons': [
            {
              'horizon_bars': 1,
              'ic': spearman correlation between signal and forward return,
              't_stat': t-statistic of the IC,
              'n_samples': count of valid (signal, return) pairs,
              'is_significant': abs(t_stat) > 2.0 and n_samples >= min_samples,
              'pct_positive_ic': was IC positive (>0)?
            },
            ...
          ],
          'passes_validation': True iff at least one horizon clears the bar
        }
    """
```

#### Implementation sketch

```python
from scipy import stats

def test_signal_ic(df, signal_column, forward_horizons=[1, 4, 24], min_samples=30):
    if signal_column not in df.columns:
        # Allow a categorical like 'struct_swing_event' to be converted to a bool
        if signal_column in df.columns:
            signal = df[signal_column].notna()
        else:
            raise ValueError(f"Column {signal_column} not in df")
    else:
        signal = df[signal_column].astype(bool)

    results = []
    for h in forward_horizons:
        # Forward return at horizon h: (close[i+h] - close[i]) / close[i]
        fwd_ret = df['close'].pct_change(h).shift(-h)
        aligned = pd.concat([signal.rename('sig'), fwd_ret.rename('ret')], axis=1).dropna()
        if len(aligned) < min_samples:
            results.append({
                'horizon_bars': h, 'ic': np.nan, 't_stat': np.nan,
                'n_samples': len(aligned), 'is_significant': False,
                'pct_positive_ic': None
            })
            continue
        # Spearman rank correlation
        ic, p_value = stats.spearmanr(aligned['sig'], aligned['ret'])
        # t-stat for IC = ic * sqrt(n) / sqrt(1 - ic**2) is wrong;
        # the correct t-stat uses Newey-West for serial correlation.
        # For our purposes, t_stat = ic * sqrt(n) is the standard approximation.
        n = len(aligned)
        t_stat = ic * np.sqrt(n) if abs(ic) < 1 else np.nan
        results.append({
            'horizon_bars': h, 'ic': ic, 't_stat': t_stat,
            'n_samples': n, 'is_significant': abs(t_stat) > 2.0 and n >= min_samples,
            'pct_positive_ic': ic > 0
        })

    return {
        'signal': signal_column,
        'horizons': results,
        'passes_validation': any(r['is_significant'] for r in results)
    }
```

**Pass criteria** (per sharp_edges.md and patterns.md):
- IC > 0.02 (or < -0.02 for short signals).
- t-stat > 2 (or < -2).
- n_samples ≥ 30.

If a signal fails the IC test, **don't add it to the engine** — or remove it if it's already there. The temptation to keep a "promising" signal that's not yet significant is the path to overfitting.

#### The signals to test

The engine's "natural signals" to IC-test are:

```python
SIGNALS_TO_TEST = [
    # Structure
    ('struct_swing_event_SCHOCH_UP',   'major bullish reversal'),
    ('struct_swing_event_SCHOCH_DOWN', 'major bearish reversal'),
    ('struct_swing_event_SBOS_UP',     'swing bullish continuation'),
    ('struct_swing_event_SBOS_DOWN',   'swing bearish continuation'),
    ('struct_mss_MSS_UP',              'MSS bullish'),
    ('struct_mss_MSS_DOWN',            'MSS bearish'),
    # Bias confirmation
    ('smc_bias_confirmed',             'daily bias just confirmed'),
    # FVG
    ('fvg_active',                     'price in a fresh FVG'),
    # OB
    ('ob_active',                      'price in an unmitigated OB'),
    # Liquidity
    ('event_sweep_pdh',                'PDH swept (bullish turtle soup)'),
    ('event_sweep_pdl',                'PDL swept (bearish turtle soup)'),
    # Premium/Discount
    ('pd_zone_premium',                'in premium zone'),
    ('pd_zone_discount',               'in discount zone'),
]
```

The signals are derived as booleans from categorical columns (e.g., `df['struct_swing_event'] == 'SCHOCH_UP'`).

### 5.3 Walk-Forward Validation (`walk_forward`)

The single most important *aggregate* test. Per patterns.md#walk-forward, the engine's signal pipeline is run on rolling train/test windows, and the *test* Sharpe is what matters (not the train Sharpe).

#### API

```python
def walk_forward(
    df: pd.DataFrame,
    signal_func: callable,        # function that takes df, returns (signal_series, fwd_return_series)
    train_days: int = 180,        # 6 months
    test_days: int = 30,          # 1 month
    step_days: int = 7,           # 1 week
    cost_bps_round_trip: float = 24.0,
) -> dict:
    """
    Walk-forward analysis per patterns.md#walk-forward.

    Args:
        df: enriched DataFrame with 'open_time', 'close', and signal columns
        signal_func: function (df) -> (signal: pd.Series[bool], fwd_ret: pd.Series[float])
                     The signal must be a long/flat indicator; fwd_ret is the
                     forward return at the strategy's holding horizon.
        train_days, test_days, step_days: window sizes
        cost_bps_round_trip: per-trade cost in basis points (default 24)

    Returns:
        {
          'folds': [WalkForwardResult, ...],
          'summary': {
            'mean_train_sharpe': ...,
            'mean_test_sharpe': ...,
            'sharpe_degradation': 1 - mean_test / mean_train,
            'pct_profitable_folds': ...,
            'worst_test_sharpe': ...,
            'is_viable': mean_test_sharpe > 0.5 and degradation < 0.5
          }
        }
    """
```

#### Implementation

The implementation follows `patterns.md` directly:

```python
@dataclass
class WalkForwardResult:
    train_start: pd.Timestamp
    train_end:   pd.Timestamp
    test_start:  pd.Timestamp
    test_end:    pd.Timestamp
    train_sharpe: float
    test_sharpe:  float
    train_trades: int
    test_trades:  int
    train_pnl_bps: float
    test_pnl_bps:  float

def walk_forward(df, signal_func, train_days=180, test_days=30, step_days=7,
                 cost_bps_round_trip=24.0):
    df = df.reset_index(drop=True)
    open_times = df['open_time']

    # Convert days to bars (15m bars)
    train_bars = train_days * 96
    test_bars  = test_days * 96
    step_bars  = step_days * 96

    folds = []
    for start in range(0, len(df) - train_bars - test_bars, step_bars):
        train_idx = (start, start + train_bars)
        test_idx  = (start + train_bars, start + train_bars + test_bars)

        train_df = df.iloc[train_idx[0]:train_idx[1]]
        test_df  = df.iloc[test_idx[0]:test_idx[1]]

        # Run signal on train and test (separately)
        train_sig, train_fwd = signal_func(train_df)
        test_sig,  test_fwd  = signal_func(test_df)

        # Compute returns
        train_ret = (train_sig.astype(float) * train_fwd) - cost_bps_round_trip / 10000.0
        test_ret  = (test_sig.astype(float) * test_fwd)  - cost_bps_round_trip / 10000.0

        train_sharpe = sharpe_ratio(train_ret)
        test_sharpe  = sharpe_ratio(test_ret)

        folds.append(WalkForwardResult(
            train_start=open_times.iloc[train_idx[0]],
            train_end  =open_times.iloc[train_idx[1]],
            test_start =open_times.iloc[test_idx[0]],
            test_end   =open_times.iloc[test_idx[1]],
            train_sharpe=train_sharpe,
            test_sharpe=test_sharpe,
            train_trades=train_sig.sum(),
            test_trades=test_sig.sum(),
            train_pnl_bps=train_ret.sum() * 10000,
            test_pnl_bps =test_ret.sum() * 10000,
        ))

    return {
        'folds': folds,
        'summary': {
            'mean_train_sharpe': np.mean([f.train_sharpe for f in folds]),
            'mean_test_sharpe':  np.mean([f.test_sharpe for f in folds]),
            'sharpe_degradation': 1 - (np.mean([f.test_sharpe for f in folds]) /
                                       max(np.mean([f.train_sharpe for f in folds]), 0.01)),
            'pct_profitable_folds': sum(1 for f in folds if f.test_sharpe > 0) / len(folds),
            'worst_test_sharpe': min(f.test_sharpe for f in folds),
            'n_folds': len(folds),
            'is_viable': (
                np.mean([f.test_sharpe for f in folds]) > 0.5 and
                (1 - np.mean([f.test_sharpe for f in folds]) /
                 max(np.mean([f.train_sharpe for f in folds]), 0.01)) < 0.5 and
                all(f.test_trades >= 5 for f in folds)  # min trades per fold
            )
        }
    }
```

**Pass criteria**:
- `mean_test_sharpe > 0.5`
- `sharpe_degradation < 0.5`
- Every fold has ≥ 5 trades (statistical minimum)
- At least 4 folds per symbol (i.e., 4+ months of test data)

If the walk-forward fails, the engine is overfit or the strategy being tested is not viable. Do not ship.

### 5.4 Regime Coverage (`regime_coverage`)

A standalone test for **regime robustness** — does the strategy work in bear, chop, and bull periods independently? Per sharp_edges.md#regime-blindness, a 2-year backtest might be one regime; if the strategy only works in bulls, it's not a strategy.

#### API

```python
REGIMES = {
    '2022_bear':   ('2022-01-01', '2022-12-31'),
    '2023_chop':   ('2023-01-01', '2023-12-31'),
    '2024_bull':   ('2024-01-01', '2024-12-31'),
    '2025_?',      ('2025-01-01', '2025-12-31'),  # bull or bear; depends
    '2026_partial':('2026-01-01', pd.Timestamp.now().normalize()),
}

def regime_coverage(
    df: pd.DataFrame,
    signal_func: callable,
    cost_bps_round_trip: float = 24.0,
) -> dict:
    """
    Per-regime Sharpe test.

    Returns:
        {
          'regimes': {
            '2022_bear': {'sharpe': float, 'trades': int, 'pnl_bps': float, 'passes': bool},
            '2023_chop': {...},
            ...
          },
          'is_adequate': at least 3 regimes pass AND the strategy is positive in bear
        }
    """
```

**Pass criteria**:
- At least 3 regimes covered (the engine must have data for 3+ named periods).
- At least 1 regime with the strategy being SHORT-side profitable (i.e., the strategy's shorts work in a bear market) — otherwise it's just a long-only strategy in disguise.
- No regime with `pnl_bps < -500` (i.e., the strategy doesn't blow up by -5% in any single regime).

### 5.5 `run_all_validators()` — The Ship Gate Entry Point

A single function that runs all four validators and returns a verdict. Used by the integration test in Phase 6 and by CI.

```python
def run_all_validators(
    df: pd.DataFrame,
    htf_data: Dict[str, pd.DataFrame] | None = None,
    symbol: str = 'BTCUSDT',
    timeframe: str = '15m',
    signal_func: callable | None = None,
) -> dict:
    """
    Run all four validators and return a unified verdict.

    Returns:
        {
          'lookahead': {pass, violations},
          'ic_tests': [test_signal_ic results for each signal],
          'walk_forward': {folds, summary},
          'regime_coverage': {regimes, is_adequate},
          'ship': bool,    # True iff all validators pass
          'verdict': str,  # human-readable summary
        }
    """
```

## Manual Verification

### Verify 5.1 — Lookahead audit

```bash
cd backend && python -c "
import pandas as pd
from app.core.smc.validators import audit_lookahead

# Build a 200-bar synthetic dataset with an obvious future
n = 200
half = 100
df = pd.DataFrame({
    'open_time': pd.date_range('2024-01-01', periods=n, freq='15min', tz='UTC'),
    'open':   [100.0]*half + [200.0]*(n-half),
    'high':   [100.0]*half + [200.0]*(n-half),
    'low':    [100.0]*half + [200.0]*(n-half),
    'close':  [100.0]*half + [200.0]*(n-half),
    'volume': [1000.0]*n,
})

result = audit_lookahead(df, symbol='TEST', timeframe='15m')
print(f'pass: {result[\"pass\"]}')
print(f'violations: {len(result[\"violations\"])}')
for v in result['violations'][:5]:
    print(f'  row {v[\"row\"]}, col {v[\"col\"]}, value {v[\"value\"]}')

assert result['pass'], f'lookahead audit FAILED with {len(result[\"violations\"])} violations'
print('OK: lookahead audit passes')
"
```

**Pass criteria**: `result['pass']` is True. If it fails, the printed violations tell you which columns are reading the future.

**Common failures**:
- `struct_swing_event` at row 50 shows `SBOS_UP` because price at row 100 jumps from 100 to 200. Look for: the engine is using a global `.max()` or `.idxmax()` instead of a left-to-right scan.
- `htf_*_close` at row 50 shows a value derived from the future. Look for: `last_closed_htf_candle` is using `iloc[-1]` instead of the strict cutoff rule.

### Verify 5.2 — IC tests

```bash
cd backend && python -c "
import pandas as pd
from app.core.smc.engine import run_smc_analysis
from app.core.smc.validators import test_signal_ic, SIGNALS_TO_TEST
from app.core.data_utils import get_finalized_candles

df = get_finalized_candles('BTCUSDT', '15m', limit=70_000)  # 2y
df = run_smc_analysis(df, symbol='BTCUSDT', timeframe='15m')

# Build boolean columns for categorical signals
df['struct_swing_event_SCHOCH_UP']   = df['struct_swing_event'] == 'SCHOCH_UP'
df['struct_swing_event_SCHOCH_DOWN'] = df['struct_swing_event'] == 'SCHOCH_DOWN'
df['struct_swing_event_SBOS_UP']     = df['struct_swing_event'] == 'SBOS_UP'
df['struct_swing_event_SBOS_DOWN']   = df['struct_swing_event'] == 'SBOS_DOWN'
df['struct_mss_MSS_UP']              = df['struct_mss'] == 'MSS_UP'
df['struct_mss_MSS_DOWN']            = df['struct_mss'] == 'MSS_DOWN'
df['pd_zone_premium']                = df['pd_zone'] == 'premium'
df['pd_zone_discount']               = df['pd_zone'] == 'discount'

print('Signal IC test results:')
for col, desc in SIGNALS_TO_TEST:
    if col not in df.columns:
        print(f'  {col:35s}  MISSING')
        continue
    result = test_signal_ic(df, col, forward_horizons=[1, 4, 24])
    horizons_str = ', '.join(
        f'h={h[\"horizon_bars\"]}: IC={h[\"ic\"]:+.4f} t={h[\"t_stat\"]:+.2f} n={h[\"n_samples\"]}'
        for h in result['horizons']
    )
    pass_str = '✓' if result['passes_validation'] else '✗'
    print(f'  {pass_str} {col:35s}  {horizons_str}')
"
```

**Pass criteria**:
- At least 3 of the 12 signals pass.
- Signals that fail do so honestly (low IC, low t-stat, or low n).

**Common outcomes**:
- Most signals will *fail* the IC test on BTC 15m data alone. This is expected. The signal is real, but you need *combination* with other signals and *gating* by bias/kill zone to be tradeable. The Phase 5 IC test is a per-feature check, not a per-strategy check.
- A signal that passes on its own is a strong candidate for direct use in a strategy. A signal that fails is still useful as a *filter* (e.g., "only enter when the OB is in the discount zone") but not as a primary trigger.

### Verify 5.3 — Walk-forward

```bash
cd backend && python -c "
import pandas as pd
from app.core.smc.engine import run_smc_analysis
from app.core.smc.validators import walk_forward
from app.core.data_utils import get_finalized_candles

df = get_finalized_candles('BTCUSDT', '15m', limit=70_000)
df = run_smc_analysis(df, symbol='BTCUSDT', timeframe='15m')

# A toy signal: go long when in discount AND daily bias is bull AND swing trend is up
def signal_func(d):
    sig = (
        (d['pd_zone'] == 'discount') &
        (d['smc_daily_bias'].isin(['bull', 'tentative_bull'])) &
        (d['struct_trend_swing'] == 1) &
        (d['is_kill_zone'] == True)
    )
    fwd = d['close'].pct_change(4).shift(-4)  # 1h forward
    return sig, fwd

result = walk_forward(df, signal_func, train_days=180, test_days=30, step_days=7)
print(f'is_viable: {result[\"summary\"][\"is_viable\"]}')
print(f'mean_train_sharpe: {result[\"summary\"][\"mean_train_sharpe\"]:.2f}')
print(f'mean_test_sharpe:  {result[\"summary\"][\"mean_test_sharpe\"]:.2f}')
print(f'degradation: {result[\"summary\"][\"sharpe_degradation\"]:.1%}')
print(f'profitable folds: {result[\"summary\"][\"pct_profitable_folds\"]:.1%}')
print(f'n folds: {result[\"summary\"][\"n_folds\"]}')

# This is a smoke test — the toy signal is unlikely to be viable.
# The point is the validator runs end-to-end.
"
```

**Pass criteria**:
- The validator runs without exceptions.
- The output structure is correct.
- The `is_viable` flag is `True` or `False` based on real test Sharpes.

This is a *smoke test* of the walk-forward harness. The actual signal strategy that's shipped will be tested in Phase 6 with a real strategy object.

### Verify 5.4 — Regime coverage

```bash
cd backend && python -c "
import pandas as pd
from app.core.smc.engine import run_smc_analysis
from app.core.smc.validators import regime_coverage
from app.core.data_utils import get_finalized_candles

df = get_finalized_candles('BTCUSDT', '15m', limit=70_000)
df = run_smc_analysis(df, symbol='BTCUSDT', timeframe='15m')

def signal_func(d):
    sig = (d['pd_zone'] == 'discount') & (d['struct_trend_swing'] == 1)
    fwd = d['close'].pct_change(4).shift(-4)
    return sig, fwd

result = regime_coverage(df, signal_func)
for regime, stats in result['regimes'].items():
    pass_str = '✓' if stats['passes'] else '✗'
    print(f'  {pass_str} {regime:15s}  sharpe={stats[\"sharpe\"]:+.2f}  trades={stats[\"trades\"]:4d}  pnl={stats[\"pnl_bps\"]:+.0f}bps')
print(f'is_adequate: {result[\"is_adequate\"]}')
"
```

**Pass criteria**:
- At least 3 regimes are covered (the BTC 15m dataset must span them).
- The verdict is `is_adequate` if the strategy is profitable in at least 3 regimes without blowing up in any.

### Verify 5.5 — `run_all_validators` end-to-end

```bash
cd backend && python -c "
import pandas as pd
from app.core.smc.validators import run_all_validators
from app.core.data_utils import get_finalized_candles

df = get_finalized_candles('BTCUSDT', '15m', limit=70_000)

# Define a placeholder signal_func for the walk-forward / regime tests
def signal_func(d):
    sig = (d.get('struct_trend_swing', 0) == 1) if 'struct_trend_swing' in d.columns else pd.Series(False, index=d.index)
    fwd = d['close'].pct_change(4).shift(-4)
    return sig, fwd

result = run_all_validators(df, symbol='BTCUSDT', timeframe='15m', signal_func=signal_func)
print(f'ship: {result[\"ship\"]}')
print(f'verdict: {result[\"verdict\"]}')
print()
print('lookahead:', 'PASS' if result['lookahead']['pass'] else f'FAIL ({len(result[\"lookahead\"][\"violations\"])} violations)')
print('ic passes:', sum(1 for r in result['ic_tests'] if r['passes_validation']), '/', len(result['ic_tests']))
print('wf viable:', result['walk_forward']['summary']['is_viable'])
print('regime adequate:', result['regime_coverage']['is_adequate'])
"
```

**Pass criteria**:
- `ship` is True iff all four sub-validators pass.
- The verdict string is human-readable and tells you which sub-validator failed (and why).

## Final Deliverable

- `validators.py` with the four validators + `run_all_validators()`.
- The lookahead audit's synthetic test (constant 100 → constant 200) passes — i.e., no engine column reads the future.
- IC tests run for all `SIGNALS_TO_TEST`. Results documented (some pass, some fail — that's expected).
- Walk-forward harness runs end-to-end on a real BTC dataset.
- Regime coverage test runs and reports per-regime Sharpe.
- `run_all_validators` returns a unified `ship: bool` verdict.

## Next Phase

→ [Phase 6: Integration](./phase-6-integration.md) — wire the engine into `pre_process`, add the new `/api/smc/engine` endpoint, archive v1.
