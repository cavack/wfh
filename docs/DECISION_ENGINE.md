# Canonical Decision Engine

Every symbol receives one public entry decision:

`NO_TRADE | FORMING | ENTRY_READY | ACTIVE | LATE | INVALIDATED | EXPIRED | UNAVAILABLE`

Only `ENTRY_READY` is a proactive entry signal. `ACTIVE` means an earlier entry-ready event is now in progress; lifecycle `TRIGGERED` never means “enter now”.

## Readiness policy

The current `entry_policy_v1` uses hard invalidators plus weighted evidence. Its versioned bands are `ENTRY_READY >= 78`, `FORMING >= 55`, otherwise `NO_TRADE`, subject to mandatory timing/direction/execution checks and anti-chase. The Anti-Chase hard-extension boundary is `1.2 ATR`.

## Hard invalidators

Examples include stale/missing mandatory market reference, invalid contract identity, invalid execution geometry, contradictory fresh market identity, and deterministic market-data veto conditions. These fail closed before Anti-Chase classification; stale or otherwise invalid evidence is not relabelled `LATE` merely because the price is extended.

## Anti-Chase ordering

Anti-Chase is mandatory, but it is a late-entry classification rather than a source of positive readiness:

1. Validate freshness and deterministic invalidators.
2. Compute readiness and mandatory direction/timing/execution gates.
3. Classify readiness below `55` as `NO_TRADE`.
4. Convert an otherwise `FORMING`, `ENTRY_READY`, or `ACTIVE` decision to `LATE` when extension is at least `1.2 ATR`.
5. Classify lifecycle `EXHAUSTED` as `LATE` independently of readiness.

Therefore Anti-Chase does not turn sub-`FORMING` evidence into `LATE`. A same-lifecycle, non-`EXHAUSTED` legacy projection with readiness below `55` and no blocker other than `ANTI_CHASE_HARD_BLOCK` is recognized as an impossible pre-fix state and may recover to its current canonical decision; a genuine `EXHAUSTED` state remains terminal, and the historical event remains persisted.

## Persistence

`ENTRY_READY` is an immutable event. It does not silently disappear. Later transitions are explicit (`ACTIVE`, `LATE`, `INVALIDATED`, `EXPIRED`) with timestamp, reason codes, evidence/model version, and provenance.

There is one user-facing readiness score. Research scores may exist internally but cannot become parallel actionable rankings.

Decision and policy changes are recorded in the [Model Change Ledger](MODEL_CHANGELOG.md).
