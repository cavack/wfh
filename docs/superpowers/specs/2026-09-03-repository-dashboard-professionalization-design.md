# WaterfallHunter Repository & Dashboard Professionalization Design

Status: APPROVED IN CHAT FOR SPEC AUTHORING
Date: 2026-09-03
Target repository: `cavack/wfh`
Design baseline: `209fff11e434dda58d3e380f181f23a111813cc2`
Primary implementation dependency: reconcile current PR #117 before overlapping dashboard/runtime edits.

## 1. Goal

Standardize WaterfallHunter into a maintainable, institutional-grade research/decision platform without changing protected strategy or execution semantics.

The design covers two coupled surfaces:

1. repository/backend architecture and ownership boundaries;
2. the operator dashboard and its information architecture.

The target UI is English-first, dark institutional trading-terminal style. The frontend must establish locale and logical-layout foundations so future i18n/RTL work does not require a structural rewrite, but this project does not add a language selector or Persian UI.

## 2. Non-negotiable invariants

The implementation must preserve all of the following unless separately authorized through their owning skills:

- `LIVE_TRADING_ENABLED=false`; no live order placement path;
- ScoreV2 weights, evidence semantics, and score interpretation;
- lifecycle state semantics and transition ownership;
- `ENTRY_READY` remains the only proactively actionable decision state;
- `TRIGGERED != ENTRY_READY` and ACTIVE/FORMING/LATE remain non-entry states;
- Anti-Chase semantics and thresholds;
- strict/experimental eligibility boundaries;
- canonical decision provenance and immutable ledgers;
- persistence-before-notification ordering;
- scientific holdout, walk-forward, embargo, and promotion rules;
- missing market evidence remains `UNAVAILABLE`, never directional evidence;
- frontend must not duplicate backend ranking, scoring, eligibility, leverage, or trade-plan decision logic.

## 3. Evidence classification for this design

`VERIFIED_FACT`: current `main` is `209fff11...`, branch protection is enabled, and current required CI contexts include backend, frontend, dependency audit, container validation, and repository hygiene.

`VERIFIED_FACT`: Production source remains on an older runtime SHA than this documentation baseline; this design does not deploy anything.

`VERIFIED_FACT`: `backend/src/waterfallhunter/main.py` is currently a multi-responsibility composition/orchestration module exceeding four thousand lines.

`DEBT`: that concentration makes ownership, test isolation, startup/shutdown reasoning, and future changes harder. File size alone is not treated as a correctness defect.

`VERIFIED_FACT`: PR #117 contains current dashboard/runtime fixes for bounded projection, stream freshness semantics, reconnect behavior, partial microstructure reuse, and decision-terminal presentation.

`PROPOSAL`: use a phased strangler refactor rather than a repository rewrite.

## 4. Architectural strategy

The system will evolve by moving responsibilities behind explicit seams while preserving current behavior at each step.

No large-bang replacement of `main.py`, database, scanner, or dashboard transport is allowed.

Target backend structure:

```text
backend/src/waterfallhunter/
  app/
    factory.py
    lifespan.py
    dependencies.py
  api/
    dashboard.py
    health.py
    metrics.py
    research.py
    backtest.py
  domain/
    scoring/
    lifecycle/
    decision/
    execution/
  services/
    hunter.py
    dashboard.py
    settlement.py
    replay.py
    notification.py
  repositories/
    candidates.py
    signals.py
    outcomes.py
    execution.py
  adapters/
    exchanges/
    telegram.py
    advisory.py
  observability/
    metrics.py
    logging.py
    health.py
  compatibility/
    legacy_runtime.py
```

The actual implementation must follow existing module ownership and may use transitional aliases where moving a symbol in one step would create unsafe churn. Compatibility modules are temporary migration seams, not a permanent second architecture.

## 5. Backend ownership rules

`app/` owns application construction, dependency wiring, lifespan, and task supervision. It must not own market or model semantics.

`api/` owns HTTP/SSE transport and validation only. Route handlers should delegate bounded use-cases rather than build large reports or perform multi-stage orchestration inline.

`domain/` owns pure or near-pure business semantics. Existing canonical score, lifecycle, decision, execution, anti-chase, and validation implementations remain authoritative during extraction.

`services/` owns orchestration use-cases and long-lived domain workflows. A service may coordinate repositories/adapters but must not silently create a second persistence or scoring model.

`repositories/` owns managed data-access boundaries and transaction-facing persistence primitives. SQLite remains the primary store until measured coordination or durability evidence justifies a separately approved migration.

`adapters/` owns external systems and providers. Exchange, Telegram, AI/advisory and similar integrations must be isolated from canonical domain decision logic.

`observability/` owns structured operational signals and must not become a dependency for model decisions.

## 6. Runtime and process model

The current single-runtime/single-writer operating assumption remains explicit. This project does not introduce multiple backend replicas, PostgreSQL, Redis, NATS, or a queue merely for architectural fashion.

Long-lived workers must have one clear owner, deterministic startup order, bounded shutdown, and direct health/last-success telemetry. Moving code out of `main.py` must preserve worker ordering and fail-closed startup behavior.

The target composition root should make these responsibilities visible:

```text
create_app()
  -> build_dependencies()
  -> register_api()
  -> lifespan()
       -> schema/readiness gates
       -> start supervised workers
       -> serve API/SSE
       -> bounded shutdown
```

Runtime work must remain compatible with the existing Docker Compose, systemd oneshot bootstrap, container `restart: unless-stopped`, and health-recovery timer model unless a separate runtime design proves a change is required.

## 7. API and contract architecture

The backend is the canonical producer of decision, rank/order, eligibility, readiness, evidence coverage, leverage advisory, trade-plan availability, and unavailable-state semantics.

Important nested dashboard structures must become explicitly typed instead of relying indefinitely on broad `Record<string, unknown>` / JSON extension bags.

Generated TypeScript contracts must be derived from canonical backend schemas where tooling permits. CI must detect stale generated artifacts.

SSE and polling must expose semantically equivalent business snapshots/events. Transport metadata may differ, but a consumer must not derive a different decision because it arrived over SSE rather than polling.

Contract evolution must distinguish cosmetic additions from semantic breaks. Semantic breaks require an explicit version or migration bridge.

PR #117's bounded public dashboard projection is treated as the intended direction and must be reconciled before overlapping contract work proceeds.

## 8. Frontend application architecture

Target frontend structure:

```text
frontend/
  app/
    layout.tsx
    page.tsx
  components/
    shell/
    terminal/
    candidates/
    research/
    operations/
    shared/
  lib/
    api/
    state/
    format/
    locale/
    accessibility/
  generated/
    dashboard-contract.ts
  tests/
  e2e/
```

The frontend should use normalized/selective state where live data volume justifies it. A lightweight reducer or `useSyncExternalStore`-style store is preferred over introducing a large state framework without evidence.

Transport state and data state are separate concepts. An open socket does not by itself mean fresh live data.

Canonical ordering must be consumed from backend-produced rank/order/display fields. The frontend must not recreate Watch Score, FinalRanking, coverage adjustments, entry readiness, leverage, or eligibility formulas.

The existing `app/dashboard/page.tsx` alias must be reviewed after the shell/navigation refactor. If `basePath='/dashboard'` makes it redundant, remove it with routing regression coverage rather than maintaining duplicate conceptual routes.

## 9. Dashboard information architecture

The product becomes four explicit workspaces instead of one long mixed-purpose page.

### Decision

The default landing workspace answers three questions quickly: what matters now, why, and how reliable is the evidence.

It contains:

- global health/freshness/signal-only header;
- ENTRY READY / FORMING / ACTIVE / BLOCKED-LATE KPIs;
- zero-entry diagnostics when relevant;
- prioritized canonical decision cards;
- current trade-plan/reference-plan presentation with explicit actionability labels;
- concise evidence summary and blocking reasons;
- recent canonical decision transitions.

`ENTRY_READY` is the only visually actionable state. FORMING, ACTIVE, LATE, INVALIDATED, EXPIRED, NO_TRADE, and UNAVAILABLE must never look like equivalent entry signals.

### Candidates

The Candidates workspace provides dense operator scanning without exposing raw internal payloads by default:

- server-canonical ordering;
- symbol search;
- decision/state filters;
- freshness and evidence availability;
- readiness/coverage display;
- bounded evidence columns;
- row inspection/drill-down;
- pagination or virtualization when row volume warrants it.

### Research & Lab

Historical outcomes, Backtest Lab, scientific validation, feature replay, lifecycle shadow, production evidence and other research surfaces move here. Research output is explicitly observational/non-promotional unless the canonical scientific workflow says otherwise.

### Operations

Operations exposes system/runtime state rather than model conclusions:

- API latency and error rate;
- SSE clients, payload size, queue/drop behavior, and reconnect state;
- backend RSS/CPU/restarts and runtime revision;
- hunter cycle/progress/backlog/freshness;
- provider latency/error/freshness;
- background worker running/last-success/failures;
- SQLite size/busy/query latency where instrumented;
- notification/outbox health;
- deployment SHA/image provenance and health transitions.

Operational degradation must be distinguishable from a legitimate market `NO_TRADE` result.

## 10. Visual system

The visual language is an institutional dark trading terminal, not a marketing dashboard.

Design rules:

- English UI only in this project;
- compact but readable information density;
- tabular numerals for prices, percentages, scores, and timestamps;
- one primary cyan/blue interaction accent;
- green/amber/orange/red reserved for semantic state meaning;
- slate surfaces with controlled elevation and minimal decorative gradients;
- spacing, border radius, typography and interactive states defined as reusable tokens/components;
- sticky global/status shell and workspace navigation;
- tables prioritize alignment, scanning and row-state clarity;
- no decorative animation that competes with changing market data;
- reduced-motion, visible keyboard focus, touch-safe controls and semantic HTML remain mandatory.

Responsive behavior uses mobile-first composition. Dense tables may horizontally scroll when necessary, but primary decision state must remain readable without requiring desktop width.

## 11. Locale and RTL foundation

Current product copy remains English. The implementation must nevertheless stop baking locale assumptions into formatting/layout primitives.

Foundation requirements:

- central locale constant/configuration;
- shared `Intl.NumberFormat` and `Intl.DateTimeFormat` helpers;
- document `lang` sourced from locale configuration;
- logical CSS properties preferred over directional left/right assumptions in new shared primitives;
- component APIs must not require English text measurement hacks;
- no language selector, translation catalog, or Persian copy is added in this project.

This is preparation only. Full i18n/RTL remains a separately scoped future feature.

## 12. Observability standard

Professionalization includes telemetry proportional to the runtime paths being refactored.

Priority metrics, where the corresponding path exists, include:

- HTTP request duration/status/in-flight by bounded route class;
- dashboard snapshot build duration and serialized size;
- SSE clients, queue depth/drop/coalescing counters;
- hunter progress age/cycle duration/backlog;
- provider latency, failures and freshness;
- background worker running/failure/last-success;
- backend RSS and restart correlation to release SHA;
- expensive report build latency and coalescing/cache behavior where applicable;
- managed SQLite busy/lock/query-duration and database size where practical.

Metrics must remain bounded-cardinality. Symbol identifiers must not be indiscriminately attached to high-frequency metric labels.

Grafana must evolve from simple up/down presentation toward Runtime, API, Dashboard/SSE, Hunter, Providers, Data/Persistence and Release views. Alerts must be tied to actionable degradation rather than dashboard decoration.

## 13. Security and repository standards

The current repository governance baseline remains intact: protected `main`, required CI, CODEOWNERS, security policy, issue/PR templates, Dependabot configuration and private vulnerability reporting.

Architecture work must preserve existing container hardening and exact-artifact deployment controls. Repository restructuring is not permission to loosen read-only filesystems, non-root execution, capability drops, revision pinning, dependency locks, secret hygiene, or manual Production authorization.

Where new public-facing dashboard/API paths are introduced, apply existing same-origin proxy and bounded-response principles. Any new expensive report endpoint requires explicit size/concurrency/abuse analysis.

Supply-chain improvements such as SBOM generation, image vulnerability scanning or signing may be added as separate reviewable tasks, but they must not be mixed into semantic model changes.

## 14. Delivery sequence

The implementation is intentionally staged so each phase can be reviewed and reverted independently.

### Phase 0 — Reconcile active work

- reconcile PR #117 against current `main`;
- preserve its verified runtime/dashboard correctness improvements;
- resolve overlapping stale PRs/issues rather than copying their implementations;
- establish exact implementation base SHA.

### Phase 1 — Frontend shell and information architecture

Create the four-workspace shell, move existing surfaces without semantic changes, establish shared layout/status primitives, and preserve current contract behavior.

### Phase 2 — Canonical contract strengthening

Replace important nested unknown bags with explicit backend-owned contract types and generated frontend types. Publish canonical ordering/display fields where the frontend currently has to infer ordering.

### Phase 3 — Dashboard state/rendering boundaries

Separate transport/freshness state, normalize candidate updates where beneficial, minimize rerender scope, and preserve bounded SSE/poll behavior.

### Phase 4 — Backend composition seams

Introduce application factory/dependency/lifespan boundaries and move bounded route/service responsibilities out of `main.py` without changing worker or decision semantics.

### Phase 5 — Service/repository/adapters extraction

Move orchestration and persistence behind explicit ownership seams only where the previous phases expose a clear boundary. Avoid a mechanical file split that merely relocates complexity.

### Phase 6 — Operations workspace and telemetry

Expose bounded operational health derived from canonical metrics/runtime evidence. Expand Grafana/alerts in parallel with the code paths that now emit meaningful telemetry.

### Phase 7 — Hardening and cleanup

Remove verified-dead compatibility aliases, redundant dashboard routing, stale docs/issues, and temporary migration seams only after consumers and tests prove they are no longer required.

## 15. Verification strategy

Every code-affecting phase must follow regression-first verification proportional to its blast radius.

Minimum repository gates for relevant phases:

- focused RED/GREEN tests for changed behavior;
- full backend pytest on the exact candidate SHA when backend/runtime semantics are touched;
- frontend contract/unit tests;
- TypeScript typecheck;
- Next.js production build;
- Playwright built-app E2E for Decision, Candidates, Research, Operations, stream/fallback and mobile paths;
- accessibility checks for primary workspaces, including keyboard/focus and reduced-motion behavior;
- repository hygiene and secret-pattern checks;
- dependency audit;
- container validation/runtime parity when runtime/build artifacts change;
- `git diff --check`;
- exact-head CI and independent review before merge.

For realtime/performance changes, add targeted concurrency/load/soak evidence rather than inferring success from unit tests.

Visual changes require stable screenshot baselines at representative desktop, tablet and mobile widths once the new shell stabilizes. Visual screenshots are verification artifacts, not substitutes for semantic assertions.

## 16. Acceptance criteria

The professionalization project is complete only when all of the following are true on the exact final implementation artifact:

- repository responsibilities are documented and reflected by code ownership boundaries;
- `main.py` is reduced to composition/orchestration responsibilities with migrated responsibilities owned elsewhere;
- worker lifecycle/startup/shutdown semantics remain regression-proven;
- canonical backend contracts own ranking/order/eligibility/readiness semantics;
- frontend contains no duplicated canonical decision formula;
- Decision, Candidates, Research & Lab, and Operations are distinct navigable workspaces;
- ENTRY READY is visually and semantically the only actionable state;
- missing evidence and system degradation remain distinguishable from market rejection;
- transport connection and data freshness are separate user-visible concepts;
- dashboard works at desktop/tablet/mobile widths without page-level horizontal overflow on primary decision flows;
- keyboard navigation, visible focus and reduced-motion behavior are verified;
- locale/format/layout primitives permit future RTL/i18n without changing domain contracts;
- observability covers the runtime paths materially changed by the project;
- required tests, E2E, audits, container/runtime checks and exact-head CI are green;
- no live trading or order placement is introduced or enabled.

Completion of repository/CI work does not itself establish Production state. Any deploy or `PRODUCTION_VERIFIED` claim remains exclusively subject to release-production-certification.

## 17. Explicitly out of scope

This project does not:

- recalibrate ScoreV2, Entry Readiness, Anti-Chase, lifecycle or leverage;
- change SHORT/ENTRY_READY strategy semantics;
- add live order execution;
- migrate SQLite to PostgreSQL;
- introduce Redis/NATS/Kafka or multi-replica backend architecture;
- replace the current deployment topology solely for modernization;
- add Persian translations or a language selector;
- turn AI advisory into a decision authority;
- make profitability or promotion claims from UI changes.

## 18. Primary risks and controls

Risk: broad refactoring hides semantic drift. Control: phased extraction, canonical regression tests, Golden/model replay where affected, and exact diff review.

Risk: frontend redesign accidentally creates a second ranking model. Control: backend-owned canonical ordering/display contracts and explicit consumer tests.

Risk: PR #117 overlap causes regressions or duplicated fixes. Control: reconcile it before implementation and treat its current verified fixes as input, not backlog text.

Risk: splitting files without reducing coupling. Control: move responsibilities only behind explicit interfaces and delete compatibility seams after consumer migration.

Risk: visually attractive but operationally misleading UI. Control: evidence-first hierarchy, unavailable/degraded states, and ENTRY_READY-only actionability.

## 19. Implementation-plan decomposition

This design is implemented through multiple sequential, independently reviewable plans rather than one oversized implementation PR:

1. **Plan A — Active-work reconciliation + frontend shell**: reconcile PR #117, establish the four-workspace shell, shared visual primitives, routing, locale foundation, and accessibility/browser baselines.
2. **Plan B — Canonical contracts + frontend state**: strengthen nested backend-owned contracts, generated TypeScript, canonical display/order fields, transport/freshness separation, and selective live-state updates.
3. **Plan C — Backend composition + ownership seams**: application factory, dependencies/lifespan, bounded API extraction, service/repository/adapter seams, with worker-order regression coverage.
4. **Plan D — Operations + observability + cleanup**: Operations workspace, bounded telemetry/Grafana/alerts, removal of proven-dead compatibility/routing seams, and final cross-layer hardening.

Each plan must leave the repository in a working, testable state. A later plan may depend on interfaces from an earlier plan, but no plan may require an unreviewable all-at-once migration.

## 20. Design decision

Adopt the phased strangler architecture and four-workspace institutional dashboard described above. No implementation begins until this committed design is reviewed and approved, after which task-level TDD implementation plans will be written in the decomposition above.
