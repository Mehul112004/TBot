# Walk-forward signal validation — detailed implementation plan

> **Status: walk-forward validation v1 implemented on 2026-08-25.**
>
> This plan extends the causal backtest engine documented in [Backtesting model](backtesting.md). Its purpose is to determine whether a signal strategy generalizes to later unseen data and whether it is strong enough to influence live signal ranking. It does not add exchange execution or convert TBot into an automated trading bot.

## Implementation status — v1

The implemented v1 is deliberately narrow: one frozen historical strategy, symbol, and timeframe per sealed manifest. It provides an anchored chronological fold plan, non-overlapping OOS ownership, a 25-bar label/purge horizon, a sealed final holdout, independent candidate-quality replay, current alert-policy replay, base/moderate/severe cost scenarios, detection-day block-bootstrap uncertainty, primary candidate slices, trial-family Benjamini–Hochberg bookkeeping, and explainable preliminary/final decisions. Results persist in the research tables and can be previewed, sealed, executed/resumed, inspected/exported, and deliberately revealed through the API, CLI, and dashboard.

The following remain explicitly deferred rather than implied by a v1 result: rolling or multi-asset fold execution, inner-loop parameter selection and sensitivity/leave-one-out reports, concentration diagnostics, probability-of-backtest-overfitting, a detailed fee/spread/funding/impact cost model, asynchronous worker/heartbeat execution, live-score calibration, and any automatic change to live alert ranking. A `PASS` is research evidence for the exact sealed scope, not a profitability guarantee.

## 1. Outcome we are building toward

TBot should be able to answer, with reproducible evidence:

1. Does this exact strategy version produce positive net expectancy on later unseen data?
2. Does it retain a useful win rate while offering and realizing acceptable reward relative to risk?
3. Is the result stable across time, symbols, timeframes, directions, and the market regimes in which the strategy claims to operate?
4. How uncertain is the result, given the number and dependence of the observed signals?
5. Does the strategy still work under less favorable execution-cost assumptions?
6. Is performance broad, or is it produced by one short period, symbol, regime, or parameter value?
7. Is the current algorithmic confidence score actually associated with better later outcomes?
8. Has the final holdout been used only after the hypothesis and implementation were frozen?

The output is an evidence grade and promotion decision, not a promise of future profitability.

## 2. Scope and boundaries

### In scope

- Chronological development, walk-forward, and final-holdout partitions.
- Purged fold boundaries that respect the signal-to-outcome label horizon.
- Reproducible experiment manifests and immutable run provenance.
- Signal-level and current alert-policy-level evaluation.
- Per-fold and segmented performance reports.
- Block-bootstrap uncertainty intervals and sample-size warnings.
- Parameter sensitivity and cost-stress scenarios.
- A registry of every tested hypothesis/variant.
- `PASS`, `PROVISIONAL`, and `REJECT` decisions with reason codes.
- Research CLI, persisted results, API read surfaces, and a non-technical dashboard report.

### Explicitly out of scope for this target

- Automatic order submission or exchange credentials.
- Portfolio allocation across correlated assets.
- Automatic hyperparameter search in the first release.
- Machine-learning ranking.
- Full maker/taker, funding, spread, and market-impact decomposition; that remains the separate cost-model phase. The validator will initially use the engine's versioned all-in per-side cost plus stress scenarios.
- Promoting the LLM's verdict as an edge. Rules-only versus LLM cohort validation belongs after deterministic strategy validation works.
- Causal S/R reconstruction. S/R remains blocked from historical strategies until its own prefix-causal implementation is complete.

## 3. Non-negotiable research decisions

### 3.1 Chronology only

Random train/test splits are forbidden. Financial observations are ordered, regimes cluster in time, and nearby signals share information. Every development, fold-test, and holdout boundary must be chronological and stored in UTC.

### 3.2 Two evaluation tracks

The platform is a signal-generation system, while the current backtest also models one open position and a cooldown. Those answer different questions and must not be mixed.

| Track | Unit being evaluated | Purpose | Valid metrics |
| --- | --- | --- | --- |
| Candidate-quality | Every eligible strategy signal, evaluated independently under the same entry/stop/target/expiry rules | Measures whether the detector produces good opportunities | Win rate, TP-before-stop rate, net R, offered R:R, payoff ratio, MFE/MAE, duration, uncertainty |
| Alert-policy | Signals admitted by the current one-position, highest-confidence, cooldown policy | Measures the behavior of the actual alert-selection policy | Net P&L/R, equity curve, drawdown, Sharpe/Sortino, profit factor, exposure and rejection counts |

Candidate-quality outcomes may overlap. Therefore they must **not** be compounded into an equity curve and must not be assigned a portfolio Sharpe ratio. Dependence is handled with time-blocked uncertainty estimation.

The alert-policy track remains the only track allowed to report a compounded account curve. Until confidence is calibrated across strategies, promotion decisions use one-strategy experiments; multi-strategy runs are diagnostic only.

### 3.3 Frozen strategy first; tuning later

Walk-forward v1 evaluates an exact, frozen strategy version and parameter manifest. It will not search for a better parameter set.

When parameter selection is added later, it must be an inner-development activity:

- fewer than five material tunable parameters unless separately justified;
- a predeclared objective;
- training/inner-validation data only;
- a deterministic tie-break favoring the simpler or baseline configuration;
- no final-holdout access during selection;
- every attempted configuration registered as a tested variant.

### 3.4 Detection-time context only

Regime, volatility state, direction, score, levels, and all feature values used for segmentation must be captured as they existed on the signal candle. Later chart state cannot relabel the setup.

### 3.5 The holdout is consumable

An untouched holdout is useful only until it is inspected. Once revealed, it becomes historical research data. Any strategy, threshold, or scope change made after seeing it creates a new experiment generation and requires a new later holdout or a forward-paper-validation period.

## 4. Terminology

| Term | Meaning in TBot |
| --- | --- |
| Hypothesis family | The economic idea being tested, such as “trend pullback recovery has positive 1h expectancy” |
| Variant | One exact strategy/parameter/filter implementation within a family |
| Development region | Earliest chronology available for implementation checks and, later, parameter selection |
| Walk-forward region | Chronological sequence of unseen test folds used to estimate stability |
| Final holdout | Latest sealed region opened once after code, parameters, scope, and gate policy are frozen |
| Fold | One train/development interval, purge boundary, and later OOS test interval |
| Label interval | From signal detection through next-open entry and the last candle that can determine its outcome |
| Purge | Removal of development observations whose label interval overlaps a later OOS interval |
| Embargo | A configured gap used when a split design could otherwise let adjacent labels or fitted state contaminate another sample |
| Primary slice | A predeclared segment used in the promotion decision |
| Exploratory slice | A diagnostic segment that may generate a later hypothesis but cannot retroactively promote the current one |

## 5. Current foundation and missing capabilities

### Already available in engine 4.0.0

- Closed-candle/as-of enforcement and warm-up isolation.
- Prefix-causal active strategies and fail-closed strategy execution.
- Next-candle-open entry and fixed detection-time levels.
- Conservative same-bar stop/target resolution.
- One open position, deterministic simultaneous-signal selection, and cooldown.
- Hybrid eight-/24-bar expiry.
- After-cost P&L and R, reproducibility manifest, candle fingerprint, and simulation rejection counts.
- Detection-time `regime` on `SetupSignal`.

### Gaps this plan must close

- No experiment entity above an atomic `BacktestRun`.
- No development/walk-forward/holdout boundary model.
- No independent outcome for every eligible signal.
- No persisted fold ownership or fold-level metrics.
- No volatility-regime, structural-bias, MFE, MAE, or initial offered-R metadata on historical outcomes.
- No block-bootstrap confidence intervals or minimum-sample policy.
- No sensitivity, cost-stress, concentration, or multiple-testing report.
- No deliberate holdout reveal workflow.
- No evidence-grade/promotion decision service.
- No UI that explains stability and uncertainty.

## 6. Research protocol

### 6.1 Experiment lifecycle

```text
DRAFT
  -> PREFLIGHT_FAILED          data/scope cannot support the design
  -> SEALED                    manifest, folds, parameters, code and holdout fixed
  -> WALK_FORWARD_RUNNING
  -> WALK_FORWARD_COMPLETE
  -> PROVISIONAL or REJECT     decision without opening final holdout
  -> HOLDOUT_REVEALED          deliberate one-time action
  -> PASS or REJECT            final decision
  -> SUPERSEDED                a later strategy generation exists
```

Failures caused by infrastructure are recorded separately from research rejection. A crashed worker must never turn into a `REJECT`; it remains `FAILED` and resumable.

### 6.2 Required declaration before execution

Every experiment must state:

- one-sentence hypothesis and economic/behavioral rationale;
- hypothesis family and variant identifier;
- strategy name, strategy version, source commit, and engine version;
- all relevant parameters, including defaults inherited from the strategy;
- symbols, timeframes, allowed directions, and intended regimes;
- exact data source and coverage;
- development, walk-forward, and sealed holdout boundaries;
- fold mode and sizes;
- entry, target, conflict, expiry, cooldown, and candidate-outcome policies;
- base and stressed cost assumptions;
- primary metrics and primary slices;
- promotion-policy version;
- all known sibling variants already tested in the hypothesis family;
- deterministic random seed for resampling.

The normalized manifest is hashed. An experiment with the same manifest hash must be idempotent: it returns/resumes the existing experiment rather than silently creating a duplicate trial.

### 6.3 Data-coverage preflight

Before outcomes are calculated, generate a coverage report for every requested symbol/timeframe:

- first and last closed candle;
- candle count and expected candle count;
- missing/duplicate/out-of-order timestamps;
- invalid OHLC envelopes, zero/non-finite prices, negative volume, and unclosed rows;
- required warm-up availability;
- strategy compatibility and historical-causality support;
- number of calendar days and the proposed fold count;
- data fingerprint by symbol/timeframe and overall experiment fingerprint;
- data-source limitations, including unavailable/delisted universe members where relevant.

An integrity error fails the experiment before any performance result is visible. Insufficient history produces a transparent `PROVISIONAL`/`insufficient_history` outcome, not smaller hidden folds.

### 6.4 Partition hierarchy

The chronology is partitioned in this order:

```text
earliest                                                     latest
|----------- development + walk-forward region -----------|-- sealed holdout --|
| train 1 | purge | test 1 | train 2 ... | purge | test N |                  |
```

Initial defaults are policy values, not universal market truths:

- holdout size: the later of 20% of eligible chronology or two planned test windows;
- walk-forward folds: at least five non-overlapping OOS test windows for a possible `PASS`;
- test step: equal to test-window length by default, preventing duplicate OOS observations;
- training mode: anchored by default for frozen strategies; rolling becomes available when regime recency is a declared hypothesis;
- window sizes: selected from data availability and expected **signal counts**, never by looking at outcome quality;
- minimum fold history: enough warm-up plus enough earlier development data to run the declared process.

If the dataset cannot support five folds and a sealed holdout, it can still produce a research report, but not a final `PASS`.

### 6.5 Fold-boundary and label rules

The current maximum outcome horizon is derived from engine policy, not copied into a second hard-coded constant:

```text
label_span = next_open_delay + max(unfavorable_expiry_bars, favorable_expiry_bars)
```

With current defaults this is at most 25 bars, subject to earlier stop/target exit.

Rules:

1. A candidate belongs to a test fold by **signal detection time**, not exit time.
2. Its outcome may use only the declared label window after detection.
3. Development candidates whose realized/maximum label interval overlaps the next test start are purged from any fitting, calibration, or threshold selection.
4. Warm-up candles before a fold are feature initialization only and never become fold observations.
5. OOS test windows used for aggregate claims do not overlap.
6. Every signal has exactly one walk-forward fold owner; duplicate ownership is a hard integrity failure.
7. The final holdout receives no parameter, threshold, calibration-bucket, or regime-policy fit.
8. Any future rolling design that trains on observations after a test window must apply a post-test embargo as well as label-aware purging.

### 6.6 State at a fold boundary

Candidate-quality and alert-policy state are handled differently:

- Candidate-quality outcomes are assigned by detection time and evaluated independently.
- Alert-policy replay begins from a declared flat-account boundary for each OOS fold. Pre-fold signals and their positions are excluded. This measures a deploy-from-here policy and avoids importing development P&L into OOS sizing.
- Initial OOS equity is reset to the manifest's nominal capital in every fold. Aggregate fold claims use R-based metrics; fold capital curves are not concatenated as though they were one uninterrupted live account.
- A separate full-period frozen-policy replay may be shown as a diagnostic, clearly labelled non-folded, to illustrate uninterrupted operational behavior.

This boundary policy must be versioned because allowing a development position to cross into a test fold would answer a different question.

### 6.7 Final-holdout procedure

The holdout can be revealed only when:

- walk-forward execution is complete;
- the strategy source commit and parameter manifest are frozen;
- the promotion policy and primary slices are frozen;
- the experiment records the decision to proceed;
- no unresolved integrity error exists.

The reveal operation stores the actor, timestamp, code/manifest hash, and previous walk-forward decision. A changed hash blocks reveal and requires a new experiment generation.

## 7. Outcome data contract

### 7.1 Candidate outcome record

Create one immutable record for every strategy signal that passes its deterministic eligibility threshold, even when the alert-policy simulator later rejects it because another position is open.

Minimum fields:

| Group | Fields |
| --- | --- |
| Identity | experiment, evaluation run, fold, candidate sequence, strategy name/version, symbol, timeframe |
| Timing | signal candle open/close, next-open entry time, exit time, label-window end |
| Context | direction, confidence, trend regime, volatility regime, structural bias, regime strength |
| Detection levels | detection close, proposed entry, fixed stop, TP1, TP2, ATR |
| Fill and risk | actual next-open fill, stop distance, TP1/TP2 offered R after fill, skipped-fill reason |
| Outcome | terminal label, gross R, net R, gross/net P&L at nominal risk, duration bars/minutes |
| Path diagnostics | maximum favorable excursion in R, maximum adverse excursion in R, time to MFE/MAE |
| Costs | base cost in bps/currency/R and cost-scenario identifier |
| Audit | engine/policy versions, source run ID, exact rejection/reason codes |

Skipped candidates remain part of the funnel report. A missed fill, invalid level order, sub-1R gap, missing next candle, or data error cannot disappear from denominators without explanation.

### 7.2 Alert-policy outcome record

Reuse the existing `BacktestTrade` and `BacktestRun` semantics, then add fold/evaluation references and detection-time segmentation metadata. Preserve the current single-position and cooldown audit counts.

### 7.3 MFE/MAE semantics

- MFE and MAE start at the actual next-open fill and end at the terminal exit/expiry candle.
- Gap behavior follows the same open-first execution rules as the simulator.
- MFE/MAE are descriptive path extrema; they do not invent an executable exit sequence when both extremes occur in one OHLC candle.
- Results are normalized by the fixed initial stop risk so different prices and symbols are comparable.

## 8. Metrics and statistical treatment

### 8.1 Candidate-quality primary metrics

| Metric | Definition |
| --- | --- |
| Eligible candidates | All deterministic candidates before portfolio/cooldown filtering |
| Evaluated candidates | Candidates with a valid next-open fill and complete label window |
| Net win rate | Share with net R greater than zero |
| TP1-before-stop rate | Share whose conservative terminal path reached TP1 before stop |
| Mean/median net R | After-cost outcome normalized by initial stop risk |
| Expectancy | `win_rate × mean_win_R - loss_rate × abs(mean_loss_R)`; must reconcile to mean net R |
| Payoff ratio | `mean_win_R / abs(mean_loss_R)` |
| Break-even win rate | `abs(mean_loss_R) / (mean_win_R + abs(mean_loss_R))` |
| Offered TP1/TP2 R | Reward available after actual fill relative to the fixed stop |
| MFE/MAE | Favorable/adverse path excursion in initial R |
| Expiry rate | Share closed by time horizon rather than target/stop |
| Funnel rates | Detected → valid levels → fillable → evaluated → policy-admitted |

`win_rate` is never interpreted alone. It is displayed beside payoff ratio, break-even win rate, mean net R, offered R, and uncertainty.

### 8.2 Alert-policy primary metrics

- net P&L and net R;
- profit factor;
- maximum drawdown in currency, percentage, and R;
- calendar-time Sharpe and Sortino under the existing engine definition;
- percentage of profitable folds;
- median and worst fold expectancy;
- signals rejected by overlap/cooldown and their independent candidate quality;
- strategy/symbol/timeframe contribution and concentration.

### 8.3 Uncertainty

Signals near one another are dependent, particularly when their label windows overlap. An IID trade bootstrap is not sufficient.

Implement a deterministic moving-block or stationary block bootstrap over chronological detection-time clusters:

- resampling unit: UTC detection-day aggregates/clusters;
- default block length: at least the maximum label horizon converted to calendar time, with a policy minimum appropriate to the timeframe;
- bootstrap repetitions: 5,000 by default;
- stored seed: required in the manifest;
- intervals: 95% percentile interval initially; BCa may be added after validation;
- primary intervals: mean net R, win rate, payoff ratio, and profit factor;
- fold-level dispersion reported separately from the pooled interval.

Also report a Wilson interval for the raw win proportion as an understandable secondary diagnostic. If the bootstrap cannot form enough independent blocks, the result is `insufficient_independent_history`.

### 8.4 Sample-size policy

Initial versioned policy:

| OOS evaluated candidates | Interpretation |
| ---: | --- |
| `< 30` | Descriptive only; `PROVISIONAL`, no probability wording |
| `30–99` | Early evidence; may remain `PROVISIONAL` regardless of point estimates |
| `>= 100` | Eligible for statistical `PASS` if all other gates pass |

The report also shows independent time blocks and per-slice counts. One hundred near-identical signals from one volatile week are not treated like one hundred independent observations.

### 8.5 Segmentation

Primary slices are declared before execution:

- fold;
- strategy version;
- symbol;
- timeframe;
- direction;
- intended trend regime;
- volatility regime;
- confidence bucket;
- base versus stressed cost scenario.

Secondary diagnostics may include structural bias, session/time-of-day, duration, and offered-R bucket. Sparse cross-products are suppressed rather than displayed as precise estimates.

For each slice show `N`, net win rate, mean/median net R, payoff ratio, interval, expiry rate, and contribution to total positive/negative R.

### 8.6 Concentration

Report:

- share of positive net R from the top symbol, timeframe, regime, month, and fold;
- share of candidates from the most active time block;
- leave-one-symbol-out and leave-one-fold-out expectancy;
- whether removing the best fold changes the sign of expectancy.

A concentrated result may be valid for a restricted scope, but cannot be promoted as a general strategy.

### 8.7 Multiple testing

Every variant within a hypothesis family increments the family trial count, including rejected and manually inspected variants.

- The confirmatory null hypothesis is `mean net R <= 0` after base costs unless the manifest declares another primary hypothesis.
- Any p-value used for correction must come from a dependence-aware, versioned test such as a centered/null block-bootstrap test. Do not estimate a p-value merely by counting how many samples from an ordinary uncentered bootstrap fall below zero.
- Store the raw and adjusted significance measures.
- Use Benjamini-Hochberg false-discovery-rate control for a family of related planned tests; default `q = 0.10`.
- Bonferroni may be used for a small set of high-stakes confirmatory tests.
- A chart inspection can create a new hypothesis but cannot be treated as untouched confirmation.
- The final report lists all sibling trials and whether the current result survives the configured correction.

No correction can repair an undisclosed test history; the experiment register is part of the evidence.

## 9. Promotion and evidence-grade policy

The policy is versioned and its thresholds are configuration, not hidden code constants.

### 9.1 Hard integrity gates

Any of the following produces `REJECT` or `PREFLIGHT_FAILED` without performance promotion:

- non-final candles, data gaps, invalid prices, duplicate timestamps, or insufficient warm-up;
- a non-prefix-causal strategy/feature path;
- overlapping or duplicate OOS fold ownership;
- development labels crossing an OOS boundary without purge;
- changed code/parameters after the experiment was sealed;
- missing base costs or incompatible engine/policy versions;
- incomplete fold execution presented as a complete result.

### 9.2 Statistical viability gate

Initial `PASS` requirements:

- at least five completed non-overlapping OOS folds;
- at least 100 evaluated OOS candidates and enough independent time blocks;
- pooled mean net R above zero with a 95% block-bootstrap lower bound above zero;
- median fold expectancy above zero;
- at least 60% of sufficiently sampled folds positive;
- no unexplained catastrophic loss concentration;
- base-cost expectancy positive;
- all declared primary-scope results reported, including failures;
- final holdout opened only after freeze and independently passes the configured holdout gate.

If evidence is positive but the sample/history is insufficient, the result is `PROVISIONAL`, not `PASS`.

### 9.3 Final-holdout confirmation gate

The holdout is a confirmation sample, not another optimization window. It does not need to contain 100 candidates by itself, but it must be large enough to contradict a lucky walk-forward result.

Initial requirements:

- at least 30 evaluated holdout candidates and enough independent time blocks; otherwise the experiment remains `PROVISIONAL` and continues into forward paper observation;
- holdout mean net R above zero at base cost;
- holdout win rate above its realized break-even win rate;
- no more than 50% degradation in mean net R from the walk-forward estimate unless the difference is within the predeclared uncertainty tolerance;
- the combined walk-forward-plus-holdout mean net R retains a 95% block-bootstrap lower bound above zero;
- no new intended-regime, integrity, concentration, or cost-stress failure;
- no post-seal strategy, parameter, scope, slice, or gate-policy change.

A holdout failure cannot be averaged away by an excellent development period. Its failure reason is reported directly and the strategy is rejected or returned to a new-generation research cycle.

### 9.4 Product-quality targets

Statistical viability is necessary but may still produce signals the user does not want. The initial quality targets for an alert-eligible grade are:

- net win-rate point estimate at least 50%;
- win rate exceeds the calculated break-even rate by at least three percentage points;
- median offered TP1 R at least 1.25 after the actual next-open fill;
- mean winning R at least 0.8 and payoff ratio at least 1.2;
- mean net expectancy at least `+0.10R` per evaluated candidate;
- expiry rate and adverse excursion remain within strategy-specific limits;
- results are not dependent on a single symbol/fold/regime.

These are starting decision thresholds, not claims that these exact numbers are universally optimal. Baseline reports may justify a later policy revision, but the revision applies only to new experiments and is never made to rescue an already-seen result.

### 9.5 Regime and scope gate

- Only regimes declared in the strategy's intended scope are required for general promotion.
- An intended regime with at least 30 OOS candidates and materially negative expectancy blocks unrestricted promotion.
- A strategy may receive a restricted `PASS` for a symbol/timeframe/regime subset only if that subset was predeclared or is confirmed in a new experiment.
- Post-hoc discovery of a good slice creates a new hypothesis and remains exploratory in the current report.

### 9.6 Parameter robustness gate

For every material numeric parameter:

- test at least `-20%`, `-10%`, baseline, `+10%`, and `+20%` where the value's meaning permits;
- vary one parameter at a time first, followed only by a small declared joint grid if necessary;
- require a broad positive neighborhood rather than one isolated best point;
- flag any neighbor with more than 50% expectancy degradation;
- record all tested neighbors in the multiple-testing family.

Parameter sensitivity is run on development/walk-forward data, never used to retrofit the opened holdout.

### 9.7 Cost robustness gate

Run the exact same candidates under:

- zero cost, for diagnostic decomposition only;
- base configured cost;
- moderate stress, initially base plus 10 bps per side;
- severe stress, initially base plus 25 bps per side.

`PASS` requires positive base-cost expectancy. A result that becomes sharply negative under moderate stress is downgraded or restricted, even if the base estimate is positive.

### 9.8 Evidence grades

| Grade | Meaning | Live use |
| --- | --- | --- |
| A | Full OOS and holdout pass; quality, stability, sensitivity, and cost targets met | Eligible for highest evidence tier |
| B | Statistical pass with a minor documented limitation or narrower validated scope | Eligible within validated scope |
| C | Positive but provisional evidence, small sample, or incomplete regime coverage | Research/dashboard only by default |
| Insufficient | Cannot estimate reliably | No probability language or top ranking |
| Rejected | Integrity or performance gate failed | Suppressed from evidence-backed ranking |

## 10. Proposed architecture

Keep the existing `BacktestEngine` as the source of execution semantics. Add a focused research package rather than expanding the API blueprint into a monolith.

```text
backend/app/research/
  manifest.py              typed manifest, normalization, hashing, policy versions
  coverage.py              data and fold feasibility preflight
  folds.py                 chronological fold planner and purge validation
  candidate_replay.py      independent candidate outcome labels
  walk_forward.py          orchestration, resume, fold ownership
  metrics.py               candidate and policy metric calculations
  uncertainty.py           block bootstrap, Wilson intervals, effective blocks
  segmentation.py          predeclared slices and concentration reports
  sensitivity.py           parameter/cost scenarios and trial registration
  promotion.py             PASS/PROVISIONAL/REJECT decision + reason codes
  report.py                canonical JSON/CSV/summary export
```

Supporting surfaces:

| Area | Proposed change |
| --- | --- |
| Atomic replay | Extract a non-persisting `BacktestEngine.evaluate_dataset(...)` path and make current `run(...)` delegate to it without semantic changes |
| Strategy signal metadata | Extend historical signal extraction to retain volatility regime, structural bias, regime strength, ATR, and declared score/gate metadata |
| Persistence | Add research experiment/fold/evaluation/candidate-outcome tables with versioned migrations |
| API | Add a dedicated research blueprint; keep `/api/backtest` backward compatible |
| Batch use | Add `backend/scripts/run_walk_forward.py` consuming a manifest file |
| Frontend | Add a Validation report page/tabs; keep the current Backtest page for single atomic simulations |

### 10.1 Refactor safety rule

Extracting the pure replay path must be behavior-preserving. A golden regression fixture must show that the existing single-window API produces identical trades, P&L, equity curve, audit counts, and configuration before and after the refactor. A pure refactor does not justify silently changing engine 4.0 semantics.

### 10.2 Long-running execution

A multi-fold, multi-scenario evaluation should not hold one HTTP request open.

- The API persists a queued experiment and returns `202`.
- A database-backed worker/poller claims pending fold work.
- Fold work is idempotent by experiment/fold/track/scenario key.
- Progress and heartbeat timestamps are persisted.
- A restart resumes missing/failed infrastructure work without duplicating completed outcomes.
- Research rejection and execution failure use different statuses.

The CLI uses the same service synchronously and is the first delivery surface; the dashboard/API execution layer follows after correctness is established.

## 11. Persistence design

Use versioned migrations for this subsystem. Do not add another startup-time `ALTER TABLE` sequence for research evidence.

### 11.1 `research_experiments`

Core fields:

- `id`, `family_id`, `variant_id`, `generation`;
- `name`, `hypothesis`, `rationale`;
- `status`, `decision`, `evidence_grade`, decision reason codes;
- normalized `manifest_json` and unique `manifest_sha256`;
- engine version, strategy versions, source commit;
- data coverage/fingerprint summary;
- development, walk-forward, and holdout boundaries;
- holdout state, reveal timestamp, reveal actor, reveal manifest hash;
- promotion-policy, metric-schema, bootstrap, and fold-policy versions;
- created/started/completed/updated timestamps and infrastructure error.

### 11.2 `research_folds`

- experiment ID and fold number;
- train start/end, purge start/end, test start/end;
- fold mode and derived label-span bars;
- train/test candle and candidate counts;
- chosen parameter manifest if later tuning is enabled;
- status, heartbeat, start/completion timestamps, and error;
- references to atomic backtest runs;
- fold fingerprint and no-overlap audit result.

Unique key: experiment + fold number.

### 11.3 `research_evaluation_runs`

One row per fold × track × cost scenario × strategy/symbol/timeframe scope:

- experiment/fold IDs;
- `candidate_quality` or `alert_policy` track;
- cost scenario and execution-policy version;
- source run ID where applicable;
- status and metrics JSON;
- candidate/trade/funnel counts;
- result fingerprint.

### 11.4 `backtest_candidate_outcomes`

Stores the immutable candidate-outcome contract from section 7.1. Use indexed columns for common filters and JSON only for extensible evidence/reason details.

Suggested indexes:

- experiment + fold;
- strategy version + symbol + timeframe;
- signal time;
- trend regime + volatility regime;
- direction and confidence bucket;
- terminal outcome and skip reason.

### 11.5 `research_metric_slices`

- evaluation/experiment ID;
- slice type and normalized slice key;
- sample size and independent-block count;
- point metrics JSON;
- uncertainty JSON;
- primary/exploratory flag;
- sparse/insufficient flag and reason.

### 11.6 `research_trials`

- family ID, experiment/variant ID, parameters and hypothesis label;
- created order and whether confirmatory or exploratory;
- raw/adjusted significance values;
- multiple-testing method and family size;
- result/decision.

## 12. Manifest contract

Illustrative YAML:

```yaml
schema_version: "walk-forward-manifest-v1"
name: "trend-following-1h-baseline"
family_id: "trend-pullback-1h"
variant_id: "baseline-v3"
hypothesis: "The frozen 1h trend-pullback strategy has positive net OOS expectancy."
rationale: "Directional persistence after a controlled EMA pullback."

strategy:
  name: "Trend Following"
  version: "3.0"
  source_commit: "<git-commit>"
  parameters: {}

scope:
  symbols: [BTCUSDT, ETHUSDT, SOLUSDT]
  timeframes: [1h]
  directions: [LONG, SHORT]
  intended_regimes: [TRENDING_UP, TRENDING_DOWN]

data:
  source: "stored-binance-futures-klines"
  start: "<utc>"
  end: "<utc>"
  require_closed: true
  gap_policy: "fail"

partitions:
  mode: "anchored"
  development_end: "<utc>"
  test_window_days: 60
  step_days: 60
  minimum_folds: 5
  holdout_start: "<utc>"
  holdout_end: "<utc>"
  purge_policy: "label-aware"

execution:
  engine_version: "4.0.0"
  entry_policy: "next-bar-open-fixed-levels"
  same_bar_conflict: "stop-first"
  alert_policy: "single-position-five-bar-cooldown"
  candidate_policy: "independent-outcomes-v1"
  initial_capital: 10000
  risk_per_trade: 0.01

cost_scenarios:
  - {name: zero, bps_per_side: 0}
  - {name: base, bps_per_side: 10}
  - {name: moderate, bps_per_side: 20}
  - {name: severe, bps_per_side: 35}

statistics:
  bootstrap_method: "moving-block-detection-day-v1"
  bootstrap_repetitions: 5000
  confidence_level: 0.95
  seed: 20260825
  multiple_testing: {method: benjamini-hochberg, q: 0.10}

promotion_policy: "signal-quality-gate-v1"
primary_slices: [fold, symbol, direction, trend_regime, volatility_regime]
known_family_trials: []
```

The service resolves defaults, adds derived policy values, normalizes key order/numbers/timestamps, then stores and hashes the final manifest.

## 13. Service, API, CLI, and report contracts

### 13.1 Research service commands

- create and validate manifest;
- generate coverage/fold preview without outcomes;
- seal experiment;
- execute or resume walk-forward folds;
- compute statistics and promotion decision;
- reveal and execute final holdout;
- export canonical report;
- mark a completed experiment superseded without deleting it.

### 13.2 Proposed API

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/api/research/experiments/preview` | Validate manifest and preview coverage/folds without performance |
| `POST` | `/api/research/experiments` | Persist and seal an experiment |
| `POST` | `/api/research/experiments/<id>/execute` | Queue/resume walk-forward work |
| `POST` | `/api/research/experiments/<id>/reveal-holdout` | Deliberately consume the sealed holdout |
| `GET` | `/api/research/experiments` | List experiments and decisions |
| `GET` | `/api/research/experiments/<id>` | Full experiment summary and audit |
| `GET` | `/api/research/experiments/<id>/folds` | Fold status and metrics |
| `GET` | `/api/research/experiments/<id>/slices` | Segmented metrics and uncertainty |
| `GET` | `/api/research/experiments/<id>/export` | Canonical JSON report |

Creation and reveal routes must validate state transitions. A client cannot edit a sealed manifest in place.

### 13.3 CLI

`run_walk_forward.py` should support:

- `--manifest <path>`;
- `--preview`;
- `--execute`;
- `--resume <experiment-id>`;
- `--reveal-holdout <experiment-id>` with an explicit confirmation flag;
- `--export <experiment-id>`;
- machine-readable exit codes and a concise terminal summary.

The CLI and API call the same domain service; neither reimplements research logic.

### 13.4 Canonical report

The JSON export is authoritative and includes:

- manifest and hashes;
- coverage/preflight report;
- fold plan and state-transition history;
- per-fold candidate and alert-policy metrics;
- pooled OOS metrics and uncertainty;
- all primary and permitted exploratory slices;
- funnel/rejection audit;
- concentration, sensitivity, and cost-stress results;
- multiple-testing family/trial report;
- sealed/revealed holdout metadata and results;
- promotion decision, evidence grade, and every reason code;
- source commit, engine/strategy/policy/schema versions.

A concise Markdown/HTML summary may be generated from this JSON but must not become a second source of truth.

## 14. Frontend experience

The current Backtest page remains the place for one historical simulation. Add a separate **Validation** area because one run and a research decision are conceptually different.

### 14.1 Experiment setup

- Plain-language hypothesis and rationale.
- Strategy, scope, intended regimes, and costs.
- Data-coverage preview with proposed development/fold/holdout timeline.
- Visible warnings for insufficient history, sparse expected signals, or unsupported strategies.
- A clear “Seal experiment” action explaining that the latest holdout should remain unseen.

### 14.2 Progress

- Overall and per-fold status.
- Candidate/policy tracks and cost scenarios.
- Resume/failure state without converting failures to research rejection.
- No partial headline result while required folds are missing.

### 14.3 Result summary

Lead with:

- decision and evidence grade;
- mean net R with interval;
- net win rate, break-even win rate, and payoff ratio together;
- offered versus realized R;
- sample size, independent blocks, fold count, and profitable-fold percentage;
- base/moderate/severe cost result;
- largest limitation and decision reason codes.

### 14.4 Result views

1. **Overview** — decision, quality metrics, uncertainty, limitations.
2. **Walk-forward** — chronological fold chart/table; no averaged result without fold distribution.
3. **Segments** — symbol, timeframe, direction, regime, volatility, confidence bucket.
4. **Robustness** — parameter neighborhood, cost stress, leave-one-out, concentration.
5. **Candidate funnel** — all signals, skipped fills, policy exclusions, completed outcomes.
6. **Audit** — manifest, data/code hashes, versions, fold ownership, holdout history.

Probability wording is disabled for insufficient or uncalibrated evidence.

## 15. Delivery phases

### Phase 0 — Freeze protocol and assess available history

**Goal:** establish design feasibility without inspecting outcomes.

Tasks:

1. Inventory candle coverage by symbol/timeframe.
2. Count causal signals by strategy/symbol/timeframe without calculating or ranking outcomes.
3. Select initial primary strategy and scope for the pilot.
4. Freeze `walk-forward-manifest-v1`, fold-policy v1, metric-schema v1, and promotion-policy v1.
5. Choose test/holdout-window sizes using history and signal counts only; target at least 30 expected holdout candidates without inspecting their outcomes.
6. Document data-source and universe limitations.

Acceptance:

- A preview report proposes at least five non-overlapping test folds and a sealed holdout, or clearly states why only provisional evidence is possible.
- No outcome metric is used to choose fold boundaries.

### Phase 1 — Pure replay seam and metadata completeness

**Goal:** make the repaired engine reusable without changing its behavior.

Tasks:

1. Extract pure dataset evaluation from `BacktestEngine.run`.
2. Preserve the existing database/API wrapper.
3. Extend historical signal metadata with detection-time regime details, ATR, and offered levels.
4. Add source/policy/schema version fields.
5. Add golden equivalence tests against engine 4.0 fixtures.

Acceptance:

- Existing atomic backtest trades, metrics, curves, and audits are identical on fixed fixtures.
- Changing future candles cannot alter prior detection metadata.

### Phase 2 — Candidate-quality replay

**Goal:** label every eligible signal independently.

Tasks:

1. Implement independent candidate outcomes using the same entry, gap, level, target, stop-first, and expiry semantics.
2. Add MFE/MAE and offered-R calculations.
3. Persist evaluated and skipped candidate records with reason codes.
4. Reconcile candidate labels to alert-policy trades when a candidate is admitted.

Acceptance:

- Every input signal appears exactly once in the funnel.
- An admitted candidate and its policy trade have matching fill/terminal semantics.
- Overlapping candidates do not affect one another in the candidate track.

### Phase 3 — Manifest, fold planner, and holdout seal

**Goal:** make chronology and research intent immutable.

Tasks:

1. Implement typed manifest validation/normalization/hash.
2. Implement anchored and rolling fold planning; expose anchored first.
3. Derive label span from engine policy.
4. Implement label-aware purge and duplicate-fold ownership checks.
5. Add coverage-only preview and experiment sealing.
6. Add holdout state machine and reveal audit.

Acceptance:

- Boundary tests cover every timeframe and daylight/timezone input is normalized to UTC.
- No OOS signal can belong to two aggregate folds.
- A changed manifest cannot execute under the old sealed experiment ID.

### Phase 4 — Orchestration and resumable persistence

**Goal:** execute all folds and scenarios reliably.

Tasks:

1. Add experiment, fold, evaluation, candidate-outcome, metric-slice, and trial tables.
2. Create the research tables through the application's current schema-initialisation path; add versioned migrations when a migration framework is introduced.
3. Implement fold execution for both tracks.
4. Add idempotent keys, heartbeat, retry/resume, and final completeness checks.
5. Build CLI preview/execute/resume/export.

Acceptance:

- Interrupting a run and resuming it creates no duplicate folds/candidates/trades.
- A report cannot become complete while required fold/scenario work is missing.
- Two executions of the same sealed manifest produce matching fingerprints and metrics.

### Phase 5 — Statistics, slices, and robustness

**Goal:** convert fold outcomes into defensible evidence.

Tasks:

1. Implement candidate and alert-policy metric sets.
2. Implement block bootstrap and Wilson intervals with deterministic seeds.
3. Add primary slices and sparse-sample suppression.
4. Add fold stability, concentration, leave-one-out, cost-stress, and parameter-sensitivity reports.
5. Add hypothesis-family registry and multiple-testing correction.

Acceptance:

- Statistical fixtures reproduce expected values and seeded intervals.
- Shuffling row order fails; chronological order is required.
- Small/dependent samples cannot display precise probability language.

### Phase 6 — Promotion gate and final holdout

**Goal:** issue a reproducible research decision.

Tasks:

1. Implement versioned gate rules and reason codes.
2. Produce preliminary `PROVISIONAL`/`REJECT` from walk-forward results.
3. Enforce deliberate holdout reveal.
4. Recompute only the frozen final decision after holdout.
5. Generate evidence grade and validated scope.

Acceptance:

- High in-sample performance cannot override failed OOS/integrity gates.
- Insufficient evidence is never promoted to `PASS`.
- A post-reveal code/parameter change invalidates reuse of the holdout decision.

### Phase 7 — API and frontend

**Goal:** make the research process usable without hiding its rigor.

Tasks:

1. Add research blueprint and async/status endpoints.
2. Add frontend types/client calls.
3. Build experiment preview/seal/progress/result views.
4. Add canonical export and audit view.
5. Update API, architecture, backtesting, and strategy documentation.

Acceptance:

- The UI can trace every headline number to folds, sample size, cost scenario, and manifest.
- Holdout reveal is explicit and cannot be triggered accidentally.
- Partial/failed runs are visually distinct from rejected strategies.

### Phase 8 — Pilot and shadow validation

**Goal:** prove the validator with one narrow strategy before using it broadly.

Pilot order:

1. Choose one causal strategy, one timeframe, and a small liquid-symbol set.
2. Register the baseline hypothesis before viewing results.
3. Run walk-forward and inspect implementation/audit correctness.
4. Freeze and reveal the final holdout once.
5. Compare validator conclusions with a forward paper-observation period.
6. Fix validator defects before testing new enablers.
7. Only then begin causal S/R ablation against the frozen baseline.

Acceptance:

- The pilot report is reproducible from its manifest.
- Any validator defect found during the pilot invalidates affected decisions and triggers a new evaluation schema/policy version.

## 16. Test strategy

### Unit tests

- manifest normalization, hashing, immutable fields, and invalid configurations;
- fold boundary generation for all timeframes;
- label-span derivation and purge behavior;
- exact one-fold ownership and non-overlap;
- candidate outcome gap/stop/target/expiry parity;
- MFE/MAE for long/short/gap cases;
- metric formulas, empty/zero-loss/zero-win cases;
- deterministic bootstrap and Wilson intervals;
- sparse-slice suppression;
- gate status/reason-code matrices;
- multiple-testing corrections.

### Causality/leakage tests

- Mutating candles after a fold's allowed label window cannot change its signals or outcomes.
- Mutating the final holdout cannot change walk-forward folds, fitted parameters, buckets, or decision policy.
- Development labels that cross the test boundary are removed from any fitted statistic.
- Higher-timeframe/regime metadata is prefix invariant.
- No full-period normalization or percentile calculation may include future rows.

### Integration tests

- in-memory database experiment creation through final decision;
- persistent idempotency and resume after simulated worker failure;
- API state transitions and conflict responses;
- migration upgrade on an existing database containing backtest records;
- canonical export round trip;
- existing `/api/backtest` compatibility.

### Golden/regression tests

- fixed engine 4.0 atomic backtest fixture before/after replay extraction;
- fixed multi-fold manifest with known fold ownership and result fingerprint;
- candidate-policy reconciliation fixture;
- frontend build and affected lint/type checks.

### Adversarial tests

- spectacular in-sample and negative OOS performance;
- one profitable fold carrying all results;
- 100 signals on one day;
- strategy with no losses/infinite point profit factor;
- insufficient holdout candles;
- duplicate execution request;
- strategy code changes after seal;
- missing cost scenario;
- all candidates skipped by next-open gap;
- regime slice discovered only after viewing results.

## 17. Observability and operational controls

Log and expose:

- experiment/fold/evaluation IDs in every worker message;
- queued/running/completed/failed counts;
- current fold/scenario/track and heartbeat age;
- data and result fingerprints;
- duration and memory by fold;
- candidate/funnel counts and rejection reasons;
- resume/retry count;
- holdout reveal events;
- policy/schema version mismatches.

Research records are append-only except operational status/heartbeat fields. Material completed results are never overwritten; a corrected computation creates a new metric-schema or experiment generation.

## 18. Risks and mitigations

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Repeatedly viewing the holdout | Converts unseen evidence into tuned history | Seal/reveal state, hash check, generation rule, later forward paper period |
| Fold overlap | Counts the same market event multiple times | Non-overlapping default, unique signal ownership, hard audit failure |
| Dependent signals | Makes confidence intervals too narrow | Candidate/policy separation and chronological block bootstrap |
| Sparse regimes | Produces misleading slice precision | Minimum counts, independent-block counts, suppression/provisional status |
| Portfolio policy masks signal quality | Weak signals may disappear behind cooldown | Independent candidate track plus policy track |
| Candidate overlap inflates an equity curve | Impossible simultaneous compounding | No candidate-track Sharpe/equity curve |
| Strategy score is uncalibrated | Raw fractions are not probabilities/comparable | One-strategy promotion; calibration phase later |
| Parameter mining | Finds a lucky local optimum | Frozen v1, small declared grids later, sensitivity plateau, trial registry/FDR |
| Regime labels use future data | Creates false conditional edge | Detection-time causal labels and prefix-invariance tests |
| Data vendor/universe bias | Omits failed assets or bad periods | Coverage/universe disclosure and point-in-time data when scope requires it |
| Long jobs fail mid-run | Creates partial or duplicated evidence | DB-backed idempotent folds, heartbeat, resume, completeness gate |
| Refactor changes engine results | Invalidates prior semantics silently | Golden equivalence tests and explicit engine/policy versioning |
| Arbitrary gate thresholds | Encourages moving goalposts | Versioned policy frozen before outcomes; changes apply prospectively |

## 19. Implementation sequence and dependencies

```text
Phase 0 protocol/data assessment
  -> Phase 1 pure replay seam
      -> Phase 2 candidate outcomes
      -> Phase 3 manifest/folds/holdout
          -> Phase 4 orchestration/persistence/CLI
              -> Phase 5 statistics/robustness
                  -> Phase 6 gate/holdout decision
                      -> Phase 7 API/UI
                          -> Phase 8 pilot
                              -> causal S/R baseline-vs-enabler ablation
```

Phase 2 and Phase 3 can be implemented in parallel only after the Phase 1 replay contract is frozen. Phase 7 must not lead the work; a polished UI cannot compensate for ambiguous fold or metric semantics.

## 20. Definition of done

The implemented minimum v1 is complete when:

1. An immutable manifest can be previewed, sealed, hashed, executed, resumed, and exported.
2. At least five chronological non-overlapping OOS folds plus a sealed holdout can be represented.
3. Purge/label rules are enforced and causality tests pass.
4. Every eligible signal is accounted for in the candidate funnel.
5. Candidate-quality and alert-policy reports remain distinct and reconcile where applicable.
6. Per-fold/pooled candidate metrics, primary slices, and base/moderate/severe cost-stress results are available. Concentration and sensitivity remain subsequent robustness work.
7. Uncertainty reflects time dependence and small samples are downgraded.
8. The gate produces explainable `PASS`, `PROVISIONAL`, or `REJECT` with a versioned policy.
9. Holdout reveal is deliberate, audited, and invalidated by post-seal changes.
10. Existing engine 4.0/API behavior remains regression-tested.
11. A pilot strategy can produce a reproducible full report and documented decision when adequate candle coverage is supplied.
12. Only after a pilot produces adequate OOS/holdout evidence does TBot begin testing causal S/R, fractals, or other enablers against the frozen baseline.

## 21. First implementation slice

Start with **Phase 0 + Phase 1**, not the dashboard:

1. Generate a no-outcome coverage/signal-count inventory.
2. Choose one pilot strategy/timeframe/liquid-symbol scope.
3. Freeze the initial manifest/fold/metric/gate contracts.
4. Extract the pure replay seam behind golden engine-4.0 equivalence tests.
5. Only then build independent candidate outcomes and the fold orchestrator.

This establishes the smallest trustworthy foundation on which every later enabler comparison will depend.
