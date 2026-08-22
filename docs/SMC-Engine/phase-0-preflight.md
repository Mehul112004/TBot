# Phase 0: Pre-flight

> **Future SMC v2 design.** This phase plan is not a record of completed runtime modules; see [the SMC design status](README.md).

## Goal

Before writing any SMC engine code, verify the environment, data availability, and prep the codebase for v1 archival. This phase has **zero new logic** — it is gates and prep.

## Tasks

### 0.1 Verify data availability (BLOCKING)

The validation universe (BTC + ETH + SOL) needs ≥ 2 years of 15m candles. Check what's actually in the database before doing anything else.

```sql
SELECT
  symbol,
  timeframe,
  COUNT(*)                AS candle_count,
  MIN(open_time)          AS earliest,
  MAX(open_time)          AS latest,
  EXTRACT(DAY FROM (MAX(open_time) - MIN(open_time))) AS days_covered
FROM candles
WHERE timeframe = '15m' AND symbol IN ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
GROUP BY symbol, timeframe
ORDER BY symbol;
```

**Pass criteria**:
- All 3 symbols present.
- ≥ 2 × 365 = 730 days of 15m data per symbol (i.e., ≥ 69,888 candles per symbol, since 15m × 96 bars/day = ~35,040/year).
- `earliest` no later than `today - 730 days`.

If you fail this gate: import more data via `POST /api/data/import/binance` (per the data blueprint at `backend/app/blueprints/data.py:11`). Do not proceed to Phase 1 until all 3 symbols clear.

### 0.2 Verify HTF coverage (BLOCKING for the engine's LTF-anchored use)

The 1H, 4H, 1D candles are derived by the engine from a single underlying dataset, but you still need to confirm the LTF table has at least the LTF rows (15m) — the HTFs are typically fetched/derived from the same source rows. Just check:

```sql
SELECT symbol, COUNT(*) AS rows_15m
FROM candles WHERE timeframe = '15m' AND symbol = 'BTCUSDT'
GROUP BY symbol;
```

Pass: ≥ 70,000 rows. (The engine calls `get_finalized_candles` per TF separately, so a multi-TF check is done at runtime by `mtf.py` in Phase 1.)

### 0.3 Archive the current SMC code (PROMOTES, doesn't break)

Move the v1 SMC code to a dedicated archive directory. This is a soft delete — git history preserves the originals.

```bash
mkdir -p backend/app/strategies/archive/smc_v1
git mv backend/app/core/market_structure.py backend/app/strategies/archive/smc_v1/market_structure.py
git mv backend/app/core/events.py           backend/app/strategies/archive/smc_v1/events.py
git mv backend/app/core/fractals.py         backend/app/strategies/archive/smc_v1/fractals.py
```

Update the import path **temporarily** in callers. The known live caller is `/api/sr-zones/smc-zones` (`backend/app/blueprints/sr_zones_bp.py:345-369`):

```python
# OLD
from app.core.market_structure import extract_fvgs, extract_order_blocks
from app.core.events import detect_choch, detect_liquidity_sweep

# NEW (temporary — replaced permanently in Phase 6)
from app.strategies.archive.smc_v1.market_structure import extract_fvgs, extract_order_blocks
from app.strategies.archive.smc_v1.events import detect_choch, detect_liquidity_sweep
```

`market_regime.py` stays in place — it is in active use by the live strategies and will not be touched.

**Pass criteria**:
- Flask app still boots: `python backend/run.py` → no `ImportError` on any route.
- `/api/sr-zones/smc-zones?symbol=BTCUSDT&timeframe=15m` still returns zones (v1 contract is unchanged from the outside).

### 0.4 Create the new package skeleton (no logic)

```bash
mkdir -p backend/app/core/smc
touch backend/app/core/smc/__init__.py
```

The `__init__.py` should expose the public API (skeleton — populated at end of Phase 4):

```python
"""
SMC Engine v2.0 — multi-timeframe Smart Money Concepts.

Public API:
    run_smc_analysis(df_15m, htf_data, symbol) -> pd.DataFrame
    SMContext (frozen dataclass)
"""
from .engine import run_smc_analysis
from .context import SMContext

__all__ = ["run_smc_analysis", "SMContext"]
```

`engine.py` and `context.py` are placeholders for now (will raise `NotImplementedError`). Don't import them until Phase 4.

### 0.5 Pre-flight quant environment check

Confirm you can run a backtest with the standard cost model. From `backend/`:

```bash
python -c "
import pandas as pd
import numpy as np
from scipy import stats
from statsmodels.regression.linear_model import OLS
import statsmodels.api as sm
print('quant env OK')
"
```

All four imports must succeed. If `statsmodels` is missing:

```bash
pip install statsmodels scipy
```

(This is a one-time install — these libraries are referenced by the quant validation script you'll write in Phase 5.)

### 0.6 Add a param budget to the codebase

Create `backend/app/core/smc/_params.py`:

```python
"""
SMC engine parameter registry.

Every numeric knob in the engine is declared here. The 5-free-param
budget (per sharp_edges.md#curve-fitting-excuses) is enforced at
import time: more than 5 entries with kind='tunable' raises.
"""
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class Param:
    name: str
    value: float
    kind: Literal["tunable", "constant"]
    doc: str

PARAMS = [
    Param("swing_pivot_bars",          10,  "tunable", "HTF-degree pivot window (swings.py)"),
    Param("internal_pivot_bars",        3,  "tunable", "LTF-degree pivot window (swings.py)"),
    Param("atr_displacement_mult",    1.5,  "tunable", "OB impulse ATR gate (order_blocks.py)"),
    Param("equal_hl_tolerance_pct", 0.001,  "tunable", "EH/EL cluster tolerance (liquidity.py)"),
    Param("fvg_min_distance_atr",    0.25,  "tunable", "Min FVG size to be tradeable (fvgs.py)"),
]

# Constants — not part of the 5-budget. These are *fixed by design* and
# must not be tuned. Adding them here makes it explicit they're locked.
CONSTANTS = [
    Param("equilibrium_pct",           0.5, "constant", "Premium/Discount equilibrium = 50%"),
    Param("bos_confirmation",          0,  "constant", "BOS rule = body-close (0 = body, 1 = wick)"),
    Param("fvg_fill_rule",             0,  "constant", "FVG fill = wick pierce"),
    Param("ob_mitigation_rule",        0,  "constant", "OB mitigation = body close through boundary"),
]

def _check_budget() -> None:
    tunables = [p for p in PARAMS if p.kind == "tunable"]
    if len(tunables) > 5:
        raise RuntimeError(
            f"Rule of 5 violated: {len(tunables)} tunable params. "
            f"Got: {[p.name for p in tunables]}. "
            f"Either lock a param to constant or merge two params."
        )

_check_budget()
```

This file's import side-effect enforces the budget. Adding a 6th tunable later will hard-fail with a clear message.

## Manual Verification

### Verify 0.1 — data availability

```bash
# From project root
docker exec -it <postgres_container> psql -U <user> -d tbot -c "
  SELECT symbol, COUNT(*) AS rows, MIN(open_time)::date AS from_, MAX(open_time)::date AS to_
  FROM candles WHERE timeframe='15m' AND symbol IN ('BTCUSDT','ETHUSDT','SOLUSDT')
  GROUP BY symbol ORDER BY symbol;
"
```

Expected output (3 rows, all symbols, all with ≥ 70,000 rows, all covering ≥ 730 days):

```
  symbol   |  rows   |   from_    |    to_
-----------+---------+------------+------------
 BTCUSDT   |  71123  | 2023-...   | 2026-...
 ETHUSDT   |  70210  | 2023-...   | 2026-...
 SOLUSDT   |  68900  | 2023-...   | 2026-...
```

**If any symbol returns 0 rows**: import via `curl -X POST http://localhost:5000/api/data/import/binance -H "Content-Type: application/json" -d '{"symbol":"BTCUSDT","timeframe":"15m","days":800}'` and re-run. Do NOT proceed to Phase 1.

### Verify 0.2 — HTF coverage

Same query, no separate check needed: `mtf.py` will fail loudly at Phase 1 if HTF data is missing for a symbol+TF. The runtime check there is your real verification.

### Verify 0.3 — v1 routes still work

```bash
curl -s "http://localhost:5000/api/sr-zones/smc-zones?symbol=BTCUSDT&timeframe=15m&limit=100" | head -c 500
```

Expected: JSON with `zones: [...]` and a non-zero `count`. If you get a 500, an import path was missed.

```bash
# Also smoke-test that no other caller is broken
grep -rn "from app.core.market_structure\|from app.core.events\|from app.core.fractals" backend/ --include="*.py"
```

Expected: zero matches outside the archive directory.

### Verify 0.4 — package skeleton

```bash
python -c "import app.core.smc; print('smc package OK')"
```

Expected: `smc package OK` (no import errors; the `__init__.py` is a stub but the module imports).

### Verify 0.5 — quant env

```bash
cd backend && python -c "
import pandas, numpy, scipy.stats, statsmodels.api, statsmodels.regression.linear_model
print('quant env OK')
"
```

Expected: `quant env OK`.

### Verify 0.6 — param budget

```bash
cd backend && python -c "
from app.core.smc import _params
print(f'tunables: {len([p for p in _params.PARAMS if p.kind==\"tunable\"])}/5')
print(f'constants: {len(_params.CONSTANTS)}')
"
```

Expected:

```
tunables: 5/5
constants: 4
```

If the count is off, `_check_budget()` raised and you'll see a `RuntimeError` with the full message. That is the *intended* failure mode for any future PR that adds a 6th tunable.

## Final Deliverable

- 3 symbols with ≥ 2 years of 15m data in `candles` table.
- v1 SMC code archived to `backend/app/strategies/archive/smc_v1/`.
- `/api/sr-zones/smc-zones` still functional (parity preserved).
- New `backend/app/core/smc/` package skeleton with `_params.py` enforcing the 5-param budget.
- No other codebase changes.

## Next Phase

→ [Phase 1: Foundation](./phase-1-foundation.md) — write `mtf.py`, `swings.py`, `sessions.py`.
