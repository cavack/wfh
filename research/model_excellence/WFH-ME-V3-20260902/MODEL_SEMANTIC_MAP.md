# Model semantic map (M0.2)

**Mission:** `WFH-ME-V3-20260902`  
**Source SHA:** `d129264b22bacbe4601c2ee8a373a9c1e2cbac30`  
**Scope:** current callers and evidence semantics only. No thresholds, weights, or production behavior were changed.

## Authority and caller flow

```text
multi_exchange_validator.validate_candidate()
  -> ScoreV2.evaluate()                 # strict, trade-eligible quality packet
  -> result metrics / watch_score
main._evaluate_candidate()
  -> stage_lifecycle_store.advance()    # persisted stage context, hard-gating allowed
  -> build_entry_decision()              # sole canonical user-facing decision
  -> _apply_signal_leverage_advisory()  # advisory only, after decision
  -> entry_decision_store.append_if_changed()
  -> dashboard / notifier / replay context
```

`ScoreV2` is not itself the public decision. `EntryDecisionPolicy` owns the public bands and hard gates. Lifecycle is context used by the decision engine; it is not an instruction to enter. The v2 lifecycle implementation is explicitly shadow-only and cannot promote a decision.

## Semantic inventory traced to real callers

| Boundary | Current semantics | Real caller/evidence | Classification | Measurement disposition |
|---|---|---|---|---|
| ScoreV2 strict | `ScoreV2.evaluate()` requires complete candles, microstructure, derivatives, same-contract price location, cross-exchange confirmation, and taker-sell dominance. It returns `is_valid=false` rather than a partial trade score when any strict gate fails. | `backend/src/waterfallhunter/core/multi_exchange_validator.py:918`; `score_v2.py:65-101` | **INTENTIONAL_SEPARATION** (strict quality contract) | Keep separate from watch scoring; compare only on matched packets. |
| ScoreV2 watch | `evaluate_watch()` is observational and `trade_eligible=false`; it normalizes available component weight and reports unavailable components instead of imputing them. Maximum watch component weight is 85 by design/legacy contract. | `score_v2.py:103-164`; `multi_exchange_validator.py:1012` | **INTENTIONAL_SEPARATION** | Watch freshness/backlog must be corrected or excluded before model comparison; current baseline has WATCH p95 age 4156.4s. |
| Entry Readiness | `_score_entry_components()` builds a separate 0-100 readiness score from available evidence; `build_entry_decision()` applies coverage, direction, timing, execution, cross-exchange, trade-plan, freshness, and lifecycle predecessor gates. Bands are 55/78. | `entry_decision.py:768-878`; `main.py:2496-2519` | **INTENTIONAL_SEPARATION, DRIFT NOT PROVEN** | A semantic crosswalk is required before any parameter search; do not treat readiness as ScoreV2 probability. |
| Timing difference | ScoreV2 candle schema/scoring includes `two_closed_candles` and `volume_acceleration`; Entry Readiness timing helper uses its own timing fields and threshold (`timing >= 10`). | `score_v2.py:10-35`; `entry_decision.py:65-85,539-597` | **UNRESOLVED SEMANTIC DIFFERENCE** | Replay matched packets and inspect rejection/outcome attribution; no evidence supports changing either layer. |
| Structure difference | ScoreV2 structural maximum is 35 and includes `support_broken`; Entry Readiness structure maximum is 20 and uses its own component set. | `score_v2.py:20-29,177-250`; `entry_decision.py:50-63,539-597`; `CURRENT_MODEL_CONTRACT.json MODEL-DIFF-002` | **UNRESOLVED SEMANTIC DIFFERENCE** | Determine whether strict validation vs readiness evidence is intentional or double-counted. Needs promotion-grade data. |
| Execution difference | ScoreV2 strict microstructure is a completeness/approval gate. Entry Readiness awards execution points but hard-blocks unless spread and slippage are each `<=0.30%`; ScoreV2's documented spread acceptance is looser (`<=0.50%`). | `entry_decision.py:232-278`; `CURRENT_MODEL_CONTRACT.json MODEL-DIFF-003` | **UNRESOLVED SEMANTIC DIFFERENCE** | Build a boundary-case matrix and outcome ledger; do not tune friction limits. |
| Lifecycle v1 | `stage_lifecycle_store.advance()` persists ordered hype/damage/setup/trigger state with TTLs; main injects it into metrics and passes the candidate state to Entry Decision. | `stage_lifecycle.py:8-34`; `main.py:2442-2478` | **INTENTIONAL CONTEXT/GATING** | Lifecycle transitions are not labels of expected return; freshness and persistence completeness are required for interpretation. |
| Lifecycle v2 | `evaluate_lifecycle_v2_shadow()` emits hashed transitions with `shadow_only=true` and `trade_eligible=false`; main persists a comparison but leaves v1 as final state. | `lifecycle_v2_shadow.py:212-270`; `main.py:2598-2625` | **INTENTIONAL SHADOW** | Exclude from champion selection; use only divergence diagnostics. |
| Anti-chase/terminal | Freshness and deterministic invalidators are evaluated before Anti-Chase. `1.2 ATR` can convert only otherwise FORMING/ENTRY_READY/ACTIVE to LATE; sub-FORMING remains NO_TRADE. Terminal retention preserves provenance. | `entry_decision.py:496-530,612-760,824-878`; `docs/DECISION_ENGINE.md` | **RESOLVED CORRECTNESS CONTRACT** | Regression-covered; do not interpret current terminal behavior as a tunable model defect. |
| Leverage | `build_signal_leverage_advisory()` derives a bounded 4–18x advisory from independent score/stop/volatility/friction/suitability/exchange bounds. Main computes it after the canonical decision; non-actionable states are not recommended/unavailable and no fallback is fabricated. | `risk_manager.py:74-223`; `main.py:2478-2519`; `entry_decision.py:307-336` | **INTENTIONAL ADVISORY** | Exclude leverage from readiness/champion optimization; missing causal inputs are measurement blockers, not directional evidence. |
| Trade plan | Entry Decision only regards a plan as present when required numeric entry/stop/TP1/TP2 fields exist and status is not rejected; expiry becomes a hard block. It is a decision gate, not a score component. | `entry_decision.py:341-360,800-815`; execution plan producer `execution_planning.py:615-836` | **INTENTIONAL SAFETY GATE** | Attribute no-plan cases to geometry vs upstream evidence/runtime separately before optimization. |
| Evidence acquisition/freshness | Causal ages are calculated at decision time; analysis `>180s`, reference `>60s`, missing, invalid, or future evidence fails closed. WS/REST path counters are recorded separately. | `main.py:2490-2504`; `production_evidence.py:50-105`; `main.py:584-668` | **MEASUREMENT BLOCKER** | Baseline WS share 0.036067 (507 WS vs 13,550 REST), WATCH p95 age 4156.4s, backlog 147. Model conclusions from this sample are contaminated by observation latency. |

## Classifications and decisions

1. **Intentional separation:** strict ScoreV2, observational watch score, canonical Entry Decision, lifecycle context, lifecycle-v2 shadow, leverage advisory, and trade-plan safety gate have different authority and failure semantics. They must not be merged into one score.
2. **Unresolved semantic differences:** timing, structure, and execution differences are verified facts but not yet defects. The current corpus and natural signal counters cannot distinguish specialization from drift or double-counting.
3. **Resolved correctness:** current Anti-Chase ordering/provenance and terminal semantics are protected regression contracts, not optimization targets.
4. **Measurement blockers:** stale WATCH observations, WS/REST imbalance, absent natural signal/outcome counters, Tier-2 ~15.94-day evidence, and missing cost-adjusted net-R prevent champion selection or parameter search.

## Explicit dependency graphs (required M0.2 crosswalk)

### B. ScoreV2 component graph

```text
normalized candles ─┬─> structure (35: post-pump/support break)
                    ├─> timing (20: closed candles, LH, reclaim/repump, RSI, close, volume)
microstructure ─────┼─> execution (20)
derivatives ────────┼─> derivatives confirmation (15)
cross-exchange ─────┼─> confirmation (5)
price/location ─────┴─> same-contract location (5)
all strict completeness/approval gates ──> strict score_v2, is_valid, trade_eligible
available packet ──> score_v2_watch (normalized observational score, never an entry)
```

### C. Entry Readiness component graph

```text
structure rules (20) ───────┐
timing rules (15) ──────────┤
order flow (20) ────────────┤
derivatives (15) ───────────┤─> 0-100 readiness + coverage
execution (10) ─────────────┤
cross exchange (5) ─────────┤
price location (5) ─────────┤
cascade (10) ───────────────┘
readiness/coverage + direction + timing>=10 + execution/cross gates
  + freshness + trade_plan_present ──> canonical EntryDecision
```

### D. Lifecycle and gate graph

```text
candidate evidence -> lifecycle v1 advance/persist -> predecessor state/TTL context
                    -> readiness classification (NO_TRADE/FORMING/ENTRY_READY/ACTIVE)
                    -> freshness/invalidator gates
                    -> Anti-Chase (>=1.2 ATR: FORMING/READY/ACTIVE -> LATE)
                    -> terminal retention (LATE/INVALIDATED/EXPIRED)
```

Lifecycle v2 is a parallel `shadow_only` comparison and cannot alter this path.

### E. Trade-plan dependency graph

```text
market/evidence + entry geometry + stop/targets + fee/slippage/funding assumptions
  -> execution_planning feasibility/expiry
  -> required numeric entry, stop, TP1, TP2 and non-rejected status
  -> trade_plan_present gate
```

The plan is not a readiness component; it is a safety gate. Missing or rejected geometry therefore rejects an otherwise high score.

### F. Leverage dependency graph

```text
canonical decision + ScoreV2 metrics["score"] + structural stop + ATR/volatility
  + execution friction/suitability + exchange maximum
  -> independent bounds -> adaptive_signal_leverage_v2 (4x..18x advisory)
```

The score input is a semantic coupling to ScoreV2, but leverage is computed after the decision and is not a readiness gate or promotion metric. Non-actionable decisions produce no recommendation.

### G. Evidence reuse / double-counting matrix

| Evidence family | ScoreV2 | Readiness | Cascade/other consumers | Classification |
|---|---|---|---|---|
| taker buy/sell ratio | timing/order-flow/derivatives confirmation | order flow (10) | cascade trade-flow/derivatives | **POTENTIAL_DOUBLE_COUNT**; quantify by ablation |
| buy/sell flow imbalance | execution/order-flow inputs | order flow (5) | cascade flow | **POTENTIAL_DOUBLE_COUNT**; shared raw evidence |
| funding, OI, top-trader ratio | derivatives (15) | derivatives (15) | cascade derivatives | **POTENTIAL_DOUBLE_COUNT**; not a reproduced defect |
| spread, slippage, depth | execution gate/score | execution points + hard limits | cascade liquidity, plan feasibility, leverage friction | **VERIFIED_INTENTIONAL_REUSE** for safety; contribution overlap unresolved |
| candles/LH/reclaim/RSI/close/volume | structure and timing | structure and timing | lifecycle context | **VERIFIED_INTENTIONAL_REUSE** across specialized contracts; timing semantics unresolved |

No row is classified as a reproduced model defect without matched-packet attribution and outcome evidence.

### H. Missing/unavailable behavior

Strict ScoreV2 fails closed on incomplete packets; watch scoring reports unavailable components and normalizes available weight. Entry Readiness tracks coverage, but missing/invalid/future evidence can trigger `UNAVAILABLE`/hard blocks and is never directional evidence. Missing trade-plan fields fail `trade_plan_present`; leverage returns unavailable/not-recommended rather than a fallback.

### I. Runtime freshness coupling

Analysis age over 180 seconds or reference age over 60 seconds invalidates the decision. The baseline WATCH population (p95 4156.4 seconds, backlog 147) therefore changes evidence availability before scoring. REST fallback dominance (13,550 vs 507 WS hits) is an acquisition confounder. This is a measurement defect, not evidence for lowering thresholds.

### J. Candidate optimization boundaries

Allowed next step is a matched, point-in-time replay crosswalk of timing, structure, and execution differences, stratified by lifecycle and availability, followed by immutable natural outcomes with cost-adjusted net-R. Parameter search, leverage changes, threshold changes, and champion promotion remain blocked until freshness and outcome integrity are repaired.

## Readiness disposition

- **Parameter search:** `BLOCKED` until causal freshness is within the `<180s` target (or observations are explicitly censored), current-contract matched replay is available, and promotion-grade outcomes include cost-adjusted net-R.
- **Current model promotion:** `BLOCKED`; existing artifacts report 210 complete of 790 outcome rows, maximum two complete outcomes for any stage-2 configuration, and OOS selection evidence not run.
- **Allowed next evidence:** construct a deterministic crosswalk/replay of the three unresolved differences, stratified by lifecycle state and evidence availability; collect immutable natural signals/outcomes without lowering gates.
- **Safety invariants:** `SHORT_ONLY`, `SIGNAL_ONLY`, `LIVE_TRADING_ENABLED=false`, missing/stale evidence remains unavailable, and PR #115/main are untouched.

## Required output sections A-J

### A. Authority and scope

`multi_exchange_validator` produces model packets; `main._evaluate_candidate` composes
the canonical packet; `build_entry_decision` is the sole user-facing decision authority.
Persistence occurs through `entry_decision_store.append_if_changed` before downstream
dashboard/notification consumers. No frontend or advisory score is an authority.

### B. ScoreV2 dependency graph

```text
candles + microstructure + derivatives + cross_exchange_confirmed
  + price_location
    -> ScoreV2._gates()
      -> ScoreV2.evaluate()
        -> strict score/components OR is_valid=false
```

The watch branch is separate:

```text
partial packets -> ScoreV2.evaluate_watch()
  -> normalized observational score + coverage + unavailable_components
  -> trade_eligible=false
```

Strict evaluation is called by `MultiExchangeValidator.validate`; watch evaluation is
called by its watch path. Neither call directly emits an entry decision.

### C. Entry Readiness dependency graph

```text
result_metrics
  -> _score_entry_components()
    -> readiness, coverage, direction/timing/execution/cross-exchange results
  -> _initial_block_reasons() [freshness + deterministic blockers]
  -> _trade_plan()
  -> _base_decision() [55/78 bands + gates + Anti-Chase ordering]
  -> _apply_previous_transition() [predecessor/terminal semantics]
  -> canonical entry_decision packet
```

`main` supplies candidate status and causal analysis/reference ages, then persists the
result. Readiness is not a probability and does not replace `ScoreV2`.

### D. Lifecycle dependency graph

```text
strategy_stages snapshot
  -> StageLifecycleStore.advance() -> persisted stage_lifecycle_v1
  -> main injects stage_lifecycle + candidate status into Entry Decision
```

The v2 path is diagnostic only:

```text
metrics + causal timestamps -> build_lifecycle_v2_evidence_from_metrics()
  -> evaluate_lifecycle_v2_shadow()
  -> compare_v1_v2_shadow()
  -> shadow_only=true, trade_eligible=false, persisted comparison
```

Lifecycle (`WATCH` through `EXHAUSTED`/`INVALIDATED`) is context, not an entry
instruction; `TRIGGERED` alone never means enter.

### E. Trade-plan dependency graph

```text
validated market constraints + risk policy + SafeLeverageBounds
  -> build_short_paper_execution_plan()
  -> position_setup (entry/stop/TP1/TP2[/TP3], expiry)
  -> EntryDecision._trade_plan()
  -> trade_plan_present gate; expiry -> TRADE_PLAN_EXPIRED blocker
```

Missing/rejected required numeric levels suppress actionability. Trade-plan feasibility
is a safety gate and is not an additional readiness score.

### F. Leverage dependency graph

```text
entry metrics + structural stop + volatility + friction
  + execution suitability + exchange ceiling
    -> build_signal_leverage_advisory()
      -> AVAILABLE (4-18x) | NOT_RECOMMENDED | UNAVAILABLE
```

`main` applies this after `build_entry_decision`; `project_leverage_advisory` only
projects the already-produced advisory into the packet/trade plan. It cannot create,
remove, or upgrade an entry decision.

### G. Evidence acquisition and freshness graph

```text
direct/shared WS or REST fallback
  -> normalized evidence + causal observed_at
  -> analysis/reference age at decision clock
  -> freshness invalidators (analysis >180s, reference >60s)
  -> fail closed before Anti-Chase classification
```

WS/REST path counters are observability, not model evidence. Cache reuse must preserve
causal timestamps and may not extend freshness.

### H. Evidence reuse and double-counting matrix

| Evidence family | ScoreV2 use | Entry Readiness use | Lifecycle/other use | Reuse risk/disposition |
|---|---|---|---|---|
| Candle structure/timing | strict gates and components | separate structure/timing points | lifecycle stage snapshot may consume derived stage flags | **REVIEW:** timing/structure are verified differences; matched replay needed to rule out double-counting |
| Microstructure (flow/depth/spread/slippage) | completeness/approval and execution component | execution points plus hard spread/slippage gates | leverage consumes friction/suitability | **REVIEW:** same raw packet is intentionally reused for distinct safety roles; do not sum outputs as one score |
| Derivatives/OI/funding/taker ratios | strict completeness and derivatives component | derivatives points/reasons | leverage may consume score/volatility bounds | **REVIEW:** causal input reuse is permitted; outcome attribution must identify correlated evidence |
| Cross-exchange confirmation | strict gate and 5-point component | separate 5-point confirmation/gate | contract identity validation | **PROTECTED:** same-contract requirement; no inferred confirmation |
| Price location/extension | strict price-location gate/component | price-location and Anti-Chase | execution plan geometry | **PROTECTED:** Anti-Chase is a terminal classification, not positive readiness |
| Lifecycle stage flags | not a strict ScoreV2 component | candidate status/stage-chain gate | persisted v1 and shadow-only v2 | **INTENTIONAL SEPARATION:** do not treat stage labels as returns or score points |
| Trade-plan levels | not a ScoreV2 component | presence/expiry gate | paper execution and replay | **INTENTIONAL SAFETY GATE:** no-plan is not bearish evidence |
| Freshness/availability | packet completeness/validity | hard invalidator and coverage | ranking freshness/observability | **PROTECTED:** missing/stale remains unavailable; never impute direction |

### I. Classification ledger

The classifications above remain: strict/watch/readiness/lifecycle/leverage/trade-plan
separation is intentional; timing, structure, and execution differences are unresolved
semantic differences (not reproduced defects); Anti-Chase provenance/terminal behavior
is resolved correctness; stale WATCH observations and insufficient outcomes are
measurement blockers.

### J. Measurement-readiness disposition

The map is diagnostic, not a promotion recommendation. Parameter search remains
`BLOCKED` until freshness contamination is resolved or explicitly censored, the
unresolved boundaries have matched current-contract replay, and cost-adjusted
promotion-grade outcomes exist. No thresholds or weights were changed.

## Source artifacts inspected

- `docs/MODEL.md`, `docs/DECISION_ENGINE.md`, `docs/PROJECT_HANDOFF.md`
- `research/model_excellence/WFH-ME-V3-20260902/CURRENT_MODEL_CONTRACT.json`
- `research/model_excellence/WFH-ME-V3-20260902/CURRENT_STATE_BASELINE.json`
- `/srv/waterfallhunter/research/agent_council/20260902/MODEL_PROBLEM_LEDGER.json` (pre-existing runtime artifact)
