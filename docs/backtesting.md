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

## Current execution semantics (engine 4.0.0)

1. A request identifies a stored symbol/timeframe/date range plus one or more discovered strategies, initial capital, risk percentage, and all-in execution cost in basis points per side.
2. The engine loads only database rows explicitly marked closed. A candle is also excluded unless `open_time + timeframe <= end_date`, so the requested end is an as-of boundary rather than permission to use an evolving bar.
3. Before the evaluation start it loads 200–500 warm-up candles according to the selected strategies. Warm-up observations initialize indicators/regime state but their signals and P&L are excluded. Missing warm-up history fails the run.
4. OHLCV is validated for finite/positive prices, valid high/low envelopes, non-negative volume, unique increasing timestamps, exact timeframe continuity, and closed status. A bad row or gap fails the run; it is not silently patched.
5. Every selected strategy must support the timeframe and complete successfully. A strategy exception fails the whole run. Live-only strategies and the current batch S/R feature path are rejected because they cannot yet produce a demonstrably prefix-causal history.
6. A detected signal enters at the **next candle's open**, not at the generating candle's close. Detection-time stops and targets remain fixed; a gap therefore changes available R:R. If the open has already crossed the stop or TP1, or reduces TP1 below 1R, the missed opportunity is skipped. Signal timestamps must match a candle exactly.
7. The entry candle is included in outcome evaluation. Stop/target gaps use the candle open; otherwise OHLC level hits use the configured level. When one candle reaches both stop and TP1, stop wins. TP1 is the normal first target because a continuous move must cross it before TP2; TP2 is terminal only when a candle opens beyond it.
8. The account permits one open position. If several strategies signal on the same bar, highest confidence wins with a deterministic strategy-name tie-break. Signals during the position are skipped, and five full cooldown bars begin after exit. This prevents a later trade from being sized with P&L that was unknown at its entry.
9. A position expires after eight bars while unfavorable or 24 bars while favorable, matching the platform's hybrid live-outcome horizon. End-of-sample also closes at the final candle close.
10. Position size is current realized equity × risk percentage divided by per-unit stop distance. Equity compounds using the same cent-rounded net P&L used by persistence and the equity curve. The configured all-in basis-point cost is charged on entry and exit notional.
11. Trailing-stop simulation is disabled. OHLC bars cannot determine whether the favorable extreme that moves the stop occurred before the adverse extreme that hits it.
12. Each run persists an engine/configuration manifest containing strategy versions, execution policies, warm-up/evaluation counts, cost/risk inputs, a SHA-256 fingerprint of the analyzed candle values, and counts for every simulation rejection reason (missing levels, missed fill, sub-1R fill, overlap/cooldown, or no next bar).

The standard REST endpoint accepts timeframes `5m`, `15m`, `30m`, `1h`, `4h`, and `1d`; it validates risk from 0.1–100% and slippage from 0–100 bps (default 10 bps). For exact request and export routes, see [API reference](logic/api_endpoints.md).

## Metrics currently stored/reported

The persisted `BacktestRun` includes total trades, net win rate, total P&L and P&L %, profit factor, Sharpe/Sortino, maximum drawdown (absolute and pointwise %), average profitable-trade net R, trade duration, best/worst trade, configuration manifest, and equity curve. Each `BacktestTrade` retains signal timing/direction, entry/exit, stops/targets, terminal label, after-cost P&L, net R, duration, and realized equity at entry.

`win_rate` counts trades with net P&L greater than zero—not target labels—because a nominal target touch can still be unprofitable after costs. `rr_ratio` is net P&L divided by the risk amount at entry. Sharpe and Sortino use calendar-daily realized-equity returns and a 365.25-day crypto annualization factor; sub-daily trade P&L is not incorrectly treated as daily returns. Sortino uses downside deviation across all daily observations. Drawdown percentage is measured against the running peak at each point.

Metric definitions are tied to this engine's discrete trade/output model. Compare only runs made with the same engine/policy version, compatible data fingerprint/coverage, symbol/timeframe, strategy version, and cost/risk settings.

## Reliability changes in 4.0.0

Engine 4.0.0 invalidates direct comparison with earlier backtest totals. It corrected these result-skewing behaviors:

- the entry candle was previously omitted from stop/target evaluation;
- a fully resolved future trade updated equity before later, overlapping entry timestamps were processed;
- unmatched signal timestamps were silently mapped to the closest candle;
- next-open gaps moved every structural stop/target by the gap amount, inventing levels that did not exist at detection time;
- the requested sample had no indicator warm-up and could include candles not final at the as-of boundary;
- historical strategy exceptions could be swallowed while the run was marked complete;
- centered Burner divergence and fractal events exposed pivots before their right-hand confirmation bars closed;
- TP2 was preferred when an OHLC bar also crossed TP1, even though the current live tracker treats the first reached major level as terminal;
- win rate and winner R used terminal labels/gross R instead of after-cost profitability;
- irregular per-trade results were annualized as if they formed a regular return series, and drawdown % used the wrong peak denominator.

Focused regression coverage lives in `backend/tests/test_backtest_engine.py`, `backend/tests/test_backtest_causality.py`, `backend/tests/test_extract_events.py`, and `backend/tests/test_strategy_runner.py`.

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
- Engine 4.0 makes a single historical simulation causal and reproducible; it does **not** by itself make an optimized strategy out-of-sample evidence.

These are documentation and research-practice guardrails, not a claim that the current engine already automates a full walk-forward or portfolio-validation framework.

## Remaining research limitations

- There is not yet an automated anchored/rolling walk-forward runner, untouched final holdout, multiple-testing correction, bootstrap confidence interval, or probability-of-backtest-overfitting report.
- The cost input is one all-in per-side basis-point assumption. It does not separately model maker/taker fees, spread, size-dependent impact, or perpetual funding.
- OHLC replay is deliberately conservative for same-bar stop/target conflicts but cannot reconstruct the true intrabar path. Lower-timeframe replay is still required for higher fidelity.
- The batch S/R feature pipeline still selects/scores zones using the full DataFrame. Historical strategies that require it fail closed until a per-prefix state machine replaces that implementation.
- One open position per symbol is modeled. This is not a multi-asset portfolio allocation or correlated-risk engine.
- In a combined-strategy run, simultaneous candidates are resolved by raw strategy confidence. Those gate fractions are not yet calibrated across strategies, so strategy-quality decisions should use one-strategy runs until the calibration phase replaces this tie-break with comparable estimates.

## Changing the simulation

Any modification to signal timing, entry/exit price, intrabar conflict rule, sizing, fee/slippage model, cooldown, trailing logic, or metric calculation changes the meaning of future results. Treat it as an engine-version change:

1. Write the intended semantic difference in the change description.
2. Add a controlled test in `backend/tests/test_backtest_engine.py`.
3. Update this document and affected API/front-end descriptions.
4. Do not compare old artifact totals to new-engine totals without labelling the engine/configuration difference.
