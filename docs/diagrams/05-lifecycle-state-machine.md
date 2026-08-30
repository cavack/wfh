# D05 — Lifecycle State Machine

Source baseline: `main@65c063ffea6209ecd84b224656bbc627ff811898`

## Purpose

Show WaterfallHunter's lifecycle as contextual evidence progression, independently from the public `EntryDecision` contract.

Authoritative references: `README.md`, `docs/ARCHITECTURE.md`, `docs/MODEL.md`, lifecycle code/tests.

```mermaid
stateDiagram-v2
    state "FUEL-RICH" as FUEL_RICH
    state "PRE-TRIGGER" as PRE_TRIGGER

    [*] --> WATCH
    WATCH --> FUEL_RICH
    FUEL_RICH --> PRE_TRIGGER
    PRE_TRIGGER --> ARMED
    ARMED --> TRIGGERED
    TRIGGERED --> EXHAUSTED

    WATCH --> INVALIDATED: explicit invariant fails
    FUEL_RICH --> INVALIDATED: explicit invariant fails
    PRE_TRIGGER --> INVALIDATED: explicit invariant fails
    ARMED --> INVALIDATED: explicit invariant fails
    TRIGGERED --> INVALIDATED: explicit invariant fails

    note right of TRIGGERED
      Context only
      TRIGGERED != ENTRY_READY
    end note

    note right of EXHAUSTED
      Anti-chase / late context
      not a new-entry instruction
    end note
```

## Interpretation

- Lifecycle answers **where the setup is in its evolution**, not whether the operator should enter now.
- `TRIGGERED` is not actionable by itself. The canonical public actionability contract is `EntryDecision`, and only `ENTRY_READY` is proactive.
- `EXHAUSTED` is terminal late/chase context for the lifecycle path.
- Invalidation reason codes and persistence semantics remain defined by the current lifecycle implementation; the diagram intentionally avoids duplicating those internals.
