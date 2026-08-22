# LLM confirmation and providers

The LLM is a bounded reviewer of a rule-generated candidate; it is not the continuous market scanner. Its work is performed asynchronously by the single-worker `LLMQueueManager` after a `WatchingSetup` is persisted.

## Decision contract

`LLMClient` requests JSON that validates against a Pydantic decision schema. The response contains a verdict (`CONFIRM`, `REJECT`, or `MODIFY`), reasoning, dimension scores, confidence, and optional modified stop/target levels. The prompt asks the model to consider trend, momentum, market structure, volume, price action, risk/reward, key levels, and counter-signals.

For `CONFIRM`/`MODIFY`, the result becomes a `ConfirmedSignal`; `MODIFY` replaces the proposed levels. For `REJECT`, it becomes a `RejectedSignal`. Prompt/response data and parsed verdict are persisted in `LLMPromptLog` and exposed through `/api/signals/llm_logs`.

## Context builder

`llm_context_builder.py` assembles candidate metadata/risk, indicators, volume, recent price action/classified candles, higher-timeframe context, and market data such as funding/open interest/session when available. It is a context-construction layer; the final decision is the provider's structured response filtered by the client schema/rules.

## Provider selection

| `LLM_PROVIDER` | Provider implementation | Configuration family |
| --- | --- | --- |
| `lm_studio` (default) | Local OpenAI-compatible chat endpoint | `LLM_BASE_URL`, `LLM_MODEL`, optional `LLM_API_KEY` |
| `vertex_ai` | Google Gen AI / Vertex AI client | `VERTEX_PROJECT_ID`, `VERTEX_LOCATION`, `VERTEX_MODEL`, generation controls, application credentials |
| `groq`, `openrouter`, `openai` | OpenAI-compatible cloud endpoint | API base/model/key/generation controls |

Common controls include `LLM_MAX_TOKENS`, `LLM_TIMEOUT`, and `LLM_TEMPERATURE`. Vertex additionally supports max tokens, temperature, and a thinking-level setting. Keep actual keys, project IDs, chat IDs, and local endpoints in local/deployment configuration rather than documentation.

The endpoint named `/api/signals/lm-studio-status` is retained for UI compatibility but delegates to the configured provider status mechanism, not only LM Studio.

## Queue behaviour

The queue builds a fresh decision context, retrieves finalized higher-timeframe history, and may retry provider calls. It serializes confirmation work through one worker and has pacing/retry delays, so a watching candidate can remain visible while evaluation is pending. Telegram delivery is a separate queue after a result is persisted.

When adjusting prompts, providers, parsing, or context fields, update LLM tests, the prompt-log UI expectations, [architecture](../architecture.md), and this guide.
