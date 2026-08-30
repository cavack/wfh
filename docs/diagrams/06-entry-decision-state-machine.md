# D06 — EntryDecision State Machine

Source baseline: `main@65c063ffea6209ecd84b224656bbc627ff811898`

## Purpose

Show the user-facing `entry_decision_v1` states and the persistence rules that make a previously actionable event explicit rather than silently disappearing.

Authoritative references: `backend/src/waterfallhunter/core/entry_decision.py`, `backend/src/waterfallhunter/core/entry_decision_store.py`, `docs/DECISION_ENGINE.md`.

```mermaid
stateDiagram-v2
    [*] --> NO_TRADE: insufficient / blocked
    [*] --> FORMING: readiness >= forming band
    [*] --> ENTRY_READY: all proactive gates pass
    [*] --> UNAVAILABLE: required state cannot be established honestly

    NO_TRADE --> NO_TRADE: fresh re-evaluation
    NO_TRADE --> FORMING: evidence improves
    NO_TRADE --> ENTRY_READY: all gates pass
    NO_TRADE --> UNAVAILABLE: required state unavailable

    FORMING --> FORMING: still incomplete
    FORMING --> NO_TRADE: readiness / evidence degrades
    FORMING --> ENTRY_READY: all gates pass
    FORMING --> UNAVAILABLE: required state unavailable

    ENTRY_READY --> ENTRY_READY: same setup remains ready
    ENTRY_READY --> ACTIVE: same-lifecycle TRIGGERED with valid predecessor
    ENTRY_READY --> LATE: anti-chase / late transition
    ENTRY_READY --> INVALIDATED: explicit invalidation / conditions lost
    ENTRY_READY --> EXPIRED: TradePlan expiry

    ACTIVE --> ACTIVE: same active setup remains valid
    ACTIVE --> LATE: late transition
    ACTIVE --> INVALIDATED: explicit invalidation / conditions lost
    ACTIVE --> EXPIRED: TradePlan expiry

    LATE --> LATE: sticky within same lifecycle
    INVALIDATED --> INVALIDATED: sticky within same lifecycle
    EXPIRED --> EXPIRED: sticky within same lifecycle

    note right of ENTRY_READY
      Only proactive signal state
    end note

    note right of ACTIVE
      Earlier ENTRY_READY is now in progress
      No new-entry instruction
    end note
```

## Transition semantics

- The current engine treats prior `ENTRY_READY`/`ACTIVE` decisions specially: expiry becomes explicit `EXPIRED`; invalidation becomes explicit `INVALIDATED`; late anti-chase conditions become `LATE`.
- A lifecycle `TRIGGERED` evaluation may become `ACTIVE` only when a same-lifecycle predecessor is already `ENTRY_READY` or `ACTIVE`. Without that predecessor, it fails closed with `ENTRY_READY_PREDECESSOR_REQUIRED`.
- `LATE`, `INVALIDATED`, and `EXPIRED` are sticky for the same lifecycle identity. A distinct lifecycle can start a fresh evaluation rather than silently rewriting the earlier event.
- Non-actionable states are recomputed from current evidence; exact reason codes remain in the canonical packet and durable transition history.
