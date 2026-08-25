# Signal quality and trader decision-support roadmap

> **Status: proposed implementation roadmap (2026-08-22).** This document defines planned work. It is not a statement that any capability below is live. The current system behaviour remains documented in [Architecture and runtime](architecture.md), [Strategy catalog](strategy-catalog.md), and [Backtesting model](backtesting.md).

## 1. Product decision

TBot remains a **manual-trading signal platform**. It identifies, explains, ranks, and tracks potential setups; the user decides whether and how to trade, then executes manually at their chosen venue.

### In scope

```text
point-in-time market data
  -> deterministic candidate detection
  -> evidence snapshot + constrained LLM review
  -> research-backed ranking and alerting
  -> user review / optional trade journal / outcome analysis
```

- Detect selective, explainable candidates from closed-candle data.
- Rank candidates by evidence measured in prior, comparable historical data.
- Make the reason, invalidation, and uncertainty of every candidate visible.
- Learn from all detected, reviewed, and optionally user-recorded trades.
- Improve the research and validation process before expanding strategy complexity.

### Explicit non-goals

- No exchange credentials, order submission, position management, or automated sizing.
- No claim that an indicator, S/R confluence, SMC pattern, or LLM verdict is predictive until it passes the research gate.
- No “black-box confidence” presented as a probability without calibration evidence.
- No automatic promotion of a strategy because one historical aggregate looks attractive.

## 2. Design principles

1. **Selective beats busy.** A valid outcome is `NO_TRADE`; alert volume is not a success metric.
2. **Evidence beats chart aesthetics.** Multiple correlated technical conditions are one hypothesis until independently validated.
3. **The timestamp is part of the data.** A signal is evaluated only with information available when its candle closed.
4. **Live, backtest, and analysis share semantics.** Entry timing, stop/target rules, cost assumptions, and candle finality must be explicit and versioned.
5. **The LLM is an advisory reviewer.** Deterministic rules own candidate eligibility and risk validity.
6. **Uncertainty is a first-class output.** Small samples, unstable regimes, stale data, and missing inputs reduce or suppress a rank.
7. **Every decision is reproducible.** Persist the strategy version, inputs, rule results, cost model, LLM result, and analysis time.

## 3. Target signal lifecycle

```text
closed candle + data-quality checks
  -> strategy hard gate
  -> immutable candidate snapshot and reason codes
  -> deterministic risk/level validation
  -> optional LLM review within hard bounds
  -> calibrated ranking / alert eligibility
  -> user review and manual execution
  -> outcome + optional user journal
  -> periodic research and calibration refresh
```

The lifecycle deliberately stops before exchange execution. It should answer: *What was known? Why is this candidate here? How similar historical candidates performed after costs? What would invalidate it?*

## 4. Evidence model for a candidate

TBot already persists candidate cards, their setup data, and LLM responses. Phase B extends that existing record into a complete, versioned `EvidenceSnapshot` rather than introducing duplicate basic storage. The snapshot remains immutable once persisted; refreshed live context must be recorded as a new observation rather than overwriting the detection-time facts.

### Required contents

| Group | Minimum fields |
| --- | --- |
| Identity | candidate ID, symbol, timeframe, strategy name/version, candle close time, detection time, data version |
| Market state | close, ATR, realised volatility, current regime, higher-timeframe trend/context, data freshness/gap status |
| Rule evidence | every hard-gate result, additive rule contribution, failing/unknown conditions, reason codes |
| Levels | proposed entry, stop, targets, distance to stop/target in ATR and R, structural invalidation level |
| Context | relevant S/R or pivot zones and their provenance; indicators actually used by the strategy |
| Research evidence | current evaluation version, comparable historical sample size, out-of-sample net expectancy, calibration bucket, regime coverage status |
| Review | LLM verdict/reasoning/version/latency when used; deterministic post-review validation result |

### Candidate-display contract

The dashboard and Telegram format must show, at minimum:

- Direction, strategy, timeframe, detection age, and an explicit freshness/expiry state.
- Entry, stop, targets, R:R, and what price action invalidates the thesis.
- Three to five concise deterministic reasons the setup qualified.
- Counter-signals or missing evidence, not only bullish/bearish confirmation.
- Comparable-sample size and whether performance is out-of-sample, provisional, or unavailable.
- A link to the immutable snapshot and the backtest/evaluation version that produced the rank.

Do **not** label a score as “high probability” unless calibration proves that candidates in that score bucket achieved the stated frequency on an untouched out-of-sample sample.

## 5. Research gate: admit evidence, not stories

Every strategy change, new feature, and score change must be recorded as an experiment before it can influence live ranking. The existing backtest engine remains useful, but it must be extended from a simulator into a reproducible validation gate.

### Experiment manifest

Persist or version-control an immutable manifest for each run:

```yaml
experiment_id: "trend-following-v3-2-regime-filter-2026-08-22"
hypothesis: "A trend filter improves net 1h pullback expectancy during directional regimes."
strategy_version: "3.2+<commit>"
universe: [BTCUSDT, ETHUSDT, SOLUSDT]
timeframes: [1h]
development_window: "..."
holdout_window: "..." # untouched until the decision
walk_forward: {train_days: 180, test_days: 30, step_days: 7}
cost_model_version: "crypto-perp-v1"
parameter_manifest: { ... }
all_hypotheses_tested: [ ... ]
```

The actual implementation format may be a database model, JSON, or YAML, but it must be immutable once the evaluation is run.

### Required checks

| Check | Required result before live ranking |
| --- | --- |
| Data integrity | No duplicate keys; detected gaps, stale bars, zero/invalid prices, and extreme returns are reported or excluded with an audit trail. |
| Time integrity | Only finalized data; live scan and backtest use an as-of boundary; higher timeframes use only prior closed candles. |
| In-sample / holdout separation | Parameters are selected without reading the final holdout. |
| Walk-forward | Rolling out-of-sample results are reported by fold, including trade count and worst fold. |
| Costs | Fees, spread/slippage, funding, and a conservative impact assumption are explicit and versioned. |
| Regimes | Results are segmented by trend/range and volatility state, with no hidden aggregate-only promotion. |
| Sensitivity | Material numeric parameters are stable over a reasonable neighbourhood; unexplained knobs are removed. |
| Multiple testing | All attempted variants are logged; apply a false-discovery correction when testing many hypotheses. |
| Capacity/liquidity | Candidate eligibility states the liquidity/participation assumptions behind the result. |

### Initial ship-gate policy

For the first implementation, the gate should produce `PASS`, `PROVISIONAL`, or `REJECT` rather than hard-code one universal Sharpe cutoff.

- `PASS`: clean time/data audit, sufficient out-of-sample sample, positive net expectancy after costs, credible walk-forward stability, and no unacceptable regime failure.
- `PROVISIONAL`: insufficient observations or incomplete coverage. It may be displayed for research, but is not eligible for “top-ranked” alerts.
- `REJECT`: data/time-integrity failure, negative net result after costs, severe parameter sensitivity, or an unaddressed material risk.

The report must retain sample sizes, fold results, and cost assumptions. A high in-sample Sharpe, a visually compelling chart, or a successful LLM explanation cannot override a failed gate.

## 6. Simulator fidelity improvements

The current next-candle-open entry rule is a sound foundation. Extend it without changing its semantics silently.

### Cost model v1

For each completed simulated trade, separately record:

- Entry and exit fee assumptions (maker/taker mode where specified).
- Spread/slippage assumption for entry and exit.
- Funding accrued over the holding period for perpetual futures.
- Liquidity/impact proxy based on volatility and trade participation, where volume data supports it.
- Total cost in quote currency, basis points, and R.

Costs must be configurable by symbol/timeframe and evaluated pessimistically as well as at the base assumption. Results should show gross and net values side by side.

### Intrabar ambiguity

When one OHLC bar reaches both a stop and target, the existing deterministic stop-first rule is conservative but not necessarily representative of tradable path order. Preserve it as the default baseline and add two diagnostic scenarios:

1. pessimistic stop-first;
2. lower-timeframe replay when verified finer data is available.

Never promote a strategy based only on the optimistic path. Label runs with their intrabar policy so results are comparable.

### Data-quality and universe checks

Implement an auditable preflight report for every run: timeframe continuity, closed-candle status, duplicate/open-time conflicts, price/volume validity, import source, and coverage by symbol. Where a multi-asset universe is introduced, explicitly record delisted or unavailable assets to prevent survivor-only conclusions.

## 7. Ranking and calibration

The live strategy confidence remains an explainable rule score. Ranking is a separate service that estimates how candidates with comparable evidence have performed historically.

### Ranking inputs

1. Strategy version and deterministic rule score.
2. Symbol/timeframe and comparable-market-regime cohort.
3. Distance to stop/target, expected holding horizon, and costs.
4. Out-of-sample net expectancy and TP-before-stop frequency from the cohort.
5. Sample size, stability across walk-forward folds, and data freshness.
6. Counter-signals, unresolved gaps, expired context, or failed risk checks.

### Output contract

```text
rank_status: eligible | provisional | suppressed
evidence_grade: A | B | C | insufficient_data
net_expectancy_r: numeric or unavailable
calibrated_outcome_rate: numeric or unavailable
comparable_sample_size: integer
uncertainty_reason_codes: [...]
```

No outcome rate is shown when the comparable out-of-sample sample is too small. In that case the platform should say “insufficient comparable evidence”, not manufacture precision.

### Calibration report

For each strategy/version, generate a periodic table by score bucket, symbol, timeframe, and regime:

| Bucket | Candidates | TP-before-stop rate | Mean net R | Median net R | Max drawdown contribution | OOS only? |
| --- | ---: | ---: | ---: | ---: | ---: | --- |

The system is calibrated only if higher score buckets reliably outperform lower ones on later unseen data. If this relationship fails, downgrade or suppress the rank even if a strategy’s aggregate backtest is positive.

## 8. LLM role and deterministic guardrails

The LLM may review a persisted candidate and articulate supporting/counter evidence. It must not create a trade from scratch, bypass a failed hard gate, or make an unconstrained risk change.

### Required post-review validator

After `CONFIRM` or `MODIFY`, validate deterministically:

- direction is unchanged unless the candidate is rejected;
- entry, stop, and targets are finite, ordered correctly for the direction, and use current/explicit reference prices;
- stop distance and target distances fall within strategy-defined ATR/R bounds;
- minimum R:R remains valid after all modifications;
- candidate is still within its candle/clock TTL and market data is fresh;
- no data-gap, stale-context, or suppressed-rank condition exists;
- the exact input snapshot, provider/model ID, response, parsing result, and validator result are persisted.

An invalid modification becomes `REJECTED_BY_RISK_GUARD`, not a confirmed signal. Compare rules-only, LLM-confirmed, LLM-rejected, and LLM-modified cohorts on later out-of-sample data before claiming the LLM improves selection.

## 9. Manual-review journal and outcome attribution

Outcome tracking should distinguish the platform’s hypothetical candidate outcome from the user’s optional manually recorded trade result.

### User-review record

Add an optional review/journal record linked to a candidate:

| Field | Purpose |
| --- | --- |
| `review_decision` | taken, skipped, watched, invalidated, or other explicit neutral state |
| `reviewed_at` and note | records discretionary reason without asserting a model fact |
| Optional manual trade fields | entry/exit time and price, side, size label, fees, realised P&L/R |
| Adjustment reasons | late entry, altered stop, early exit, exchange/market condition, other |
| Candidate reference | immutable signal snapshot ID and strategy/evaluation version |

### Reporting questions

- Did user-taken candidates outperform the full eligible set?
- Which skip reasons protected capital, and which discarded positive expectancy?
- Does the LLM improve outcomes relative to deterministic eligibility alone?
- Which strategy/version/regime combinations are contributing net R after costs?
- Are alerts timely enough for the documented holding horizon?

Journal data is decision-support feedback, not a reason to mutate historical candidate evidence.

## 10. Alerting and operational safeguards

### Alert policy

- Notify only `eligible` candidates by default; `provisional` candidates remain visible in the dashboard/research view.
- Deduplicate semantically equivalent candidates and show a refresh/changed-evidence event rather than repeated alerts.
- Include expiration time and suppress delivery after TTL expiry or a data-freshness failure.
- Prefer a short alert plus a dashboard link to the full evidence snapshot.

### Runtime safeguards

- Monitor candle freshness, WebSocket health, REST backfill failures, queue latency, data gaps, and LLM latency.
- Surface a degraded-data state prominently; fail closed by suppressing rather than ranking stale candidates.
- Revalidate a candidate immediately before a delayed LLM-confirmed delivery.
- Version strategy code, feature definitions, scoring rules, cost model, and prompts in every persisted result.

## 11. Delivery plan

Work in this order. Each phase is independently useful and must preserve the existing manual-only boundary.

### Phase A — Baseline and experiment provenance

**Goal:** make existing backtests comparable and auditable.

**Implementation status (engine 4.0.0):** causal execution/data preflight, warm-up isolation, fail-closed strategy execution, engine/strategy/policy metadata, and a candle-value fingerprint are implemented. Walk-forward/OOS schemas, per-regime breakdowns, uncertainty intervals, and explicit cost components remain to be built before Phase A is complete.

- Add run/strategy/parameter/data/cost-model version metadata.
- Add data-quality preflight output and experiment-manifest persistence.
- Add out-of-sample and walk-forward result schema, including per-fold trade count.
- Add regime and strategy/symbol/timeframe breakdowns to backtest reports.

**Acceptance criteria:** two reruns with identical inputs produce identical result metadata; every report identifies its data coverage, cost model, strategy version, sample size, and OOS boundaries.

### Phase B — Complete immutable candidate evidence

**Goal:** make a live alert reproducible and reviewable.

- Audit and extend the existing persisted candidate/setup/LLM records with a versioned `EvidenceSnapshot` and reason-code schema; do not duplicate records that already exist.
- Persist any missing hard gates, additive score components, used indicators, level provenance, data-health state, and evaluation version alongside the existing setup and LLM response.
- Expose the complete evidence detail through the signal API, dashboard, and Telegram link/copy.

**Acceptance criteria:** a stored candidate can be rendered after a restart without recomputing present-day indicators; the UI clearly distinguishes detection-time evidence from live price.

### Phase C — Cost and simulation realism

**Goal:** report net, not fantasy, performance.

- Implement versioned fee, spread/slippage, funding, and conservative impact components.
- Record gross/net metrics and cost contribution per trade.
- Add intrabar-policy labelling and lower-timeframe replay where data exists.

**Acceptance criteria:** backtest exports show every cost component and cannot compare incompatible cost or intrabar policies without an explicit warning.

### Phase D — Calibration and ranking

**Goal:** promote the most evidence-supported candidates, not merely the highest raw rule score.

- Build periodic evaluation cohorts and score-bucket calibration reports.
- Introduce `eligible`, `provisional`, and `suppressed` rank states.
- Use calibrated net expectancy and uncertainty penalties to order alertable candidates.

**Acceptance criteria:** all alert ranks link to an evaluation version and comparable OOS cohort; insufficient evidence cannot appear as a precise probability or top-tier rank.

### Phase E — LLM guardrails and evaluation

**Goal:** retain explanation value without granting the LLM trading authority.

- Implement deterministic post-LLM risk/TTL/data validators.
- Add `REJECTED_BY_RISK_GUARD` state and full audit records.
- Produce rules-only versus LLM cohort reports.

**Acceptance criteria:** malformed, stale, or risk-invalid LLM decisions never create confirmed signals; LLM usefulness is measured on a later held-out period.

### Phase F — Manual-review journal

**Goal:** learn from the user’s discretionary process while keeping it optional.

- Add decision/journal API and UI.
- Link manual outcomes to candidate snapshots without overwriting hypothetical results.
- Add taken-versus-skipped and adjustment-reason reports.

**Acceptance criteria:** a user can record a review in under a minute; reports can separate system signal quality from manual execution variation.

## 12. Suggested implementation boundaries

The final file layout should be chosen during implementation, but ownership should remain clear:

| Area | Likely owner |
| --- | --- |
| Backtest semantics, cost model, experiment runs | `backend/app/core/backtest_engine.py`, backtest blueprint, persistence models |
| Data audit and finalized/as-of boundaries | `backend/app/utils/data_utils.py`, data ingestion utilities, tests |
| Candidate evidence and risk guard | `base_strategy.py`, `strategy_runner.py`, watching/LLM managers, persistence models |
| Calibration/evaluation | new focused research/evaluation service; persisted evaluation version/results |
| User review journal | signals or a dedicated journal blueprint, models, React Signal Feed/detail views |
| Alert suppression/freshness | scanner, queue managers, Telegram delivery, SSE events |

Update [Architecture and runtime](architecture.md), [Backtesting model](backtesting.md), [Live analysis](logic/live_analysis.md), and [API reference](logic/api_endpoints.md) in the same change that introduces any live behaviour or payload.

## 13. Deferred work

The planned SMC v2 engine, additional feeds, and more complex models are deferred until the research gate is operating. Any new feature begins as a hypothesis and must earn inclusion through the same validation process. Complexity does not substitute for evidence.

## 14. Definition of success

TBot succeeds when it gives the manual trader fewer, clearer, more reproducible candidates; honestly communicates uncertainty; and steadily demonstrates whether each strategy, filter, LLM review, and discretionary choice improves **out-of-sample net outcomes after costs**.
