# WaterfallHunter Architecture Diagram Suite — Design

Date: 2026-08-31

Source repository: `cavack/wfh`

Source baseline: `main@65c063ffea6209ecd84b224656bbc627ff811898`

Design branch: `docs/architecture-diagram-suite-20260831`

Status: DESIGN APPROVED IN CHAT / IMPLEMENTATION NOT YET STARTED

## 1. Purpose

Create a maintainable, source-bound architecture diagram suite for WaterfallHunter that explains the system from product boundary to runtime topology, canonical decision semantics, persistence, observability, scientific validation, and release certification.

The suite is documentation-only. It must improve system comprehension without changing application behavior, market logic, thresholds, persistence semantics, notification ordering, deployment policy, or Production state.

## 2. Authoritative sources

The implementation must be grounded in the exact repository state named above and re-check `main` before finalization. Older audit findings are context only when they still match current source/runtime evidence.

Primary source-of-truth documents and code areas:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/DECISION_ENGINE.md`
- `docs/DASHBOARD.md`
- `docs/MODEL.md`
- `docs/OPERATIONS.md`
- `docs/strict-scientific-validation.md`
- `docs/feature-equivalent-replay.md`
- `docs/operational-historical-outcomes.md`
- `backend/src/waterfallhunter/`
- `backend/src/waterfallhunter/migrations/`
- `frontend/`
- `watchdog/`
- `deploy/`
- `scripts/`
- `.github/workflows/`
- `skills/waterfallhunter/`

Repository-local engineering routing remains authoritative:

`engineering-orchestrator -> repository-architecture-auditor -> relevant domain specialists -> verification-regression`

## 3. Read-only Production reconciliation

A read-only runtime check was performed before this design was written.

Observed Production facts at design time:

- host: `srv8643113472`
- application path: `/srv/waterfallhunter/app`
- deployed repository SHA: `65c063ffea6209ecd84b224656bbc627ff811898`
- repository checkout state: detached HEAD on the exact SHA above
- backend container: running and healthy
- frontend container: running and healthy
- watchdog: running and healthy
- Prometheus: running and healthy
- Grafana: running and healthy
- Alertmanager: running and healthy
- nginx: active
- `LIVE_TRADING_ENABLED=false`
- `LBANK_EXECUTION_SHADOW_ENABLED=true`

These observations are runtime evidence only. They do not authorize Production mutation and must not be converted into a production-readiness claim.

## 4. Protected invariants

The diagram work must not change or reinterpret these boundaries:

- `SIGNAL_ONLY` product policy;
- `LIVE_TRADING_ENABLED=false` mandatory runtime invariant;
- no order placement or cancellation;
- ScoreV2 weights and evidence semantics;
- canonical decision thresholds or readiness policy;
- lifecycle transition semantics;
- strict/experimental eligibility boundaries;
- anti-chase semantics;
- immutable signal/decision provenance;
- persistence-before-notification ordering;
- scientific holdout/walk-forward rules;
- production execution policy;
- missing market data remains unavailable evidence, never bearish/bullish evidence;
- frontend must not invent or duplicate canonical backend decision/ranking logic.

## 5. Canonical semantic distinctions the diagrams must make explicit

### 5.1 EntryDecision versus lifecycle

Public entry states:

`NO_TRADE | FORMING | ENTRY_READY | ACTIVE | LATE | INVALIDATED | EXPIRED | UNAVAILABLE`

Only `ENTRY_READY` is a proactive signal state.

Lifecycle context:

`WATCH -> FUEL-RICH -> PRE-TRIGGER -> ARMED -> TRIGGERED -> EXHAUSTED`

with an invalidation path to `INVALIDATED`.

Lifecycle `TRIGGERED` must never be visually equated with `ENTRY_READY`.

### 5.2 Evidence versus actionability

Research scores, lifecycle labels, replay results, execution observations, historical outcomes, and AI advisory are evidence surfaces. They cannot silently become actionable entry commands.

### 5.3 Persistence and notification

Canonical decision/event persistence occurs before notification delivery. Telegram is downstream notification transport and cannot define the decision.

### 5.4 Scientific boundary

Replay, historical outcomes, calibration, walk-forward, holdout, and promotion evidence are research/validation paths. They do not auto-promote a strategy or authorize Production changes.

## 6. Diagram inventory

The implementation will create seventeen primary diagrams.

### D01 — System Context / Big Picture

Purpose: show users, public edge, application services, data providers, persistence, notifications, advisory providers, and observability in one readable system-level view.

Primary notation: Mermaid flowchart.

### D02 — Runtime Deployment Topology

Purpose: show the actual host/runtime shape: nginx, Docker Compose, frontend, backend, watchdog, Prometheus, Grafana, Alertmanager, internal networks, persistent volume, and loopback/public boundaries.

Primary notation: Mermaid flowchart with deployment-style subgraphs.

### D03 — End-to-End Data Pipeline

Purpose: show the full data path:

`market discovery -> normalization -> evidence packet -> cascade intelligence -> canonical entry decision -> persistence -> API/SSE -> Decision Terminal`.

Primary notation: Mermaid flowchart.

### D04 — Canonical Decision Flow

Purpose: show freshness, contract identity, evidence completeness, hard invalidators, anti-chase, timing/direction/execution checks, weighted readiness, and final EntryDecision.

Primary notation: Mermaid flowchart.

### D05 — Lifecycle State Machine

Purpose: show lifecycle context independently from entry actionability.

Primary notation: Mermaid state diagram.

### D06 — EntryDecision State Machine

Purpose: show canonical user-facing decision states and explicit post-entry transitions.

Primary notation: Mermaid state diagram.

### D07 — Evidence Architecture

Purpose: show evidence families and how they converge into the canonical evidence/decision path while preserving mandatory/optional and unavailable semantics.

Evidence families include market identity, structure/timing, derivatives, aggressive flow, liquidation/cascade, liquidity/execution, cross-exchange, regime, relative weakness, and freshness/provenance.

Primary notation: Mermaid flowchart.

### D08 — Entry Decision Transaction Sequence

Purpose: show symbol evaluation through deterministic decision, metadata/provenance validation, atomic persistence, immutable event creation, downstream outbox, advisory, and dashboard exposure.

Primary notation: Mermaid sequence diagram.

### D09 — TradePlan / TP-SL / Leverage Flow

Purpose: show observational/canonical calculation flow, venue constraints, feasibility, conservative risk geometry, leverage recommendation, and fail-closed unavailable branches.

No live-order execution node is permitted.

Primary notation: Mermaid flowchart.

### D10 — Persistence / Database ERD

Purpose: show domain-critical persistent entities and relationships without turning the diagram into a dump of every SQLite table.

At minimum, reconcile the current migration chain through:

- `0001_db_readiness_probe.sql`
- `0002_runtime_schema_baseline.sql`
- `0003_signal_metadata.sql`
- `0004_signal_decision_outbox.sql`
- `0005_lifecycle_v2_shadow.sql`
- `0006_entry_decisions.sql`
- `0007_entry_decision_advisories.sql`

Primary notation: Mermaid ER diagram.

### D11 — Dashboard / API / SSE Architecture

Purpose: show browser -> Next.js -> FastAPI transport, polling/bootstrap, SSE stream/replay, canonical dashboard snapshot, and lazy-loaded research endpoints.

Primary notation: Mermaid sequence or flowchart, whichever is clearer after source inspection.

### D12 — Notification Delivery Architecture

Purpose: show immutable canonical event -> durable outbox -> lease/retry/rate-limit/dead-letter/cutover logic -> Telegram notification.

Primary notation: Mermaid sequence diagram.

### D13 — Replay / Historical Outcomes / Scientific Validation

Purpose: show production evidence, feature-equivalent replay, imported/natural outcomes, strict cohort formation, calibration, walk-forward, untouched holdout, report/model-card evidence, and explicit promotion boundary.

Primary notation: Mermaid flowchart.

### D14 — Observability and Incident Flow

Purpose: show application metrics/health -> Prometheus -> Grafana/Alertmanager -> watchdog/operator/recovery path, including separation between observability and decision semantics.

Primary notation: Mermaid flowchart.

### D15 — CI / Release / Production Certification

Purpose: show exact-SHA source -> CI/test gates -> immutable image/artifact -> review -> backup/migration preflight -> guarded deploy -> health/runtime verification -> rollback/certification boundary.

Primary notation: Mermaid flowchart.

The diagram must make clear that CI success alone is not Production verification.

### D16 — Repository / Module Responsibility Map

Purpose: show ownership and dependency direction across backend, frontend, watchdog, deploy, scripts, research/docs, migrations, tests, and repository-local engineering skills.

Primary notation: Mermaid flowchart.

### D17 — Master Architecture Map

Purpose: provide one compact layered map connecting the preceding sixteen views without reproducing every detail. It is an index diagram, not a mega-chart containing every node.

Primary notation: Mermaid flowchart.

## 7. Repository layout

Proposed documentation layout:

```text
docs/
  diagrams/
    README.md
    01-system-context.md
    02-runtime-deployment-topology.md
    03-end-to-end-data-pipeline.md
    04-canonical-decision-flow.md
    05-lifecycle-state-machine.md
    06-entry-decision-state-machine.md
    07-evidence-architecture.md
    08-entry-decision-transaction-sequence.md
    09-tradeplan-risk-flow.md
    10-persistence-erd.md
    11-dashboard-api-sse.md
    12-notification-delivery.md
    13-scientific-validation.md
    14-observability-incident-flow.md
    15-ci-release-production-certification.md
    16-repository-responsibility-map.md
    17-master-architecture-map.md
```

Each file will contain:

1. title;
2. purpose;
3. source baseline SHA;
4. authoritative source references;
5. Mermaid source;
6. concise interpretation notes;
7. explicit safety/semantic caveats where relevant.

`docs/diagrams/README.md` will act as the navigational index and will group diagrams by concern rather than merely listing files.

Existing canonical docs will link to the diagram suite where useful. They will not be rewritten merely to duplicate diagram text.

## 8. Visual conventions

The suite must be visually consistent and readable on GitHub.

Conventions:

- left-to-right for pipeline/topology diagrams unless sequence/state notation naturally dictates otherwise;
- subgraphs for trust/runtime/domain boundaries;
- one semantic concept per node;
- short node labels, with detail moved to notes below the diagram;
- deterministic naming across diagrams (`EntryDecision`, `Lifecycle`, `Managed SQLite`, `Decision Terminal`, etc.);
- dashed edges for advisory/optional/non-authoritative paths;
- explicit labels for `SIGNAL_ONLY`, `OBSERVATIONAL`, `RESEARCH_ONLY`, or `UNAVAILABLE` boundaries when omission could mislead;
- no color-only semantics; meaning must also be encoded by labels/shapes/edge style for accessibility;
- avoid line-crossing and dense mega-graphs;
- no invented implementation layers that are not supported by source/runtime evidence.

## 9. Mermaid and visual-tool strategy

Canonical source in the repository will be Mermaid because it is diffable, reviewable, text-native, and renders in GitHub.

Mermaid Chart will be used to render/validate each canonical diagram interactively before completion.

A secondary visual/whiteboard representation may be created with B&A Diagrams for selected high-value overview diagrams, but it is not the source of truth.

The `hgraph Development` plugin is not currently exposed by the available tool surface, so the implementation must not claim to use it unless it becomes available later.

Remote Desktop Commander is used only for read-only reconciliation of Production topology/evidence unless a separate explicit Production authorization is given.

## 10. Source-bound freshness contract

Every diagram file must include the source baseline SHA used for its reconciliation.

Before final verification:

1. resolve current `main` again;
2. compare it with the design/implementation baseline;
3. inspect intervening commits relevant to architecture, contracts, runtime, schema, dashboard, observability, or release flows;
4. update diagrams if current source contradicts them;
5. never silently label a stale view as current.

## 11. Verification strategy

This is documentation-only, but completion still requires verification.

### Required checks

- every Mermaid diagram parses and renders successfully;
- every diagram's labels match current canonical terminology;
- lifecycle and EntryDecision remain visually distinct;
- only `ENTRY_READY` is shown as proactive actionability;
- no live-order execution path appears;
- persistence-before-notification ordering is preserved;
- missing/unavailable evidence is not shown as directional evidence;
- ERD relationships are grounded in current schema/migrations;
- dashboard diagrams do not duplicate backend decision logic;
- release diagram distinguishes CI, deploy, and Production verification states;
- links from the diagram index resolve;
- modified canonical docs remain internally consistent;
- `git diff --check` equivalent hygiene must pass on the exact final artifact;
- final diff must be reviewed for accidental semantic wording changes.

### Verification evidence

Completion report must list:

- exact final SHA;
- changed files;
- Mermaid validation result per diagram;
- link/documentation checks;
- any source area that could not be fully reconciled;
- explicit confirmation that runtime/source behavior was not modified.

## 12. Implementation sequence

Implementation will proceed in dependency order:

1. create diagram index and shared terminology/conventions;
2. system context and runtime topology;
3. data pipeline and evidence architecture;
4. lifecycle and EntryDecision state machines;
5. canonical decision and transaction sequence;
6. TradePlan/risk path;
7. persistence ERD;
8. dashboard/API/SSE and notification delivery;
9. scientific validation and observability;
10. CI/release/certification;
11. repository responsibility map;
12. master architecture map;
13. link selected existing canonical docs to the new suite;
14. render/validate all Mermaid diagrams;
15. re-resolve current `main`, reconcile drift, and run final documentation verification.

## 13. Acceptance criteria

The work is accepted when:

- all seventeen canonical diagrams exist under `docs/diagrams/`;
- each diagram is source-bound and independently understandable;
- all Mermaid diagrams render without syntax errors;
- diagrams use current terminology and match current source/runtime boundaries;
- the suite provides useful views at system, runtime, domain, state, sequence, persistence, observability, scientific, and release levels;
- no protected invariant or application behavior changes;
- no Production mutation occurs;
- the documentation index makes the suite easy to navigate;
- final verification is tied to the exact final repository artifact.

## 14. Non-goals

This work does not:

- redesign the trading strategy;
- optimize thresholds or weights;
- change ScoreV2, lifecycle, anti-chase, EntryDecision, TradePlan, leverage, or eligibility semantics;
- add a live trading/order path;
- migrate the database;
- change Docker/Production topology;
- refactor `main.py` or runtime code;
- repair unrelated repository debt;
- declare deployment or Production readiness.

## 15. Design review result

This specification intentionally favors multiple focused diagrams over one oversized graph. The source of truth remains current GitHub code/contracts; Production inspection is supporting runtime evidence only. Mermaid files are canonical; secondary visual tools are optional presentation surfaces.
