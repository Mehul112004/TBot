# S/R Zones & Pivot Points — A Visual Guide

This guide explains the four horizontal-level overlays on the TBot chart, what they mean, and how to read them together.

---

## The Four Layers (toggleable)

The chart has four independent horizontal-level layers, each with its own toggle button:

| Toggle | Color | What it shows | Style |
|---|---|---|---|
| **S/R Zones** | Green | Historical swing-based support/resistance **bands** | Filled rectangles |
| **Pivots** | Purple | Calculated pivot-point **lines** (Camarilla/Standard) | Thin dashed lines |
| **Psych Levels** | Amber | Psychological round-number levels | Faint dotted lines |
| **FVG / OB** | Cyan | Fair Value Gaps & Order Blocks (SMC theory) | Lines + markers |

All four can be on or off independently. **S/R Zones** and **Pivots** are the primary layers for most use cases.

---

## 1. S/R Zones (Green Bands)

### What they are
Support/Resistance **bands** drawn where price has historically reacted. They're not single lines — they're **zones** with a width (±0.25 × ATR), because price rarely bounces off an exact level.

### How they're detected
1. **Swing points** — price pivots found with a 12-candle lookback window on each side. These are real market structure highs/lows, not micro-noise.
2. **Round numbers** — psychological levels (Bitcoin $60k, $65k, etc.). Rendered faintly via their own "Psych Levels" toggle.
3.**Prev day/week H/L** — REMOVED from the S/R engine. This role is now filled by the Pivots layer (which does it better).

### How to read them
- **Green bands below price** = support (price tends to bounce up from here)
- **Red bands above price** = resistance (price tends to reverse down from here)
- **Orange bands** = both (zone that has acted as both support and resistance over time)
- **Darker / more saturated** band = higher strength (more touches, more recent tests)
- **Thicker border + `4H`/`1D` prefix** = the zone originated from a **higher timeframe** (stronger — institutional levels)
- **`*` marker** = **confluence** — this band's price range overlaps a higher-timeframe band. Two timeframes agreeing on the same price is a high-probability zone.

### Label format on the axis
```
S 64000 (3×)       ← support at $64000, tested 3 times
R 68000 (16×)      ← resistance at $68000, tested 16 times
4H R 72000* (8×)   ← 4h-timeframe resistance at $72000, 8 touches, confluence (*)
```

### The "Min Touches" control
The stepper (1–5) controls the minimum number of post-formation touches required for a zone to appear:
- **1** — almost every swing shows up (cluttered)
- **3** (default) — only zones tested ≥3 times appear (clean, ~6–8 zones)
- **5** — only heavily-tested zones appear (very sparse, major levels only)

**More touches = stronger zone.** A zone tested 16 times is far more reliable than one tested 2 times.

### Multi-Timeframe (MTF) behavior
When you view the `1h` chart, you also see zones from `4h` and `1d` (the next 2 timeframes up the ladder). This means:
- **1h zones** (thin border) — recent, intraday structure
- **4h zones** (thick border, `4H` prefix) — swing-trader levels
- **1d zones** (thick border, `1D` prefix) — institutional/macro levels

The strongest signals come from **confluence** zones — where a 1h band overlaps a 4h or 1d band (marked with `*`).

---

## 2. Pivot Points (Purple Lines)

### What they are
**Calculated** forecast levels projected from the previous completed day (or week). Unlike S/R bands (which are *observed* — price reacted there before), pivots are *mathematical* — derived from yesterday's High/Low/Close.

### The default variant: Camarilla (9 lines)
Camarilla levels are purpose-built for intraday trading. They divide today's expected price range into nested zones around yesterday's close:

```
                     H4  ←── breakout / stop level (above = strong uptrend day)
                     H3  ←── reversal zone (fade/short here, stop above H4)
                     H2  ←── minor resistance
                     H1  ←── minor resistance
                     P   ←── daily bias (above = bullish day, below = bearish)
                     L1  ←── minor support
                     L2  ←── minor support
                     L3  ←── reversal zone (buy/long here, stop below L4)
                     L4  ←── breakout / stop level (below = strong downtrend day)
```

### What each Camarilla label means

| Label | Role | Action |
|---|---|---|
| **P** | Daily pivot — the bias line | Above P → bullish intraday, below P → bearish |
| **H1, H2** | Inner resistance | Minor pullback levels; price may pause here |
| **H3** | **Reversal zone** (upper) | Price tends to reverse down from H3 → **short/fade**, stop above H4 |
| **H4** | **Breakout level** (upper) | If price closes above H4 → strong uptrend day; don't fade, follow the breakout |
| **L1, L2** | Inner support | Minor bounce levels |
| **L3** | **Reversal zone** (lower) | Price tends to bounce up from L3 → **long/buy**, stop below L4 |
| **L4** | **Breakout level** (lower) | If price closes below L4 → strong downtrend day; don't fade, follow the breakout |

### The Camarilla trade logic (the simple version)
1. **Normal day**: price stays within the H3–L3 range. Fade H3 (short), buy L3 (long). Stops at H4/L4.
2. **Trend day**: price breaks and closes beyond H4 or L4. Don't fade — follow the breakout in the breakout direction.
3. **Dead range day**: price never reaches H3 or L3. No trade.

### The Standard variant (7 lines)
The older, simpler variant. Also based on prev day's H/L/C:

| Label | Meaning |
|---|---|
| **P** | Pivot point — bias line (same as Camarilla P) |
| **R1, R2, R3** | Resistance levels above P, escalating distance |
| **S1, S2, S3** | Support levels below P, escalating distance |

Standard pivots are less actionable than Camarilla (no explicit reversal/breakout distinction) but are the most widely watched by retail, so they can become self-fulfilling.

### How pivots refresh
Pivots reset every UTC midnight (or weekly, if you switch the period selector). They use the **previous completed** day's candle (not the still-forming one). The `source_open_time` field in the API response shows which candle they were derived from.

### How pivots differ from S/R bands
| | S/R Zones | Pivots |
|---|---|---|
| **Source** | Observed historical price reactions | Calculated from prev day's H/L/C |
| **Nature** | Lagging (reaction to past action) | Leading (forecast for current period) |
| **Style** | Filled bands (price zones with width) | Thin lines (exact calculated levels) |
| **Lifespan** | Persist until invalidated | Reset every period |
| **Best for** | Finding where price has reacted before | Finding where price is *likely* to react today |
| **Confluence** | A pivot line inside an S/R band = high-probability zone | |

---

## 3. Psychological Levels (Amber — off by default)

### What they are
Faint horizontal lines at "round" psychological price levels where human traders cluster orders (e.g., Bitcoin at $60,000, $65,000, $70,000). These act as informal support/resistance purely because many people place orders at psychologically pleasing round numbers.

### Why faint and off by default
Psychological levels are a weak S/R signal — they're a "maybe" layer. Having them on all the time adds clutter. Turn them on when you want to see whether price is approaching a round number that might add confluence to an S/R band or pivot line.

### Grain sizing
- **BTCUSDT**: $5,000 increments (60k, 65k, 70k…)
- **ETHUSDT**: $500 increments (1500, 2000, 2500…)
- **SOLUSDT**: $50 increments (100, 150, 200…)
- **Any other symbol**: derived dynamically from the current price (~5% large grain), so a $204 coin gets $10-grain levels (190, 200, 210…) — not a fixed $500 grain that's bigger than its price.

Only the "large" grain is shown (sparse, ~6 levels nearest to price). The "small" grain exists in the engine but is excluded from the chart to avoid clutter.

---

## 4. FVG / OB (Cyan — SMC theory)

### What they are
**Fair Value Gaps (FVGs)**: 3-candle imbalances where price moved so fast it left a "gap" in the order book — price tends to return to fill these.  
**Order Blocks (OBs)**: the last bullish/bearish candle before a strong move — institutional order origin points.

### How they differ from S/R
FVGs/OBs are *structural* (created by institutional order flow and imbalance), while S/R bands are *historical* (price reacted there before) and pivots are *calculated*. They're a separate theory (Smart Money Concepts) that can add confluence when they overlap S/R or pivot levels.

### Note
The `/api/sr-zones/smc-zones` endpoint computes these on-the-fly from candle data. If candle data is stale (e.g. an imported symbol that's not live-streamed), it returns empty with a warning instead of crashing — so the rest of the chart still loads.

---

## Reading the Chart Together

The most powerful setup: **all four layers pointing at the same price.**

```
Example: BTC is at $60,000

  ┌─ R 64000 (1D)* (16×) ──┐  ← 1D S/R band (16 touches, confluence with 4h)
  │  ── H3 (Camarilla) ──  │  ← Pivot reversal zone at the same level
  │                        │  ← 60000 is also a psych level (round)
  │                        │  ← (possible FVG here too)
  └────────────────────────┘
            ↑
   This is a HIGH-PROBABILITY reversal zone.
   Multiple independent methods agree: historical S/R,
   calculated pivots, round number, SMC structure.
```

When you see a **confluence `*`** on an S/R band that aligns with a pivot line near a round number, that's the strongest signal the system can offer.

### Practical workflow
1. Start with **S/R Zones + Pivots** on (the default).
2. Check the **Min Touches** stepper — 3 is the sweet spot for most views.
3. Look for **confluence `*`** bands — those are the day's key levels.
4. Compare S/R bands against pivot lines — if an H3 pivot sits inside a resistance band, that's where price is likely to reverse.
5. Turn on **Psych Levels** if you want to see whether a round number is nearby.
6. Turn on **FVG/OB** for the full SMC picture (but it's the noisiest layer).

---

## Quick Reference: Label Cheat Sheet

| Label | Layer | Meaning |
|---|---|---|
| `S 64000 (3×)` | S/R | Support band at $64k, tested 3 times |
| `R 68000 (16×)` | S/R | Resistance band at $68k, tested 16 times |
| `4H R 72000* (8×)` | S/R (MTF) | 4h-timeframe resistance, 8 touches, confluence (*) |
| `P` | Pivot | Daily pivot point — bullish above, bearish below |
| `H3` | Pivot (Camarilla) | Upper reversal zone — fade/short here, stop above H4 |
| `L3` | Pivot (Camarilla) | Lower reversal zone — buy/long here, stop below L4 |
| `H4` / `L4` | Pivot (Camarilla) | Breakout / stop levels — closing beyond = trend day |
| `R1, R2, R3` | Pivot (Standard) | Resistance levels, escalating from R1 |
| `S1, S2, S3` | Pivot (Standard) | Support levels, escalating from S1 |
| Faint dotted line | Psych | Round psychological number (e.g., 60k, 65k) |