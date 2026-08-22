# Strategy catalog and contract

**Current live registry, reviewed 2026-08-22.** `StrategyRegistry` discovers Python modules directly in `backend/app/strategies/`; it does not auto-discover files below `backend/app/strategies/archive/`.

## Current built-in strategies

| Strategy | Version | Timeframe(s) | Candidate thesis | Runtime delivery |
| --- | ---: | --- | --- | --- |
| `Trend Following` | 3.2 | 1h | Regime-aligned EMA pullback/recovery with trend/exhaustion gates and soft confirmation | Watching → LLM → confirmed/rejected → outcome tracking |
| `Burner 9/20` | 4.0 | 1h | Fast EMA 9/20 momentum continuation after a pullback/recovery | Watching → LLM → confirmed/rejected → outcome tracking |
| `Breakout & Retest` | 3.1 | 4h | Recent structural break, retest of the level, and rejection confirmation | Watching → LLM → confirmed/rejected → outcome tracking |
| `Liquidity Sweep` | 3.1 | 4h | Wick sweep of a recent extreme followed by recovery, volume, and context checks | Watching → LLM → confirmed/rejected → outcome tracking |
| `Key Level Reversal` | 4.2 | 15m | Reversal at a repeatedly tested recent level using engulfing/RSI/volume/ADX evidence | Watching → LLM → confirmed/rejected → outcome tracking |
| `EMA Cross Alert` | — | 30m, 1h | Near/crossing EMA 9/20 condition evaluated while a candle is live | Direct Telegram alert; no WatchingSetup, LLM verdict, or outcome tracking |

The registry persists each built-in strategy's enabled/minimum-confidence preference in the `strategies` table. Session creation selects named strategies; the scanner executes selected strategies on matching timeframes.

## What each regular strategy consumes

All five candidate strategies run from closed-candle data through `StrategyRunner`. `BaseStrategy.pre_process()` establishes shared computed columns, including EMA 50/100/200, ADX, ATR, and market regime; feature requirements add EMA 9/21, RSI, MACD, bands, volume, or level context as needed.

| Strategy | Important hard conditions | Confidence/risk summary |
| --- | --- | --- |
| Trend Following | Trending directional regime; EMA 21 pullback/recovery; price positioned across EMA 50; no trend exhaustion | Five soft inputs including volume, RSI, candle/wick quality, and ADX; structural/ATR stop and structural or R-multiple targets |
| Burner 9/20 | Directional regime; sufficient EMA 9/20 spread; EMA 9 pullback recovery; no exhaustion | Momentum/price-action/volume/divergence/trap/EMA-200 soft inputs; structural or R-multiple targets |
| Breakout & Retest | Body breakout of 20-bar level, retest proximity, and rejection | Volume, RSI, wick, EMA-50 soft inputs; 10-bar/ATR stop and structural/R targets |
| Liquidity Sweep | Sweep/recovery of a 10-bar extreme; close-position and volume requirements | RSI, body, candle, and EMA-50 soft inputs; wick/ATR stop and past-extreme/R targets |
| Key Level Reversal | Price near a recent multi-hit high/low; strong engulfing and sufficient multi-factor score | RSI, relative volume, ADX decay, and closing direction form the score; current-extreme/ATR stop and past-range/R targets |

The output confidence is the strategy's algorithmic confidence. An LLM's decision/rationale is persisted separately; a `MODIFY` verdict can alter the stored signal levels.

## Strategy execution contract

### Main types

| Item | Location | Role |
| --- | --- | --- |
| `BaseStrategy` and `SetupSignal` | `backend/app/core/base_strategy.py` | Shared preprocessing, metadata, safety helpers, and candidate shape |
| `StrategyRegistry` | `backend/app/core/strategy_loader.py` | Module discovery, instances, DB synchronisation/configuration |
| `StrategyRunner` | `backend/app/core/strategy_runner.py` | Finalized-data preprocessing, live last-row detection, historical signal series |
| `WatchingManager` | `backend/app/core/watching_manager.py` | Candidate persistence, de-duplication, candle expiry |
| Built-ins | `backend/app/strategies/*.py` | Current live strategy rules |

The current DataFrame-oriented interface is `generate_signals(df)`: it returns signal/direction/confidence columns over the preprocessed series. The runner converts the latest viable live row into a `SetupSignal`; in a backtest it uses the historical series.

The base class retains older `Candle`, `Indicators`, and `scan()` compatibility types for archived/legacy code. New work should follow the active DataFrame-oriented contract used by the current built-ins unless the strategy-engine design changes deliberately.

### Candidate lifecycle contract

```text
closed candle → StrategyRunner → SetupSignal → WatchingSetup
                                            │
                                    should_confirm_with_llm?
                                      │                 │
                                      yes               no
                                      ▼                 ▼
                                LLM queue          strategy-specific handling
                                      │
                         CONFIRM / MODIFY / REJECT
```

The live scanner enqueues a candidate only when `should_confirm_with_llm()` is true. A strategy that belongs to a different lifecycle must make that separation obvious in its metadata and its documentation, as `EMA Cross Alert` does.

## Adding or changing a strategy

1. Add a module directly under `backend/app/strategies/`, not under `archive/`.
2. Subclass `BaseStrategy`; give it a unique `name`, description, version, `timeframes`, feature requirements, confidence policy, and clear live/backtest semantics.
3. Implement the active `generate_signals(df)` path and use finalized input for closed-candle strategies. Define risk levels consistently with the `SetupSignal` fields.
4. Decide whether it is a candidate-to-LLM strategy or intentionally has a distinct delivery lifecycle. Do not leave the intended state transition implicit.
5. Cover its detection and risk semantics in tests, run a controlled backtest, and update this catalog plus [backtesting guidance](backtesting.md).

## Archive and SMC status

The following historical strategy implementations are retained in `backend/app/strategies/archive/` and are not part of the automatic live registry: Bollinger Squeeze, the older EMA Crossover, Fibonacci Retracement, FVG Mitigation, MACD Momentum, Order Block Retest, RSI Reversal, SMC Liquidity Sweep, SMC Structure Shift, S/R Breakout, S/R Rejection, Trend Pullback Confluence, and Volume Climax.

`archive/smc_v1/` is different from ordinary archived strategies: its FVG/order-block/events/fractal helpers are still imported by the chart-only `/api/sr-zones/smc-zones` endpoint. The planned SMC v2 package has only a parameter registry and public API stubs at present. See [SMC v2 status](README.md#documentation-status-by-directory) before treating SMC planning material as a usable strategy dependency.
