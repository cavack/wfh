# FP/FN diagnosis protocol

**Mission:** `WFH-ME-V3-20260902`  
**Source SHA:** `d129264b22bacbe4601c2ee8a373a9c1e2cbac30`  
**Status:** `PROPOSAL`; preregister before any outcome comparison

## Scope and non-goals

This protocol diagnoses attribution errors and layer divergence. It does not
change thresholds, weights, lifecycle semantics, leverage, or production
behavior. It must not report a false-positive/false-negative rate until the
scientific eligibility gates in the measurement and outcome plans pass.

## Unit of analysis

The unit is one immutable, point-in-time candidate packet. A packet is eligible
only if its decision, evidence-as-of timestamp, code/contract hashes, and
outcome linkage are reproducible. Replay-complete but partially observed
packets remain observable and are excluded from fully observed outcome rates.

## Labels

For a declared horizon and cost-adjusted net-R rule:

- **TP:** canonical actionable decision and a complete eligible outcome meeting
  the preregistered success rule.
- **FP:** canonical actionable decision and a complete eligible outcome failing
  the success rule.
- **FN:** canonical non-actionable decision while a complete eligible
  counterfactual entry packet meets the success rule.
- **TN:** canonical non-actionable decision and no eligible counterfactual
  success.

Unresolved, stale, unavailable, invalid-level, duplicate, or
provenance-mismatched rows are **not** FP/FN labels.

## Attribution crosswalk

For every eligible packet, record the first blocking gate and all contributing
component points for both canonical Entry Readiness and the ScoreV2 strict/watch
layers. Attribute divergence to exactly one primary category:

```text
TIMING_SEMANTICS
STRUCTURE_SEMANTICS
EXECUTION_SEMANTICS
EVIDENCE_AVAILABILITY
FRESHNESS
TRADE_PLAN_GEOMETRY
LIFECYCLE_OR_ANTI_CHASE
OTHER_CONTRACT
```

The three unresolved semantic differences must be evaluated with matched
packets and identical evidence-as-of timestamps. Report both availability
changes and outcome changes; never infer quality from availability alone.

## Required strata

Every result must be stratified by:

1. lifecycle v1 state and lifecycle-v2 shadow state;
2. freshness bucket (`<=60s`, `60-180s`, `>180s`, invalid/future);
3. evidence availability family and WS/REST acquisition path;
4. symbol and time window;
5. trade-plan status and execution suitability.

No aggregate may hide a stratum with zero or incomplete outcomes.

## Metrics

Report counts and denominators first, then:

```text
precision, false-positive rate, false-negative rate,
net expectancy per eligible signal, profit factor,
max drawdown, tail loss, MAE, MFE, time-to-target,
late rate, signal frequency, and coverage/rejection attribution
```

Use cost-adjusted net-R as the primary utility. Win rate alone is prohibited.
Confidence intervals and minimum-sample rules must be declared before reading
results. No challenger may be selected from a stratum with insufficient
complete outcomes.

## Gate conditions

The protocol remains `NOT_RUN` until freshness/backlog is repaired or stale
rows are explicitly censored, natural signal/outcome denominators are
non-zero, complete costs are available, and the protected final holdout is
unopened. After eligibility, run deterministic matched replay, then
purged/embargoed walk-forward diagnosis, and only later consider ablation or
parameter search.
