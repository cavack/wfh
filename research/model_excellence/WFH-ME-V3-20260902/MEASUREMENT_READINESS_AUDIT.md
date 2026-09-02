# Measurement-readiness audit

**Mission:** `WFH-ME-V3-20260902`  
**Source SHA:** `d129264b22bacbe4601c2ee8a373a9c1e2cbac30`  
**Phase:** post-M0.2 diagnostic  
**Classification:** `VERIFIED_FACT` unless explicitly marked otherwise

## Decision

Scientific parameter search and champion selection are **BLOCKED**. The current
runtime and historical evidence can support contract tracing and deterministic
replay design, but not an unbiased comparison of ScoreV2 and Entry Readiness.

## Readiness gates

| Gate | Current observation | Status | Consequence |
|---|---|---|---|
| Repository/production identity | Branch and `origin/main` remain at `d129264b…`; production baseline is the same revision | PASS | No drift reconciliation required |
| Point-in-time freshness | WATCH p95 age `4156.4s`; policy invalidates analysis age over `180s` and reference age over `60s` | BLOCKED | Do not treat stale rows as current model behavior |
| Evidence acquisition | 507 WS hits vs 13,550 REST fallbacks (`3.6067%` WS share) | BLOCKED | Availability is confounded with acquisition path |
| Natural signal observability | `signal_ledger_total=0`, `signal_outcomes_total=0` at baseline | BLOCKED | No current forward signal/outcome denominator |
| Replay determinism | Existing replay evidence distinguishes replay completeness from full market observation | PARTIAL | Replay may verify reconstruction, not scientific eligibility |
| Outcome completeness | 210 complete outcomes of 790 rows; cost-adjusted net-R unavailable | BLOCKED | No promotion-grade utility estimate |
| OOS protection | Prior OOS selection evidence was not run; final holdout is unopened | PASS/PROTECTED | No holdout contamination |

## What is measurable now

1. Deterministic reconstruction of the canonical decision from recorded causal
   context and hashes.
2. Layer divergence on matched packets: strict ScoreV2, watch score, Entry
   Readiness, lifecycle context, and leverage advisory.
3. Availability and rejection attribution, provided unavailable evidence is
   kept distinct from zero, fail, and directional evidence.
4. Trade-plan and leverage dependency traces without using leverage as a model
   outcome.

## What is not measurable now

- Outcome superiority of the timing, structure, or execution differences.
- False-positive/false-negative rates for a fresh production population.
- Cost-adjusted net expectancy or a promotion decision.
- Whether stale WATCH rows represent model rejection or delayed observation.

## Required next diagnostic

Build a preregistered, point-in-time matched crosswalk with one row per
candidate packet and these immutable fields:

```text
packet_id, symbol, observed_at, evidence_as_of,
ScoreV2 strict/watch inputs and result,
Entry Readiness components, score, coverage, gates, decision,
lifecycle_v1 state, lifecycle_v2 shadow state,
trade-plan status and geometry provenance,
leverage advisory state and bound inputs,
freshness ages, unavailable families, WS/REST path,
outcome linkage and cost-adjusted net-R fields
```

The crosswalk must stratify by lifecycle state, evidence availability, and
freshness bucket. It must compare the three unresolved semantic differences
without changing `55`, `78`, `65`, or `1.2 ATR`.

## Promotion boundary

Do not begin parameter search until the freshness/backlog defect is repaired or
the protocol explicitly censors stale observations, natural signals and
outcomes have non-zero denominators, and the outcome ledger provides
point-in-time, cost-adjusted net-R with a protected final holdout.

**Safety invariants:** short-only, signal-only, live trading disabled, Telegram
signal delivery disabled, and no changes to PR #115 or `main`.
