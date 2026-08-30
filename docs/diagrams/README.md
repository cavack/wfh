# WaterfallHunter Architecture Diagram Suite

Source baseline: `main@65c063ffea6209ecd84b224656bbc627ff811898`

This suite is the canonical visual map of WaterfallHunter's current `SIGNAL_ONLY` architecture. The Mermaid source in these Markdown files is authoritative; rendered or whiteboard copies are presentation aids only.

## Product and runtime

- [D01 — System Context](01-system-context.md)
- [D02 — Runtime Deployment Topology](02-runtime-deployment-topology.md)
- [D03 — End-to-End Data Pipeline](03-end-to-end-data-pipeline.md)

## Decision semantics and evidence

- [D04 — Canonical Decision Flow](04-canonical-decision-flow.md)
- [D05 — Lifecycle State Machine](05-lifecycle-state-machine.md)
- [D06 — EntryDecision State Machine](06-entry-decision-state-machine.md)
- [D07 — Evidence Architecture](07-evidence-architecture.md)
- [D08 — Entry Decision Transaction Sequence](08-entry-decision-transaction-sequence.md)
- [D09 — TradePlan / Risk Flow](09-tradeplan-risk-flow.md)

## Persistence and product delivery

- [D10 — Persistence ERD](10-persistence-erd.md)
- [D11 — Dashboard / API / SSE](11-dashboard-api-sse.md)
- [D12 — Notification Delivery](12-notification-delivery.md)

## Research, operations, and release

- [D13 — Scientific Validation](13-scientific-validation.md)
- [D14 — Observability / Incident Flow](14-observability-incident-flow.md)
- [D15 — CI / Release / Production Certification](15-ci-release-production-certification.md)
- [D16 — Repository Responsibility Map](16-repository-responsibility-map.md)
- [D17 — Master Architecture Map](17-master-architecture-map.md)

## Shared terminology

- Product mode: `SIGNAL_ONLY`.
- Canonical public entry contract: `EntryDecision`.
- Public states: `NO_TRADE | FORMING | ENTRY_READY | ACTIVE | LATE | INVALIDATED | EXPIRED | UNAVAILABLE`.
- Only `ENTRY_READY` is a proactive entry signal.
- `ACTIVE` means a previously emitted entry-ready setup is in progress; it is not a new-entry instruction.
- Lifecycle context is separate: `WATCH -> FUEL-RICH -> PRE-TRIGGER -> ARMED -> TRIGGERED -> EXHAUSTED`, with explicit invalidation paths.
- Lifecycle `TRIGGERED` **does not mean** `ENTRY_READY`.
- Persistent state is held in the managed SQLite data store and migration-owned schema.
- The main UI is the `Decision Terminal`; research surfaces remain secondary and non-actionable.
- Production evidence and feature-equivalent replay are observational/scientific evidence paths, not decision-authority paths.

## Visual legend

- **Solid arrows**: authoritative runtime/data/control flow.
- **Dashed arrows**: optional, advisory, research-only, or separate-authority relationships.
- Labels such as `OBSERVATIONAL`, `RESEARCH_ONLY`, `DOWNSTREAM_ONLY`, and `SEPARATE APPROVAL` carry meaning independently of color.
- A missing or stale evidence source is represented as unavailable/blocking evidence according to the owning contract; it is never shown as bullish or bearish evidence.

## Safety boundary

`LIVE_TRADING_ENABLED=false` is mandatory. These diagrams describe a signal/research system and must not be interpreted as an order-placement architecture. No diagram in this suite authorizes or depicts exchange order placement or cancellation.

## Freshness contract

Every diagram records the source baseline used to reconcile it. Before calling the suite current, compare the listed baseline with current `main` and inspect intervening changes touching architecture, EntryDecision/lifecycle semantics, schema, dashboard/SSE, notification, scientific validation, observability, or release/deployment boundaries. Stale diagrams must be updated rather than silently treated as current.
