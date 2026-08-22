# Strategy engine

For current strategy inventory and conditions, start with [the strategy catalog](../strategy-catalog.md). This page records the engine boundary used by both live analysis and backtests.

## Runtime components

| Component | Responsibility |
| --- | --- |
| `BaseStrategy` | Metadata, common DataFrame preprocessing, safety helpers, and candidate/risk conventions |
| `StrategyRegistry` | Discovers direct modules in `app/strategies/`, instantiates them, and synchronises persisted settings |
| `StrategyRunner` | Runs a strategy on finalized live data or a historical DataFrame, then constructs `SetupSignal` for a live candidate |
| `WatchingManager` | Persists/de-duplicates candidate setups and expires them by closed-candle count |
| `LiveScanner` | Selects compatible registered strategies at each session candle close |

The active strategy interface is DataFrame-oriented: `generate_signals(df)` returns a signal series with direction/confidence information. The runner is responsible for converting the latest viable row into the `SetupSignal` sent into the watching/LLM workflow.

`BaseStrategy` also retains legacy `Candle`, `Indicators`, and `scan()` compatibility types. Those are relevant to archived implementations; do not infer that every archived class is a live registered strategy.

## Strategy result lifecycle

Regular built-ins create candidates on finalized candles and proceed through `WatchingSetup` → LLM verdict → confirmed/rejected record. `EMA Cross Alert` intentionally runs during live-candle updates and sends a direct Telegram alert instead. Any new strategy should make its intended lifecycle explicit before it is registered.

## Historical execution

The backtest engine asks the same runner for a full historical signal series, then controls entry/exit simulation. Read [Backtesting model](../backtesting.md) before changing a strategy's output or risk semantics.
