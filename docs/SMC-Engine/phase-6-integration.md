# Phase 6: Integration — pre_process, /api/smc/engine, v1 archival

## Goal

Wire the SMC engine into the existing codebase:

1. **Add `'smc'` to `BaseStrategy.required_features`** so strategies that opt in can get the full SMC context in their `generate_signals` call.
2. **Modify `BaseStrategy.pre_process`** to call `run_smc_analysis` when the `'smc'` feature is requested.
3. **Add a new `/api/smc/engine` endpoint** that returns the full enriched DataFrame as a single JSON response (so the frontend can render any subset).
4. **Archive v1 permanently** (move from `smc_v1/` to a deeper archive or delete the v1 callers entirely).
5. **Add a parity backtest** comparing v1 signal counts vs v2 on a held-out 60-day period — must match.

After this phase, the engine is integrated into the production code path.

## Files Modified

| File | Change |
|---|---|
| `backend/app/core/base_strategy.py` | Add `'smc'` to allowed `required_features`; branch in `pre_process` to call `run_smc_analysis` |
| `backend/app/blueprints/smc_bp.py` (NEW) | New blueprint with `GET /api/smc/engine` |
| `backend/app/__init__.py` | Register `smc_bp` blueprint |
| `backend/app/strategies/archive/smc_v1/` | Either move further to `archive_deep/` or delete; update any remaining callers |

## Tasks

### 6.1 Extend `BaseStrategy.pre_process` to support `'smc'`

The current `pre_process` at `backend/app/core/base_strategy.py:196` branches on `required_features`:

```python
if 'fvg' in self.required_features:
    df = extract_fvgs(df)
if 'ob' in self.required_features:
    df = extract_order_blocks(df)
# etc.
```

The new branch:

```python
if 'smc' in self.required_features:
    from app.core.smc.engine import run_smc_analysis
    # Strategies declare the operating TF (it's already in `self.timeframes[0]`)
    op_tf = self.timeframes[0]
    # Auto-fetch HTFs based on the ladder
    htf_data = _auto_fetch_htf(symbol, op_tf)
    df = run_smc_analysis(df, htf_data=htf_data, symbol=symbol, timeframe=op_tf)
```

The `_auto_fetch_htf` helper is the same one used by `engine.py` — extract it to a shared location (`backend/app/core/smc/_htf_ladder.py`) so both `pre_process` and `engine.py` use the same logic.

**Important**: when a strategy declares `'smc'` in `required_features`, it must also add `'smc'` to its `feature_config` (e.g., `feature_config = {'smc': {'include_zones': True, 'include_liquidity': True, 'include_bias': True}}` — the dict allows future per-strategy SMC config without bloating the 5-param budget).

### 6.2 New `/api/smc/engine` endpoint

Create `backend/app/blueprints/smc_bp.py`:

```python
from flask import Blueprint, request, jsonify

smc_bp = Blueprint('smc', __name__, url_prefix='/api/smc')

@smc_bp.route('/engine', methods=['GET'])
def get_smc_engine():
    """
    Returns the full SMC analysis for a symbol + timeframe.

    Query params:
        symbol (required): e.g. 'BTCUSDT'
        timeframe (default '15m'): e.g. '1h', '4h', '15m'
        limit (default 500): how many candles to analyze
        htf_depth (default 3): how many HTFs to fetch (1, 2, or 3)

    Returns:
        JSON with:
            symbol, timeframe
            candles_scanned, generated_at
            smc_context: list of per-bar SMContext snapshots (one per candle)
            performance_ms: how long the engine took

    Each SMContext in the list is a serialized version of the SMContext
    dataclass (frozen, with active_fvgs and active_obs as compact lists).
    """
    symbol = request.args.get('symbol')
    if not symbol:
        return jsonify({'error': 'Missing required query parameter: symbol'}), 400
    timeframe = request.args.get('timeframe', '15m')
    limit = request.args.get('limit', 500, type=int)
    htf_depth = request.args.get('htf_depth', 3, type=int)

    try:
        from app.core.data_utils import get_finalized_candles, StaleDataError
        from app.core.smc.engine import run_smc_analysis
        from app.core.smc.context import smc_context_from_row
        from app.core.smc._htf_ladder import _HTF_LADDER

        df = get_finalized_candles(symbol, timeframe, limit=limit)
        if len(df) == 0:
            return jsonify({'symbol': symbol, 'timeframe': timeframe, 'smc_context': []}), 200

        htf_tfs = _HTF_LADDER.get(timeframe, ['1h', '4h', '1d'])[:htf_depth]
        htf_data = {tf: get_finalized_candles(symbol, tf, limit=200) for tf in htf_tfs}

        t0 = time.time()
        df_enr = run_smc_analysis(df, htf_data=htf_data, symbol=symbol, timeframe=timeframe)
        elapsed_ms = (time.time() - t0) * 1000

        # Build per-bar SMContext snapshots
        contexts = []
        for _, row in df_enr.iterrows():
            ctx = smc_context_from_row(row, symbol=symbol, timeframe=timeframe)
            contexts.append(_serialize_context(ctx))

        return jsonify({
            'symbol': symbol,
            'timeframe': timeframe,
            'candles_scanned': len(df_enr),
            'generated_at': datetime.utcnow().isoformat() + 'Z',
            'smc_context': contexts,
            'performance_ms': elapsed_ms,
        }), 200

    except StaleDataError as e:
        return jsonify({
            'symbol': symbol, 'timeframe': timeframe, 'smc_context': [],
            'warning': f'Candle data is stale: {e}'
        }), 200
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
```

The `_serialize_context` helper converts the SMContext (with named tuples and Optionals) to a JSON-serializable dict.

### 6.3 Parity backtest against v1

Before deleting the v1 code, run a 60-day parity backtest:

```python
# backend/scripts/smc_v1_v2_parity.py
import pandas as pd
from app.core.data_utils import get_finalized_candles
from app.strategies.archive.smc_v1.events import detect_choch as v1_choch
from app.strategies.archive.smc_v1.events import detect_liquidity_sweep as v1_sweep
from app.strategies.archive.smc_v1.market_structure import extract_fvgs as v1_fvgs
from app.strategies.archive.smc_v1.market_structure import extract_order_blocks as v1_obs
from app.core.smc.engine import run_smc_analysis
from app.core.smc.context import smc_context_from_row

# 60-day held-out window: last 60 days of BTC 15m
df = get_finalized_candles('BTCUSDT', '15m', limit=4*96*60)

# v1 path
df_v1 = df.copy()
df_v1 = v1_choch(df_v1)
df_v1 = v1_sweep(df_v1)
df_v1 = v1_fvgs(df_v1)
df_v1 = v1_obs(df_v1)

# v2 path
df_v2 = run_smc_analysis(df.copy(), symbol='BTCUSDT', timeframe='15m')

# Compare event counts
v1_choch_count = df_v1['event_choch_bullish'].sum() + df_v1['event_choch_bearish'].sum()
v2_choch_count = ((df_v2['struct_swing_event'] == 'SCHOCH_UP').sum() +
                  (df_v2['struct_swing_event'] == 'SCHOCH_DOWN').sum())
v1_fvg_count = df_v1[df_v1['fvg_active']]['fvg_active'].sum()
v2_fvg_count = df_v2['fvg_active'].sum()
v1_ob_count = df_v1['ob_active'].sum()
v2_ob_count = df_v2['ob_active'].sum()
v1_sweep_count = df_v1['event_sweep_bullish'].sum() + df_v1['event_sweep_bearish'].sum()
v2_sweep_count = (df_v2['event_sweep_pdh'].sum() + df_v2['event_sweep_pdl'].sum() +
                  df_v2['event_sweep_pwh'].sum() + df_v2['event_sweep_pwl'].sum() +
                  df_v2['event_sweep_eqh'].sum() + df_v2['event_sweep_eql'].sum() +
                  df_v2['event_sweep_asian_h'].sum() + df_v2['event_sweep_asian_l'].sum() +
                  df_v2['event_sweep_london_h'].sum() + df_v2['event_sweep_london_l'].sum() +
                  df_v2['event_sweep_ny_h'].sum() + df_v2['event_sweep_ny_l'].sum())

# v2 should have >= v1 counts (v2 detects more due to internal structures, more sweep sources)
assert v2_choch_count >= v1_choch_count, f'CHoCH regression: v2={v2_choch_count} < v1={v1_choch_count}'
assert v2_fvg_count >= v1_fvg_count, f'FVG regression: v2={v2_fvg_count} < v1={v1_fvg_count}'
assert v2_ob_count >= v1_ob_count, f'OB regression: v2={v2_ob_count} < v1={v1_ob_count}'
# Sweep: v2 has more sweep sources (12 vs v1's 2), so v2 should have >= v1
assert v2_sweep_count >= v1_sweep_count, f'Sweep regression: v2={v2_sweep_count} < v1={v1_sweep_count}'

print(f'PARITY: v1 choch={v1_choch_count}, v2 schoch={v2_choch_count} (>= v1: {v2_choch_count >= v1_choch_count})')
print(f'PARITY: v1 fvg_active={v1_fvg_count}, v2 fvg_active={v2_fvg_count} (>= v1: {v2_fvg_count >= v1_fvg_count})')
print(f'PARITY: v1 ob_active={v1_ob_count}, v2 ob_active={v2_ob_count} (>= v1: {v2_ob_count >= v1_ob_count})')
print(f'PARITY: v1 sweep={v1_sweep_count}, v2 sweep (all sources)={v2_sweep_count} (>= v1: {v2_sweep_count >= v1_sweep_count})')
print('PARITY: all 4 checks pass')
```

If the parity backtest fails, **do not delete v1**. Investigate the regression first.

### 6.4 Archive v1 (after parity passes)

After the parity backtest passes, v1 is no longer needed for live use. Move it to a deeper archive:

```bash
mkdir -p backend/app/strategies/archive/smc_v1/
# v1 was already moved to backend/app/strategies/archive/smc_v1/ in Phase 0
# Now move it one more level deep:
mv backend/app/strategies/archive/smc_v1/market_structure.py backend/app/strategies/archive/smc_v1_archived.py
mv backend/app/strategies/archive/smc_v1/events.py           backend/app/strategies/archive/smc_v1_archived_events.py
mv backend/app/strategies/archive/smc_v1/fractals.py         backend/app/strategies/archive/smc_v1_archived_fractals.py
# (rename to make it clear they're archived, but keep them in archive/ for reference)
```

The `/api/sr-zones/smc-zones` endpoint from Phase 0 was already updated to import from the archive location. It stays for one more release cycle as a parity reference, then is removed.

### 6.5 Update v1 callers in `sr_zones_bp.py`

The Phase 0 task updated the import paths; this phase ensures the v1 endpoint still works:

```bash
# Verify the v1 endpoint still works
curl -s "http://localhost:5000/api/sr-zones/smc-zones?symbol=BTCUSDT&timeframe=15m&limit=100" | head -c 500
```

Expected: JSON with `zones: [...]` and a non-zero `count`. If the response is empty, the v1 import path was missed.

## Manual Verification

### Verify 6.1 — pre_process integration

```bash
cd backend && python -c "
import pandas as pd
from app.core.data_utils import get_finalized_candles
from app.core.base_strategy import BaseStrategy

# Create a minimal strategy that requests 'smc' feature
class TestSMCStrategy(BaseStrategy):
    name = 'Test SMC'
    timeframes = ['15m']
    required_features = ['ema', 'rsi', 'atr', 'volume_ma', 'smc']
    def generate_signals(self, df):
        return df  # no signals; we just want to verify the pre_process works

df = get_finalized_candles('BTCUSDT', '15m', limit=500)
strat = TestSMCStrategy()
df_enr = strat.pre_process(df, symbol='BTCUSDT', timeframe='15m')

# Verify the SMC columns are present
for col in ['smc_weekly_bias', 'smc_daily_bias', 'pd_zone', 'fvg_active',
            'ob_active', 'liq_pdh', 'struct_swing_event']:
    assert col in df_enr.columns, f'pre_process did not add {col} via smc feature'
print(f'TestSMCStrategy.pre_process added {len(df_enr.columns)} columns total')
print('OK: pre_process integrates smc feature')
"
```

**Pass criteria**: all 7 expected columns are added by `pre_process` when `'smc'` is in `required_features`. The number of total columns should be 80+.

### Verify 6.2 — `/api/smc/engine` endpoint

```bash
# Start the Flask app in another terminal (or assume it's running)
cd backend && python run.py &

# Wait for it to come up
sleep 5

# Hit the new endpoint
curl -s "http://localhost:5000/api/smc/engine?symbol=BTCUSDT&timeframe=15m&limit=200" | python -c "
import json, sys
data = json.load(sys.stdin)
assert 'smc_context' in data
assert 'candles_scanned' in data
assert 'performance_ms' in data
assert len(data['smc_context']) == data['candles_scanned']
# Spot-check the first context
ctx = data['smc_context'][0]
assert 'session' in ctx
assert 'weekly_bias' in ctx
assert 'pd_zone' in ctx
print(f'OK: /api/smc/engine returns {len(data[\"smc_context\"])} contexts in {data[\"performance_ms\"]:.0f}ms')
"
```

**Pass criteria**:
- The endpoint returns 200 OK.
- The response includes `smc_context` (a list of per-bar snapshots), `candles_scanned`, and `performance_ms`.
- Each context includes the categorical fields (`session`, `weekly_bias`, `pd_zone`).
- `performance_ms` is < 5000ms (the < 5s requirement from Phase 4).

### Verify 6.3 — parity backtest

```bash
cd backend && python scripts/smc_v1_v2_parity.py
```

**Pass criteria**: the script prints `PARITY: all 4 checks pass`. If any check fails, the script exits with a non-zero status.

### Verify 6.4 — v1 endpoint still works

```bash
curl -s "http://localhost:5000/api/sr-zones/smc-zones?symbol=BTCUSDT&timeframe=15m&limit=100" | python -c "
import json, sys
data = json.load(sys.stdin)
assert 'zones' in data
assert data['count'] > 0, f'v1 endpoint returned 0 zones'
print(f'OK: v1 endpoint still returns {data[\"count\"]} zones')
"
```

**Pass criteria**: the v1 endpoint returns a non-zero count. This is a sanity check — if the v1 endpoint is broken, the archive structure is wrong.

### Verify 6.5 — full engine smoke test

```bash
cd backend && python -c "
import pandas as pd
from app.core.data_utils import get_finalized_candles
from app.core.smc.engine import run_smc_analysis
from app.core.smc.validators import run_all_validators
from app.core.smc.context import smc_context_from_row

# Full 2-year BTC 15m
df = get_finalized_candles('BTCUSDT', '15m', limit=70_000)
df_1h  = get_finalized_candles('BTCUSDT', '1h',  limit=20_000)
df_4h  = get_finalized_candles('BTCUSDT', '4h',  limit=5_000)
df_1d  = get_finalized_candles('BTCUSDT', '1d',  limit=1_000)

df_enr = run_smc_analysis(df, htf_data={'1h': df_1h, '4h': df_4h, '1d': df_1d},
                          symbol='BTCUSDT', timeframe='15m')
print(f'enriched: {len(df_enr)} rows, {len(df_enr.columns)} columns')

# Run all validators
def signal_func(d):
    sig = (d['struct_trend_swing'] == 1) if 'struct_trend_swing' in d else pd.Series(False, index=d.index)
    fwd = d['close'].pct_change(4).shift(-4)
    return sig, fwd

result = run_all_validators(df, htf_data={'1h': df_1h, '4h': df_4h, '1d': df_1d},
                             symbol='BTCUSDT', timeframe='15m', signal_func=signal_func)
print(f'lookahead: {\"PASS\" if result[\"lookahead\"][\"pass\"] else \"FAIL\"}')
print(f'ic passes: {sum(1 for r in result[\"ic_tests\"] if r[\"passes_validation\"])}/{len(result[\"ic_tests\"])}')
print(f'walk-forward: {result[\"walk_forward\"][\"summary\"][\"is_viable\"]}')
print(f'regime coverage: {result[\"regime_coverage\"][\"is_adequate\"]}')
print(f'ship: {result[\"ship\"]}')
"
```

**Pass criteria**:
- The engine runs end-to-end on the full 2-year dataset.
- Lookahead audit passes.
- The IC test runs for all 12 signals (some pass, some fail).
- The walk-forward runs.
- The regime coverage test runs.
- The `ship` verdict is printed.

The `ship` flag may be False — that's expected, because the toy `signal_func` in this test isn't a real strategy. The ship gate is meant to be run with a *real* signal function. The point here is that the harness works.

## Final Deliverable

- `BaseStrategy.pre_process` supports the `'smc'` feature.
- `/api/smc/engine` endpoint returns the full SMC context in < 5s.
- Parity backtest (`scripts/smc_v1_v2_parity.py`) passes.
- v1 code is moved to a deeper archive; v1 endpoint still works for one cycle.
- All 5 manual verification checks pass.

## Next Phase

→ [Phase 7: Frontend](./phase-7-frontend.md) — extend the chart UI to render the new SMC layers.
