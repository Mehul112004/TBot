# Pivot Points Engine Logic

The Pivot Points engine lives in `app/core/pivot_engine.py` and computes **forecast** support/resistance levels from the previous completed period's candle data. Unlike the swing-based S/R engine (which finds *observed* historical zones), pivots are *calculated* levels that reset every period.

> **Why pivots?** Pivot points produce a small, fixed, clean set of horizontal levels that the market tends to respect due to self-fulfilling confluence. They complement — not replace — the swing S/R bands. The chart shows both as independent toggleable layers.

---

## Core Concept

All pivot variants take the **previous completed period's** High (H), Low (L), and Close (C) — typically the previous UTC day's 1D candle — and project a set of horizontal levels across the *current* period. The levels don't move until the next period closes.

```
Previous period: H, L, C  (e.g. yesterday's 1D candle)
                    │
                    ▼
            Pivot formula
                    │
                    ▼
Current period: P, S1–S3, R1–R3 (Standard)
              or P, H1–H4, L1–L4 (Camarilla)
```

The "previous completed" candle is the **second most-recent** 1D (or 1W) candle in the DB — the most recent is still forming. See `_fetch_prev_completed_candle()`.

---

## Variants

### Standard / Floor-Trader Pivots (7 levels)

The baseline, most widely watched variant. Symmetric around the pivot point P.

```
P  = (H + L + C) / 3
R1 = (P × 2) − L
S1 = (P × 2) − H
R2 = P + (H − L)
S2 = P − (H − L)
R3 = H + 2 × (P − L)
S3 = L − 2 × (H − P)
```

| Label | Meaning | Side |
|---|---|---|
| **P** | Pivot point — the daily bias line. Above P = bullish intraday bias, below = bearish. | Center |
| **R1, R2, R3** | Projected resistance levels, escalating distance above P | Above |
| **S1, S2, S3** | Projected support levels, escalating distance below P | Below |

### Camarilla Pivots (9 levels) — **default variant**

Designed so that H3/L3 are the **expected intraday reversal zone** and H4/L4 are the **breakout / stop level**. Better for crypto intraday than Standard because it gives actionable trade rules. The Standard P is included as the daily bias line.

```
Range = H − L

H4 = C + Range × 1.1 / 2     (= C + 0.55 × Range)
H3 = C + Range × 1.1 / 4     (= C + 0.275 × Range)
H2 = C + Range × 1.1 / 6     (= C + 0.1833 × Range)
H1 = C + Range × 1.1 / 12    (= C + 0.0917 × Range)

P  = (H + L + C) / 3           (Standard pivot, included)

L1 = C − Range × 1.1 / 12
L2 = C − Range × 1.1 / 6
L3 = C − Range × 1.1 / 4
L4 = C − Range × 1.1 / 2
```

| Label | Meaning | Trading logic |
|---|---|---|
| **H4** | Upper breakout / stop level | If price closes above H4 → strong uptrend day; longs use H4 as stop |
| **H3** | Upper **reversal zone** | Price typically reverses down from here → **fade/short**, stop above H4 |
| **H2** | Inner resistance | Minor pullback level |
| **H1** | Inner resistance | Minor pullback level |
| **P** | Daily pivot — bias line | Above P = bullish bias, below = bearish |
| **L1** | Inner support | Minor bounce level |
| **L2** | Inner support | Minor bounce level |
| **L3** | Lower **reversal zone** | Price typically reverses up from here → **buy/long**, stop below L4 |
| **L4** | Lower breakout / stop level | If price closes below L4 → strong downtrend day; shorts use L4 as stop |

**The actionable Camarilla trade rules:**
- Price reaches **H3** → fade/short, stop above H4
- Price reaches **L3** → buy/long, stop below L4
- Price closes beyond **H4 or L4** → follow the breakout (trend day, don't fade)

### Fibonacci Pivots (NOT included)
Applies Fib ratios to the prior range around P. Produces 9 levels. Not implemented because the extra levels add clutter and Fib levels are more subjective / false-signal prone.

### Woodie Pivots (NOT included)
Weights the Open heavily. Not suitable for crypto because the "Open" is ambiguous in 24/7 markets.

### DeMark Pivots (NOT included)
Conditional on prior bar's Open vs Close. Only 3 levels — too sparse as a standalone overlay.

---

## How the Chart Uses Pivots

Pivots are a **separate toggleable layer** from the swing S/R bands:

| Layer | Render style | Toggle | Source |
|---|---|---|---|
| S/R Zones | Filled **bands** (rectangles) | "S/R Zones" (green) | Swing detection engine |
| Pivot Points | Thin **lines** | "Pivots" (purple) | `pivot_engine.py` |
| Psych Levels | Faint dotted lines | "Psych Levels" (amber) | Round-number sub-layer |
| SMC Zones | Lines + markers | "FVG / OB" (cyan) | `market_structure.py` |

**Why lines, not bands?** Pivots are exact *calculated* levels, not observed zones with a width. They render as thin dashed lines (P is solid; H/L levels are dashed) with axis labels showing `P`, `H3`, `L3`, etc.

**Confluence:** When a pivot line falls inside an S/R band, that band is flagged as confluence (brighter border + `*` marker). This marks high-probability zones where two independent methods agree.

---

## API

### `GET /api/sr-zones/pivots`

| Param | Default | Description |
|---|---|---|
| `symbol` | (required) | Trading pair |
| `variant` | `camarilla` | `camarilla` \| `standard` \| `all` |
| `period` | `1d` | `1d` (previous UTC day) \| `1w` (previous ISO week) |

**Response:**
```json
{
  "symbol": "BTCUSDT",
  "variant": "camarilla",
  "period": "1d",
  "source_open_time": "2026-06-25T00:00:00",
  "count": 9,
  "levels": [
    {"level": 61917.50, "label": "H4", "variant": "camarilla", "direction": "resistance", "period": "1d", "source_open_time": "..."},
    {"level": 60844.70, "label": "H3", ...},
    ...
    {"level": 57626.30, "label": "L4", "direction": "support", ...}
  ]
}
```

Levels are sorted high → low (resistance at top, support at bottom) for stable rendering.

### Variant `all`

Returns both Standard and Camarilla levels merged, with `P` deduplicated (Standard P == Camarilla P). Useful for maximum context, but adds clutter.

---

## Implementation Details

### `_fetch_prev_completed_candle(symbol, period)`
Fetches the 2 most recent candles for the symbol/period from the DB, ordered by `open_time DESC`. Returns the **second** one (the previous completed period). Falls back to the first (most recent) if only one exists.

### `compute_pivots(symbol, variant, period)`
1. Fetches prev completed candle's H/L/C.
2. Routes to `_standard_levels(h, l, c)` or `_camarilla_levels(h, l, c)`.
3. For `variant='all'`: merges both, dedupes by label (P appears once).
4. Sorts by price descending (resistance → pivot → support).
5. Returns list of level dicts with `level`, `label`, `variant`, `direction`, `period`, `source_open_time`.

### No persistence
Pivots are computed **on-the-fly per request** — not stored in the DB. They're cheap (one query + arithmetic) and reset every period, so persistence adds no value. The DB stores only swing-based S/R zones.

### Crypto-specific guidance
- Use **UTC midnight** as the reset boundary (avoids the "which session open?" ambiguity).
- Recompute daily; do **not** carry stale pivots across multiple days.
- Camarilla H3/L3 + H4/L4 give self-contained trade rules; Standard P gives the bias line.
- On dead range days, price may never reach H3/L3 (no trade). On volatility-spike days, price may blow through H4/L4 immediately (breakout, don't fade).