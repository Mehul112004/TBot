# Backtesting model and research workflow

This document describes what the current engine simulates. It is deliberately separate from a claim about strategy quality: a saved backtest is a historical experiment defined by its data, configuration, and engine version.

## Where the engine lives

| Component | Location | Role |
| --- | --- | --- |
| API | `backend/app/blueprints/backtest_bp.py` | Validates requests, invokes the engine, persists/exports runs |
| Engine | `backend/app/core/backtest_engine.py` | Builds signal streams, simulates trades, calculates metrics |
| Historical strategy path | `backend/app/core/strategy_runner.py` | Runs a strategy over a preprocessed DataFrame |
| Persistence | `backend/app/models/db.py` | `BacktestRun` and `BacktestTrade` records |
| Interactive UI | `frontend/src/pages/Backtest.tsx` | Starts/reviews API-backed tests |
| File comparator | `frontend/src/pages/BacktestAnalyzer.tsx` | Browser-side comparison of dropped JSON result files |
| Batch research | `backend/scripts/run_comprehensive_backtest.py` | Synchronises data and writes dated JSON output bundles |

## Current execution semantics

1. A request identifies a stored symbol/timeframe/date range plus one or more discovered strategies, initial capital, risk percentage, and slippage in basis points.
2. The engine retrieves the local candle data and asks every selected strategy for its full historical signal series. Indicator/feature work is done once per strategy DataFrame rather than recomputed per candidate bar.
3. A detected signal enters at the **next candle's open**, not at the generating candle's close. Stops and targets retain their relative distance from the resulting entry price.
4. Position size is risk-based: current equity × risk percentage divided by per-unit price risk. Equity compounds between trades.
5. The simulator starts evaluating exits on the bar after entry. It checks bar high/low for stop, TP1, TP2, or end-of-data expiry. If a single bar reaches more than one level, the current deterministic priority is stop, then TP2, then TP1.
6. It applies configured slippage on both entry and exit notional. Its built-in cooldown is five bars after an entry. Trailing support exists in the engine but is not exposed by the standard REST form.
7. Runs persist their configuration, aggregate metrics, equity curve JSON, and individual trade records.

The standard REST endpoint accepts timeframes `5m`, `15m`, `30m`, `1h`, `4h`, and `1d`; it validates risk from 0.1–100% and slippage from 0–100 bps (default 10 bps). For exact request and export routes, see [API reference](logic/api_endpoints.md).

## Metrics currently stored/reported

The persisted `BacktestRun` includes total trades, wins/losses, win rate, total P&L and P&L %, profit factor, Sharpe/Sortino, maximum drawdown (absolute and %), average R/R, trade duration, best/worst trade, final equity, configuration, and equity curve. Each `BacktestTrade` retains the signal timing/direction, entry/exit, stops/targets, R/R, outcome, P&L, fees/slippage-related values, and duration.

Metric definitions are tied to this engine's discrete trade/output model. Compare only runs made with compatible data coverage, symbol/timeframe, strategy version, cost/risk settings, and result schema.

## Running a backtest

### Dashboard/API-backed run

Use the Backtest page after history is available. It builds `POST /api/backtest/run`, then reads `/api/backtest/history`, `/api/backtest/<run_id>`, or `/api/backtest/<run_id>/export` for review/export.

### Batch research run

From `backend/`:

```bash
python scripts/run_comprehensive_backtest.py --help
```

The script can sync required Binance data unless instructed otherwise, execute a selected universe/strategy/timeframe set, and write a full JSON file plus a `_brief.json` summary under a date-named `backtests/` folder. Inspect its help/configuration before running it so a comparison records the intended universe, dates, capital, risk, and slippage.

### Existing artifact convention

The repository's `backtests/YYYYMMDD/` directories are dated snapshots from earlier research. A full file contains the detailed runs; a matching `_brief.json` contains combined headline metrics and run count. They are useful provenance and inputs to the Backtest Analyser, not baseline constants or guarantees for a current strategy version.

## A repeatable strategy-research loop

Use one hypothesis and a fixed experiment manifest per change.

1. State the intended behaviour and which market regime/symbol/timeframe it addresses.
2. Specify immutable inputs: data source, symbol universe, timeframe, time period, initial capital, risk %, slippage, strategy version, and all exposed thresholds.
3. Keep the implementation change isolated. Add focused unit tests for the detection and invalidation/risk behaviour.
4. Run an in-sample development experiment only to establish that the hypothesis behaves as designed.
5. Evaluate the frozen version on a later unseen period or rolling walk-forward folds. Inspect results by regime, direction, asset, and time—not only one aggregate number.
6. Record the full configuration, sample boundaries, trade count, costs, and conclusion alongside the output. Preserve both the raw/full result and a concise comparison note.
7. Only after the validation decision, decide whether the change belongs in a live session. Update [the strategy catalog](strategy-catalog.md) and this document if execution semantics changed.

### Guardrails for interpreting results

- Do not rank versions by a single aggregate metric without checking sample size, drawdown, cost assumptions, concentration, and stability across market regimes.
- Do not tune repeatedly on the same final evaluation period; reserve an untouched segment for the decision.
- Keep all realistic costs in the manifest. The engine models configured slippage, but other market effects are a separate research assumption unless explicitly modeled.
- A high historical score is an observation about that sample, not evidence that a signal will perform similarly live.

These are documentation and research-practice guardrails, not a claim that the current engine already automates a full walk-forward or portfolio-validation framework.

## Changing the simulation

Any modification to signal timing, entry/exit price, intrabar conflict rule, sizing, fee/slippage model, cooldown, trailing logic, or metric calculation changes the meaning of future results. Treat it as an engine-version change:

1. Write the intended semantic difference in the change description.
2. Add a controlled test in `backend/tests/test_backtest_engine.py`.
3. Update this document and affected API/front-end descriptions.
4. Do not compare old artifact totals to new-engine totals without labelling the engine/configuration difference.
