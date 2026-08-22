# SMC Engine v2.0 — Research-Grade Implementation

> **Future design, not a completed runtime engine (status reviewed 2026-08-22).** `backend/app/core/smc/` currently contains a parameter registry and unimplemented `SMContext`/`run_smc_analysis` public stubs. Current charts use legacy `app/strategies/archive/smc_v1/` through `/api/sr-zones/smc-zones`.

## Overview

A multi-timeframe Smart Money Concepts (SMC) engine replacing the current fragmented SMC code (`market_structure.py`, `events.py`, `fractals.py`) with a single, audit-passing module that:

- **Covers the full ICT/SMC vocabulary**: internal & swing structure (BOS, CHoCH, MSS), institutional Order Blocks with mitigation status, Fair Value Gaps with fill %, Liquidity pools (PDH/PDL/PWH/PWL/Equal Highs-Lows/Buy-Sell-Side), Bias Engine (Weekly + Daily with confirmation), Premium/Discount 50% filter, Sessions + Kill Zones, and Multi-TF context.
- **Runs on 15m with HTF stack = 1H + 4H + 1D**, validated on **BTC + ETH + SOL** with **≥ 2 years of data** (per the locked-in configuration).
- **Is stateless on-the-fly**: no DB persistence, recomputed on each request (matches the existing `/smc-zones` pattern). Optional append-only event log for ML/IC research is a *future* capability, not in scope here.
- **Has zero look-ahead bias** by construction: swing points emit `confirmed_at` indices; HTF reads use only **closed** HTF candles; the `validators.py` module enforces this on every ship gate.
- **Adheres to quant validation discipline**: each SMC "signal" must individually clear IC > 0.02, t-stat > 2, sample > 30 before being combined with anything (per `references/patterns.md` and `sharp_edges.md#overfitting-certainty`).

## Locked-in Configuration

| Decision | Value | Source |
|---|---|---|
| Persistence | Stateless on-the-fly (no DB writes) | User choice |
| Operating TF | 15m LTF, HTF stack = 1H + 4H + 1D | User choice |
| Validation universe | BTC + ETH + SOL (CEX perp fees ~10 bps taker) | User choice |
| Min data per symbol | 2 years of 15m candles (~70k rows/symbol) | Walk-forward needs ≥ 50 trades per test fold |
| Cost model (per round-trip) | 24 bps (8 commission + 6 spread + ~10 impact) | sharp_edges `transaction-cost-fantasy` |
| Max free numeric parameters (whole engine) | 5 | sharp_edges `curve-fitting-excuses` Rule of 5 |
| Backtest Sharpe rejection bar | Sharpe > 3.0 is auto-rejected unless look-ahead audit clears | sharp_edges `overfitting-certainty` |
| Multiple-testing correction | Benjamini-Hochberg at α=0.05 if > 5 hypotheses | sharp_edges `multiple-testing-trap` |

## Architecture

```
backend/app/core/smc/
  __init__.py            # public API: run_smc_analysis()
  mtf.py                 # CRITICAL: closed-candle-only HTF alignment
  swings.py              # internal vs swing pivots, HH/HL/LH/LL labelling
  sessions.py            # Asian/London/NY session stamping + kill-zone windows
  structure.py           # internal BOS, swing BOS, CHoCH, MSS
  fvgs.py                # multi-slot FVG with fill % tracking
  order_blocks.py        # multi-slot OB ledger with mitigation status
  liquidity.py           # PDH/PDL/PWH/PWL/Asian H/L/EH/EL/buy-side/sell-side + sweeps
  bias.py                # weekly + daily bias with confirmation gate
  premium_discount.py    # 50% equilibrium, premium/discount bands
  context.py             # SMContext frozen dataclass — per-bar snapshot
  engine.py              # orchestrator: run_smc_analysis(df, htf_data) -> enriched df
  validators.py          # lookahead audit, sample-size guards, IC tests
```

`market_regime.py` is **kept as-is** (live strategies depend on it). The new SMC bias engine **adds columns** (`smc_weekly_bias`, `smc_daily_bias`) alongside the existing `regime` column; it does not replace it.

The current `market_structure.py`, `events.py`, `fractals.py` will be **archived** to `backend/app/strategies/archive/smc_v1/` at the start of Phase 2 after parity checks. Their core FVG/OB extractors will be reused (and improved) inside the new package.

## Phase Index

| # | File | Modules | Description |
|---|---|---|---|
| 0 | [Phase 0: Pre-flight](./phase-0-preflight.md) | — | Data availability, archive setup, environment, prereqs |
| 1 | [Phase 1: Foundation](./phase-1-foundation.md) | `mtf.py`, `swings.py`, `sessions.py` | Deterministic, no-lookahead building blocks |
| 2 | [Phase 2: Structure + Zones](./phase-2-structure-zones.md) | `structure.py`, `fvgs.py`, `order_blocks.py` | Replaces both v1 BoS/CHoCH engines; multi-slot FVGs/OBs |
| 3 | [Phase 3: Liquidity + Bias + PD](./phase-3-liquidity-bias-pd.md) | `liquidity.py`, `bias.py`, `premium_discount.py` | The net-new modules that close the spec gaps |
| 4 | [Phase 4: Engine Orchestrator](./phase-4-engine-orchestrator.md) | `context.py`, `engine.py` | Public API `run_smc_analysis()` + per-bar snapshot |
| 5 | [Phase 5: Validators (Ship Gate)](./phase-5-validators.md) | `validators.py` | Lookahead audit, IC tests, walk-forward, regime coverage |
| 6 | [Phase 6: Integration](./phase-6-integration.md) | — | `pre_process` wiring, new `/api/smc/engine` endpoint, v1 archival |
| 7 | [Phase 7: Frontend](./phase-7-frontend.md) | — | `SMCZone` interface extensions, new primitives, badge UI |

## Quant Principles (apply to every phase)

1. **Swing-point reads happen only at `confirmed_at` index** — never at the swing's own index. This is the bug that produces Sharpe 5 backtests.
2. **HTF reads use only candles that were closed before the LTF timestamp minus 1 ms**. A 4H candle that's still forming is *not* knowable. `iloc[-1]` is the trap.
3. **Bias engine decisions are gated by confirmation events** (a swing BOS in the bias direction inside a kill zone). Before confirmation → "tentative"; strategies should not enter on tentative bias.
4. **Each SMC "signal" must independently pass IC > 0.02 / t-stat > 2 / 30-sample minimum** before being combined with anything (per `references/patterns.md`).
5. **No silent parameters**. Every numeric knob is declared in one place (`_PARAM_REGISTRY` in each module) and counts against the 5-free-param budget. Sessions boundaries, equilibrium = 50%, BOS rule = body-close are **constants**, not tunable.
6. **The `validators.py` module is the ship gate** — phase 5 must clear before phase 6 (integration) begins.

## Cost Reality (applies to any backtest using this engine)

| Cost component | Estimate | Source |
|---|---|---|
| Commission (CEX perp taker) | 4-5 bps | Binance/Bybit fee schedule |
| Spread (limit-order entry at OB edge) | 4-8 bps | typical crypto perp at 15m |
| Market impact (1% of ADV) | 2-5 bps | Almgren-Chriss √(participation) |
| **Total per round-trip** | **~24 bps** | sum of all-in entry + exit |

Any backtest showing gross Sharpe > 1.5 on 15m is suspect. If the strategy's net Sharpe drops by > 50% after the 24 bps haircut, walk away (sharp_edges `transaction-cost-fantasy`).
