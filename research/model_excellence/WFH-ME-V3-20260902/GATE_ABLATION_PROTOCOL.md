# Gate contribution and ablation protocol

**Mission:** `WFH-ME-V3-20260902`  
**Source SHA:** `d129264b22bacbe4601c2ee8a373a9c1e2cbac30`  
**Status:** `PROPOSAL`; execution is blocked by measurement readiness

## Purpose

Measure which gates and evidence families change availability, readiness, and
eligible outcomes. This is a diagnostic protocol, not permission to alter the
production policy.

## Fixed baseline

The baseline is the exact current contract: FORMING `55`, ENTRY_READY `78`,
coverage `65`, timing `10/15`, spread/slippage limits `0.30%`, freshness
limits `180s/60s`, and Anti-Chase `1.2 ATR`. Every ablation must run from the
same immutable packet and code/contract hashes.

## Design

For each eligible matched packet, compute:

1. the unchanged canonical decision;
2. a single-gate counterfactual with exactly one gate removed or one evidence
   family masked as unavailable;
3. a combined counterfactual only when preregistered as an interaction.

Never replace unavailable evidence with zero or a passing value. Counterfactual
outputs are research labels and must never be persisted as production
decisions, notifications, or orders.

Required ablation families:

```text
timing: two_closed_candles, volume_acceleration, timing>=10
structure: support_broken and each readiness structure rule
execution: spread, slippage, depth, microstructure approval
cross_exchange, derivatives, cascade, price location
coverage, trade-plan presence, freshness, Anti-Chase
```

## Measurements

For every ablation report paired counts before outcome metrics:

```text
decision transition matrix,
first blocking gate,
readiness and coverage deltas,
availability delta,
trade-plan feasibility delta,
late/invalidated/expired delta,
eligible outcome count,
cost-adjusted net-R and confidence interval
```

Stratify by lifecycle, freshness, evidence availability, acquisition path,
symbol, and time window. Report interactions only where the paired sample is
complete for both conditions. A gate that changes only availability is not
evidence of improved quality.

## Binding and interpretation safeguards

Score, coverage, hard gates, trade-plan presence, freshness, and Anti-Chase can
be mutually binding. Therefore do not rank gates by raw rejection count or
search thresholds independently. Attribute the first blocking gate, then report
all simultaneously failing gates and the joint transition matrix.

`ScoreV2` strict rejection and Entry Readiness rejection must be measured as
separate outcomes. Leverage is excluded from ablation utility and remains an
advisory output.

## Run gate

Status remains `NOT_RUN` until the measurement-readiness and outcome-integrity
acceptance criteria pass, the matched replay is available, and the final
holdout is protected. No ablation result may select a challenger or change
production behavior before purged/embargoed walk-forward validation.
