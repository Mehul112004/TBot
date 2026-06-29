# Phase 7: Frontend — Chart UI for the new SMC engine

## Goal

Extend the chart UI in `frontend/src/pages/Charts/` to render all the new SMC layers from the v2 engine. The frontend already has a working chart (candles, EMA lines, S/R zones, v1 FVG/OB/event markers). This phase adds new layers without breaking the existing ones.

The new layers are:

1. **HTF FVG/OB projection** — HTF zones projected onto the LTF price axis with TF tags (e.g., "4H OB BULL").
2. **Liquidity levels** — PDH, PDL, PWH, PWL, Asian/London/NY range H/L, equal highs/lows, with distinct colors per source.
3. **Premium/Discount bands** — colored background bands marking premium (red) and discount (green) zones relative to equilibrium.
4. **Session / Kill-zone background tinting** — the chart background tints by session, brighter during kill zones.
5. **Bias badge** — top-right badge showing weekly/daily bias state (analogous to the existing regime badge).
6. **Updated `SMCZone` interface** — extend to support all new types.
7. **Sweep event markers** — wick-level arrows with "Sweep PDH" / "Sweep EQH" / etc. text.

The frontend fetches from the new `/api/smc/engine` endpoint (in parallel with the existing `/smc-zones` v1 endpoint) and renders the new layers in toggleable groups.

## Files Modified

| File | Change |
|---|---|
| `frontend/src/api/client.ts` | Add `SMCContext`, `LiquidityLevel`, `PDRange` interfaces; add `fetchSMCEngine()` |
| `frontend/src/pages/Charts/Charts.tsx` | Add toggle state for new layers; fetch new endpoint in parallel |
| `frontend/src/pages/Charts/useChartData.ts` | Wire `fetchSMCEngine` into the data hook |
| `frontend/src/pages/Charts/ChartControls.tsx` | Add new toggle buttons |
| `frontend/src/pages/Charts/CandleChart.tsx` | Add new rendering primitives and lines |

## Tasks

### 7.1 Extend `SMCZone` and add new interfaces in `client.ts`

The current `SMCZone` interface at `client.ts:216` covers `fvg`, `ob`, `event`. Extend it to support the new layers:

```typescript
// client.ts:216 — replace the current SMCZone with:
export interface SMCZone {
  type: 'fvg' | 'ob' | 'event' | 'liq' | 'pd_band' | 'sweep';
  direction?: 'bullish' | 'bearish' | 'neutral';
  label?: string;
  upper?: number;
  lower?: number;
  fill_pct?: number;          // 0..1, for FVGs
  mitigation_pct?: number;    // 0..1, for OBs
  mitigated?: boolean;
  mitigated_at?: string;
  volume?: number;
  created_at?: string;
  active?: boolean;
  time?: string;              // for events
  tf?: string;                // NEW: '15m' | '1h' | '4h' | '1d' for HTF projection
  source?: 'pdh' | 'pdl' | 'pwh' | 'pwl' | 'asian_h' | 'asian_l'
         | 'london_h' | 'london_l' | 'ny_h' | 'ny_l' | 'eqh' | 'eql';
  impulse_quality?: 'A' | 'B' | 'C';   // for OBs
}

export interface SMCSnapshot {
  timestamp: string;
  session: string;
  is_kill_zone: boolean;
  weekly_bias: 'bull' | 'bear' | 'neutral';
  daily_bias: 'bull' | 'bear' | 'neutral' | 'tentative_bull' | 'tentative_bear';
  bias_confirmed: boolean;
  pd_zone: 'premium' | 'equilibrium' | 'discount';
  equilibrium: number | null;
  range_high: number | null;
  range_low: number | null;
  swing_trend: -1 | 0 | 1;
  nearest_buy_side: number | null;
  nearest_sell_side: number | null;
  pdl: number | null; pdh: number | null;
  pwl: number | null; pwh: number | null;
  eqh: number | null; eql: number | null;
}

export interface SMCEngineResponse {
  symbol: string;
  timeframe: string;
  candles_scanned: number;
  generated_at: string;
  performance_ms: number;
  snapshots: SMCSnapshot[];   // one per candle
  zones: SMCZone[];           // active zones across all candles
}

export const fetchSMCEngine = async (
  symbol: string,
  timeframe: string = '15m',
  limit: number = 500,
): Promise<SMCEngineResponse> => {
  const { data } = await apiClient.get('/smc/engine', {
    params: { symbol, timeframe, limit },
  });
  return data;
};
```

### 7.2 Add new toggle state in `Charts.tsx`

```typescript
const [showHTFProjection, setShowHTFProjection] = useState(true);
const [showLiquidityLevels, setShowLiquidityLevels] = useState(true);
const [showPDBand, setShowPDBand] = useState(true);
const [showSessionBands, setShowSessionBands] = useState(true);
const [showBiasBadge, setShowBiasBadge] = useState(true);
const [showSweeps, setShowSweeps] = useState(true);
```

Pass these to the new primitives in `CandleChart.tsx`.

### 7.3 New rendering primitives in `CandleChart.tsx`

#### 7.3.1 `LiquidityPriceLinesPrimitive`

Renders PDH/PDL/PWH/PWL/Asian H/L/etc. as labelled price lines, distinct color per source. Mirrors the existing `SRBandPrimitive` pattern at `CandleChart.tsx:119-185`.

Color map (locked):

```typescript
const LIQ_COLORS: Record<string, string> = {
  pdh: '#dc2626',    // red-600
  pdl: '#16a34a',    // green-600
  pwh: '#9333ea',    // purple-600
  pwl: '#ca8a04',    // yellow-600
  asian_h: '#0891b2', // cyan-600
  asian_l: '#0891b2',
  london_h: '#7c3aed', // violet-600
  london_l: '#7c3aed',
  ny_h: '#db2777',   // pink-600
  ny_l: '#db2777',
  eqh: '#f59e0b',    // amber-500 (dashed — equal highs/lows are clusters)
  eql: '#f59e0b',
};
```

Each line is rendered as `series.createPriceLine({ price, color, lineStyle: 2, title: "PDH 42500.00" })`. Mirror the existing `smcPriceLinesRef` pattern (CandleChart.tsx:255-257, 654-759) but for liquidity.

#### 7.3.2 `PremiumDiscountBandPrimitive`

Renders the premium/discount zones as filled background bands. Mirrors `SRBandPrimitive` (CandleChart.tsx:119-185) but uses the equilibrium from the latest SMCSnapshot to anchor.

```typescript
class PremiumDiscountBandPrimitive implements ISeriesPrimitive, IPrimitivePaneView, IPrimitivePaneRenderer {
  private _equilibrium: number | null = null;
  private _range_high: number | null = null;
  private _range_low: number | null = null;

  setBand(eq: number, high: number, low: number) {
    this._equilibrium = eq;
    this._range_high = high;
    this._range_low = low;
    this._requestUpdate?.();
  }

  draw(target) {
    // Render two bands: premium (above eq, red tint) and discount (below eq, green tint)
    // Faint alpha so it doesn't obscure candles
  }
}
```

Use alpha 0.04 — same as the existing S/R band primitive.

#### 7.3.3 `SessionBandPrimitive`

Renders session/kill-zone background tinting. **Horizontal** bands don't work for sessions (sessions are *time* intervals, not price intervals) — use a **vertical** band approach: tint the chart background between two timestamps.

The simplest implementation: use a separate `ISeriesApi<'Area'>` series with NaN outside the session, OR overlay a colored rectangle via the canvas primitive. The latter is consistent with the existing `SRBandPrimitive` pattern.

A vertical band primitive:

```typescript
class SessionBandPrimitive implements ISeriesPrimitive, IPrimitivePaneView, IPrimitivePaneRenderer {
  private _bands: Array<{ start: UTCTimestamp; end: UTCTimestamp; isKillZone: boolean; session: string }> = [];

  setBands(bands) { ... }

  draw(target) {
    target.useBitmapCoordinateSpace((scope) => {
      for (const band of this._bands) {
        const xStart = this._series.coordinateToTime ? null : null;  // lightweight-charts API quirk
        // Use the timeScale to convert timestamps to x pixels
        // ... (implementation requires accessing timeScale, which is at the chart level, not the series)
      }
    });
  }
}
```

**Implementation note**: lightweight-charts' `ISeriesPrimitive` doesn't have direct access to the time scale. To do vertical bands, we need a different approach: add a secondary `ISeriesApi<'Area'>` series with NaN-valued segments. This is the standard pattern for session tinting in lightweight-charts.

**Simpler approach for Phase 7**: render session/kill-zone tinting as a single faint **vertical line** at the start of each session, NOT a full band. This is less visually appealing but easier to implement. Document this as a known limitation; revisit in a later phase.

#### 7.3.4 `BiasBadge` — top-right overlay

Mirror the existing `currentRegime` badge at `CandleChart.tsx:944-964`. The new badge shows the latest SMCSnapshot's bias state:

```typescript
{currentBias && (
  <div className="flex items-center gap-1.5 px-2.5 py-1 border rounded-md font-bold font-mono text-xs uppercase tracking-wider"
       style={{ background: 'rgba(15, 23, 42, 0.85)',
                borderColor: currentBias.weekly === 'bull' ? 'rgba(16, 185, 129, 0.4)' :
                              currentBias.weekly === 'bear' ? 'rgba(239, 68, 68, 0.4)' :
                              'rgba(167, 139, 250, 0.4)',
                color: currentBias.weekly === 'bull' ? '#10b981' :
                       currentBias.weekly === 'bear' ? '#ef4444' : '#a78bfa' }}>
    {currentBias.weekly} → {currentBias.daily}{currentBias.bias_confirmed ? ' ✓' : ' (tentative)'}
  </div>
)}
```

#### 7.3.5 HTF zone projection

The `smcZones` array (from `useChartData`) now contains both LTF and HTF zones (the new endpoint returns all of them). The existing rendering logic at `CandleChart.tsx:654-759` already supports `zone.tf` — extend it to use a fainter color for HTF zones (alpha 0.5) and label them with their TF:

```typescript
// CandleChart.tsx around line 720, extend the title
const tfTag = zone.tf && zone.tf !== timeframe ? `${zone.tf.toUpperCase()} ` : '';
const title = `${tfTag}${label} ${mid.toFixed(2)}`;
```

#### 7.3.6 Sweep event markers

The new endpoint returns `type: 'sweep'` zones. The existing marker-rendering logic at `CandleChart.tsx:682-708` already supports them with `text: zone.label`. Extend the label to include the source:

```typescript
text: `Sweep ${zone.source?.toUpperCase() || ''} ${zone.direction === 'bullish' ? '↑' : '↓'}`
```

Color: use the source color from the `LIQ_COLORS` map.

### 7.4 New toggle buttons in `ChartControls.tsx`

Mirror the existing "SMC Zones" toggle pattern (ChartControls.tsx:295-303) for each new layer:

```typescript
{/* HTF Projection Toggle */}
<button onClick={onToggleHTFProjection} ...>HTF Projection</button>

{/* Liquidity Levels Toggle */}
<button onClick={onToggleLiquidityLevels} ...>Liquidity</button>

{/* Premium/Discount Toggle */}
<button onClick={onTogglePDBand} ...>Premium/Discount</button>

{/* Sessions/Kill Zones Toggle */}
<button onClick={onToggleSessionBands} ...>Kill Zones</button>

{/* Bias Badge Toggle */}
<button onClick={onToggleBiasBadge} ...>Bias Badge</button>

{/* Sweep Markers Toggle */}
<button onClick={onToggleSweeps} ...>Sweeps</button>
```

### 7.5 Wire `fetchSMCEngine` into `useChartData.ts`

In the data hook, fetch the new endpoint in parallel with the existing ones (useChartData.ts:108-128). The hook already returns `currentRegime` (line 28) — add `currentBias` as a new field:

```typescript
const [state, setState] = useState<...>({
  ...,
  currentBias: undefined,   // NEW
});

// In the load() function, add:
const smcEngineResult = await fetchSMCEngine(symbol, timeframe, Math.min(limit, 500));
const latestSnapshot = smcEngineResult.snapshots[smcEngineResult.snapshots.length - 1];

setState(prev => ({
  ...prev,
  currentBias: latestSnapshot ? {
    weekly: latestSnapshot.weekly_bias,
    daily:  latestSnapshot.daily_bias,
    bias_confirmed: latestSnapshot.bias_confirmed,
  } : null,
  // ... (existing fields)
}));
```

## Manual Verification

### Verify 7.1 — API client types compile

```bash
cd frontend && npm run build
```

**Pass criteria**: the TypeScript build passes. The `SMCZone` and `SMCSnapshot` interfaces are referenced by the chart components, so any type error will fail the build.

### Verify 7.2 — New endpoint integration

```bash
# Start the backend in one terminal
cd backend && python run.py &

# In another terminal, hit the new endpoint
curl -s "http://localhost:5000/api/smc/engine?symbol=BTCUSDT&timeframe=15m&limit=200" | python -c "
import json, sys
data = json.load(sys.stdin)
assert 'snapshots' in data
assert 'zones' in data
assert 'performance_ms' in data
print(f'snapshots: {len(data[\"snapshots\"])}, zones: {len(data[\"zones\"])}, time: {data[\"performance_ms\"]:.0f}ms')

# Spot-check a snapshot
snap = data['snapshots'][0]
required = ['timestamp', 'session', 'is_kill_zone', 'weekly_bias', 'daily_bias',
            'pd_zone', 'equilibrium', 'range_high', 'range_low', 'swing_trend',
            'nearest_buy_side', 'nearest_sell_side', 'pdh', 'pdl', 'eqh']
for k in required:
    assert k in snap, f'missing key: {k}'
print('OK: SMC engine response structure')
"
```

**Pass criteria**:
- The endpoint returns 200 OK.
- `snapshots` and `zones` are non-empty lists.
- `performance_ms` is reasonable (< 5000ms for 200 bars).
- All required fields are present in the snapshots.

### Verify 7.3 — Frontend renders new layers

The chart UI verification is **interactive** — there is no headless test for visual rendering. The verification is:

1. Open `http://localhost:5173/charts` in your browser.
2. Select `BTCUSDT` and `15m`.
3. Wait for the chart to load.
4. **Verify each new layer**:

| Layer | What to look for | Pass criteria |
|---|---|---|
| HTF FVG/OB projection | Faint dashed lines labelled "1H FVG BULL" / "4H OB BEAR" etc. | At least 2 HTF zones visible on a 200-bar window |
| Liquidity levels | Red/green/purple/cyan/amber dashed lines labelled "PDH 42500.00" etc. | PDH and PDL visible (any of them, since they may be far from current price) |
| Premium/Discount band | Faint red band above the equilibrium, green below | A visible color band spanning the chart width |
| Sessions | A subtle background tinting per session (or vertical lines at session boundaries, given the Phase 7 simplification) | A vertical line at every 8h boundary (00:00, 08:00, 13:00, 20:00 UTC) |
| Bias badge | Top-right, shows e.g., "BULL → BULL ✓" or "BEAR → BEAR (tentative)" | A visible badge in the top-right overlay stack |
| Sweep markers | Arrow markers labelled "Sweep PDH ↑" / "Sweep EQH ↓" etc. | At least 1 sweep event on a 200-bar window (if any have fired) |

5. **Verify toggles work**:
   - Click each new toggle in `ChartControls.tsx` — the corresponding layer should appear/disappear.
   - All toggles should be **independent** (turning off HTF projection does not affect liquidity levels).

6. **Verify no regressions**:
   - The existing v1 zones (FVG/OB on the LTF) still render.
   - The S/R zones still render.
   - The EMA lines still render.
   - The chart still updates on live SSE events.

**Pass criteria**: all 6 new layers render, all toggles work independently, no regressions on existing layers.

### Verify 7.4 — Performance

```bash
# In the browser, open the Network tab and reload the chart with symbol=BTCUSDT, timeframe=15m, limit=500
# Measure the time from "Reload" to "chart fully painted (all layers visible)"
```

**Pass criteria**: < 3 seconds end-to-end on a fast connection. The `/api/smc/engine` endpoint should be the dominant cost; if it's > 3s, the engine needs a performance fix (the 30s budget in Phase 4 is the upper bound; 3s is the user-facing target).

### Verify 7.5 — Cross-symbol consistency

For each of the 3 validation symbols (BTC, ETH, SOL):
1. Open the chart.
2. Verify the same layers render.
3. Verify the bias, liquidity levels, and sessions are different (per-symbol data).

**Pass criteria**: all 3 symbols render the same UI with different data. No symbol-specific rendering bugs.

## Final Deliverable

- `SMCZone`, `SMCSnapshot`, `SMCEngineResponse` interfaces in `client.ts`.
- `fetchSMCEngine` API client function.
- 6 new toggle buttons in `ChartControls.tsx`.
- 6 new rendering layers in `CandleChart.tsx`: HTF projection, liquidity levels, premium/discount band, session tinting, bias badge, sweep markers.
- Cross-symbol rendering verified on BTC, ETH, SOL.
- Performance verified < 3s end-to-end.
- No regressions on existing v1 layers.

## Phase Summary

After all 7 phases:

1. **Phase 0**: Data availability confirmed, v1 archived, environment prep.
2. **Phase 1**: Foundation modules (`mtf`, `swings`, `sessions`) — deterministic, no lookahead.
3. **Phase 2**: Structure + zones (`structure`, `fvgs`, `order_blocks`) — parity backtest passes, multi-slot with fill%/mitigation.
4. **Phase 3**: Liquidity, bias, premium/discount — the net-new modules closing the spec gaps.
5. **Phase 4**: Engine orchestrator — `run_smc_analysis` and `SMContext` in a single call.
6. **Phase 5**: Validators — the ship gate. Lookahead audit, IC tests, walk-forward, regime coverage.
7. **Phase 6**: Integration — `pre_process` wiring, `/api/smc/engine` endpoint, v1 archival.
8. **Phase 7**: Frontend — 6 new chart layers, all toggleable, cross-symbol tested.

The engine is now production-ready for use by live strategies and the frontend chart.

## Future Work (NOT in this 7-phase plan)

- **Persistence layer**: optional append-only `event_log` table for offline ML/IC research. Re-enables if you want to feed events into an ML model.
- **Backtesting with the engine**: the strategies consuming the engine need their own backtest integration (currently `BaseStrategy.pre_process` is the integration point; backtesting requires running `generate_signals` on historical data and computing PnL).
- **LLM context integration**: the LLM context builder at `backend/app/core/llm_context_builder.py:71-124` should be updated to consume the new `smc_*` columns instead of the v1 FVG/OB columns.
- **Session background tinting (proper)**: the Phase 7 simplification uses vertical lines; a full implementation with a custom `ISeriesPrimitive` would render full horizontal background bands.
- **Multi-symbol engine**: running the engine on a basket of symbols (e.g., for relative-strength analysis) requires a new orchestration layer.
