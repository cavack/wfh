# Canonical Decision Engine

Every symbol receives one public entry decision:

`NO_TRADE | FORMING | ENTRY_READY | ACTIVE | LATE | INVALIDATED | EXPIRED | UNAVAILABLE`

Only `ENTRY_READY` is a proactive entry signal. `ACTIVE` means an earlier entry-ready event is now in progress; lifecycle `TRIGGERED` never means “enter now”.

## Readiness policy

The current policy uses hard invalidators plus weighted evidence. Initial versioned bands are `ENTRY_READY >= 78`, `FORMING >= 55`, otherwise `NO_TRADE`, subject to mandatory timing/direction/execution checks and anti-chase.

## Hard invalidators

Examples include stale/missing mandatory market reference, invalid contract identity, invalid execution geometry, explicit anti-chase hard block, contradictory fresh market identity, and deterministic market-data veto conditions.

## Persistence

`ENTRY_READY` is an immutable event. It does not silently disappear. Later transitions are explicit (`ACTIVE`, `LATE`, `INVALIDATED`, `EXPIRED`) with timestamp, reason codes, evidence/model version, and provenance.

There is one user-facing readiness score. Research scores may exist internally but cannot become parallel actionable rankings.

## Decision diagrams

See [D04 Canonical Decision Flow](diagrams/04-canonical-decision-flow.md), [D05 Lifecycle State Machine](diagrams/05-lifecycle-state-machine.md), [D06 EntryDecision State Machine](diagrams/06-entry-decision-state-machine.md), [D08 Entry Decision Transaction Sequence](diagrams/08-entry-decision-transaction-sequence.md), and [D09 TradePlan / Risk Flow](diagrams/09-tradeplan-risk-flow.md).
