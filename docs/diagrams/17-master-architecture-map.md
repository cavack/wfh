# D17 — Master Architecture Map

Source baseline: `main@65c063ffea6209ecd84b224656bbc627ff811898`

## Purpose

Provide one compact navigation map across WaterfallHunter's major concerns. This diagram intentionally links layers rather than reproducing all details from D01-D16.

```mermaid
flowchart LR
    Inputs[Market / provider inputs]
    Evidence[Canonical evidence pipeline]
    Decision[Canonical EntryDecision]
    Persistence[Durable / immutable persistence]
    Product[Decision Terminal + downstream notifications]
    Research[Replay + outcomes + scientific validation]
    Ops[Observability + bounded operations]
    Governance[Scientific promotion boundary]
    Release[CI + release + Production certification]

    Inputs --> Evidence --> Decision --> Persistence --> Product
    Persistence --> Research
    Product --> Ops
    Research --> Governance
    Governance -. separate approval and release authority .-> Release
    Release -. deploys verified artifacts; does not redefine decisions .-> Ops
```

## Focused views by layer

| Concern | Focused diagrams |
| --- | --- |
| System boundary and runtime | [D01](01-system-context.md), [D02](02-runtime-deployment-topology.md), [D16](16-repository-responsibility-map.md) |
| Market-to-product pipeline | [D03](03-end-to-end-data-pipeline.md), [D07](07-evidence-architecture.md) |
| Decision semantics | [D04](04-canonical-decision-flow.md), [D05](05-lifecycle-state-machine.md), [D06](06-entry-decision-state-machine.md) |
| Decision persistence and risk geometry | [D08](08-entry-decision-transaction-sequence.md), [D09](09-tradeplan-risk-flow.md), [D10](10-persistence-erd.md) |
| Product delivery | [D11](11-dashboard-api-sse.md), [D12](12-notification-delivery.md) |
| Research and promotion evidence | [D13](13-scientific-validation.md) |
| Operations and incidents | [D14](14-observability-incident-flow.md) |
| Release and Production authority | [D15](15-ci-release-production-certification.md) |

## Reading order

For a new engineer, start with D01 → D03 → D04/D05/D06 → D08/D10 → D11/D12 → D13 → D14/D15. Use D16 when locating source ownership.

## Core boundary

Only `ENTRY_READY` is a proactive signal. Lifecycle, research, observability, AI advisory, and release state are separate concerns and cannot silently become entry authority. WaterfallHunter remains `SIGNAL_ONLY`; this master map contains no order-execution path.
