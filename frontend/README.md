# TBot frontend

The frontend is a Vite + React + TypeScript dashboard for operating and inspecting the TBot backend. It does not calculate strategies, call LLM providers, or send Telegram messages itself; it presents the backend's REST and Server-Sent Event (SSE) interfaces.

## Pages

| Route | Purpose |
| --- | --- |
| `/` | Import data from Binance/CSV and inspect stored datasets |
| `/signal-feed` | Start or stop analysis sessions; view watching, confirmed, rejected, and outcome states |
| `/charts` | Candlestick chart with indicator, S/R, pivot, psych-level, and legacy-SMC overlays |
| `/backtest` | Configure a server-side backtest and inspect persisted runs/trades/equity data |
| `/backtest-analyser` | Compare JSON backtest artifacts dropped into the browser |
| `/llm-prompts` | Browse persisted LLM prompt/response logs |
| `/price-alerts` | Create, view, and cancel independent price alerts |

## Development

```bash
npm install
npm run dev
```

The API base URL is set through `VITE_API_BASE_URL`; if it is unset, the client uses `http://localhost:5001/api`.

Other scripts:

```bash
npm run build
npm run lint
```

## Integration boundaries

- `src/lib/api.ts` is the REST client and the first place to update when a backend endpoint changes.
- `src/hooks/useSSE.ts` owns the EventSource connection for the live signal feed.
- `src/pages/Charts/` and `src/components/Chart/` render market-data views; pricing/indicator calculation remains in the backend.
- `src/pages/Backtest.tsx` operates the persisted backend backtester. `BacktestAnalyzer.tsx` is a local browser-side reader for saved JSON outputs.

For the current end-to-end model, see [the repository architecture guide](../docs/architecture.md).
