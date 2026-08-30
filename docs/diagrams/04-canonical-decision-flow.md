# D04 — Canonical Decision Flow

Source baseline: `main@65c063ffea6209ecd84b224656bbc627ff811898`

## Purpose

Show the current `entry_decision_v1` policy as a fail-closed decision flow without collapsing lifecycle context into actionability.

Authoritative references: `backend/src/waterfallhunter/core/entry_decision.py`, `docs/DECISION_ENGINE.md`, `docs/MODEL.md`.

```mermaid
flowchart TD
    Start[Current normalized evidence]
    Packet{Canonical packet can be established honestly?}
    Unavailable[UNAVAILABLE\nrequired evidence/runtime state cannot be established]
    Fresh{Analysis <= 180s and reference <= 60s?}
    Stale[NO_TRADE\nSTALE_ANALYSIS / STALE_REFERENCE]
    Invalid{Lifecycle STRUCTURE_INVALIDATED?}
    Invalidated[INVALIDATED]
    Veto{Deterministic market-data veto?}
    NoTradeVeto[NO_TRADE]
    Chase{EXHAUSTED or extension >= 1.2 ATR?}
    Late[LATE\nANTI_CHASE_HARD_BLOCK]
    ExecInputs{Execution inputs available?}
    NoExec[NO_TRADE\nEXECUTION_UNAVAILABLE]
    Score[Compute versioned readiness + coverage]
    Gates{Readiness >= 78, coverage >= 65%,\ndirection + timing + execution + cross-exchange + TradePlan pass?}
    Triggered{Lifecycle state TRIGGERED?}
    Prior{Same-lifecycle predecessor is ENTRY_READY or ACTIVE?}
    Active[ACTIVE\nno new entry instruction]
    Ready[ENTRY_READY\nPROACTIVE SIGNAL]
    PredBlock[NO_TRADE\nENTRY_READY_PREDECESSOR_REQUIRED]
    FormBand{Readiness >= 55?}
    Forming[FORMING\ndo not enter yet]
    NoTrade[NO_TRADE]

    Start --> Packet
    Packet -- No --> Unavailable
    Packet -- Yes --> Fresh
    Fresh -- No --> Stale
    Fresh -- Yes --> Invalid
    Invalid -- Yes --> Invalidated
    Invalid -- No --> Veto
    Veto -- Yes --> NoTradeVeto
    Veto -- No --> Chase
    Chase -- Yes --> Late
    Chase -- No --> ExecInputs
    ExecInputs -- No --> NoExec
    ExecInputs -- Yes --> Score --> Gates
    Gates -- Yes --> Triggered
    Triggered -- No --> Ready
    Triggered -- Yes --> Prior
    Prior -- Yes --> Active
    Prior -- No --> PredBlock
    Gates -- No --> FormBand
    FormBand -- Yes --> Forming
    FormBand -- No --> NoTrade
```

## Current policy values

- `forming_minimum = 55.0`
- `entry_ready_minimum = 78.0`
- `max_analysis_age_seconds = 180.0`
- `max_reference_age_seconds = 60.0`
- `anti_chase_hard_block_atr = 1.2`
- Entry readiness additionally requires at least `65%` evidence coverage and passing direction, timing, execution, cross-exchange, and TradePlan gates.

## Important nuance

`UNAVAILABLE` belongs to the public EntryDecision contract for cases where required evidence/runtime state cannot be established honestly. Inside `build_entry_decision`, stale analysis/reference and unavailable execution inputs are explicit blockers that produce `NO_TRADE`; the diagram keeps those paths distinct rather than pretending every missing input maps to the same state.

A lifecycle state of `TRIGGERED` does not create an entry instruction. The current engine may emit `ACTIVE` only when a same-lifecycle prior decision was already `ENTRY_READY` or `ACTIVE`; otherwise it fails closed.
