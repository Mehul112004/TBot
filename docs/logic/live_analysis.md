# Live analysis, candidates, and outcomes

`LiveScanner` manages current in-memory analysis sessions. Each session owns one symbol, its selected strategy/timeframe set, current live price, and a Binance stream. The scanner limits the process to ten active sessions and does not allow two active sessions for the same symbol.

## Closed-candle candidate path

```text
closed stream candle
  → candle upsert / gap top-up / indicator invalidation / S-R refresh
  → StrategyRunner on matching selected strategies
  → WatchingManager creates or refreshes WatchingSetup
  → SSE + Telegram watching notification
  → LLM queue (if the strategy requests confirmation)
  → ConfirmedSignal or RejectedSignal
```

`WatchingManager` de-duplicates candidates by session/strategy/symbol/timeframe and advances watching expiry on matching closed candles. The default configured expiry is three candles. A new watching card is persisted before the asynchronous LLM call, so its pre-confirmation state is visible in the Signal Feed.

## LLM result path

The single background LLM worker enriches a candidate with higher-timeframe/history and current Binance market data, builds a structured context, retries provider evaluation when appropriate, logs the exchange, and persists one result:

- `CONFIRM` → `ConfirmedSignal` with algorithm-proposed levels.
- `MODIFY` → `ConfirmedSignal` with LLM-provided levels.
- `REJECT` → `RejectedSignal` and rejected watching setup.

The result produces SSE and Telegram delivery work. Details are in [LLM providers](llm_providers.md).

## Live-price outcome path

Every stream price update also goes to `OutcomeTracker` and `PriceAlertTracker`. The outcome tracker checks active confirmed signals against target/stop/expiry conditions. It records the first terminal outcome, sends a reply-style Telegram notification, and publishes an SSE update. Price alerts are independent manually created above/below triggers.

## State after a restart

Session objects, streams, pending queues, and SSE subscriptions are process-memory state. Session records remain in the database but are not auto-resumed. Active confirmed signals and alerts are reloaded into tracker indexes at startup; restart the desired live sessions to resume scanning.

## Direct live-candle alerts

`EMA Cross Alert` is run periodically on live candles and uses an internal cooldown. It directly formats and queues a Telegram alert. It is intentionally outside the watching/LLM/confirmed-signal outcome state machine.
