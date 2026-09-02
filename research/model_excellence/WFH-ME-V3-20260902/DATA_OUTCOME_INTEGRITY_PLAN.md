# Data and outcome integrity upgrade plan

**Mission:** `WFH-ME-V3-20260902`  
**Current code SHA:** `d129264b22bacbe4601c2ee8a373a9c1e2cbac30`  
**Phase:** diagnostic planning after measurement-readiness audit  
**Status:** `PROPOSAL`; no runtime or model changes

## Evidence-grounded constraints

1. Historical outcome evidence has only 210 complete rows of 790 and does not
   provide cost-adjusted net-R; it is development-grade, not promotion evidence.
2. The current baseline has zero natural signal and outcome counters, so a
   forward denominator is not yet available.
3. Replay completeness means deterministic reconstruction, not full market
   observation or scientific eligibility.
4. Unavailable evidence must remain an explicit state. It must not be converted
   into zero, pass, fail, or directional evidence.
5. Existing audit files with source SHA `65c063ff…` are historical evidence
   from another deployed revision and must not be silently combined with the
   `d129264b…` baseline.

## Required immutable record

For every canonical signal or replay candidate, persist or export a stable
record containing:

```text
signal_id / packet_id, symbol, strategy_profile, observed_at,
decision_at, evidence_as_of, code_sha, decision_contract_sha,
source_tree_sha, lifecycle_v1, lifecycle_v2_shadow,
score_v2_strict, score_v2_watch, readiness, coverage,
all component points and gate outcomes,
trade_plan fields and provenance,
leverage advisory state and bound inputs,
freshness ages, unavailable families, acquisition path,
outcome status, observation window, observed/expected candles,
entry/exit prices, gross R, every fee/slippage/funding component,
net R, outcome source and resolution timestamp
```

The record must be append-only, idempotently keyed, and sufficient to replay
the canonical decision without querying mutable live state.

## Outcome contract

An outcome is `SCIENTIFICALLY_EVALUABLE` only when the study protocol's required
market families are observed point-in-time, the horizon is complete, the
signal-to-outcome link is unique, and all cost fields needed by the declared
net-R formula are complete. Otherwise retain the outcome row for observability
but exclude it from the study denominator with an explicit reason.

Minimum status vocabulary:

```text
PENDING, COMPLETE, INSUFFICIENT_WINDOW, MISSING_MARKET_DATA,
INVALID_LEVELS, DUPLICATE_LINK, PROVENANCE_MISMATCH
```

`REPLAY_COMPLETE` and `MARKET_EVIDENCE_FULLY_OBSERVED` must remain separate
dimensions. A replay-complete `NO_TRADE` may be retained while still being
scientifically ineligible for a study requiring full observation.

## Validation sequence

1. **Schema/provenance check:** verify unique signal linkage, symbol
   normalization, timestamps, code/contract hashes, and append-only behavior.
2. **Freshness check:** report analysis/reference ages and acquisition path;
   censor stale WATCH observations rather than relabeling them.
3. **Availability crosswalk:** calculate denominators separately for each
   required evidence family and lifecycle state.
4. **Outcome completeness:** verify the full horizon and candle counts; classify
   insufficient windows explicitly.
5. **Cost reconciliation:** independently recompute gross R, fees, slippage,
   funding, and net R from recorded inputs; reject incomplete cost packets.
6. **Replay check:** reconstruct the decision from the immutable record and
   compare hashes and gate outcomes.
7. **Study lock:** preregister inclusion/exclusion rules and keep a final
   untouched holdout unopened until all challenger selection is complete.

## Acceptance criteria before optimization

- Non-zero natural signal and outcome denominators.
- No unresolved provenance or duplicate-link failures.
- Freshness/backlog repaired, or a declared censoring protocol applied.
- Complete cost-adjusted net-R for the analysis sample.
- Matched ScoreV2/readiness crosswalk stratified by availability and lifecycle.
- Protected final holdout and purged/embargoed walk-forward protocol.

Until all criteria pass, do not search thresholds, alter weights, compare
win-rate-only results, or promote a champion.
