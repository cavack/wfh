# WaterfallHunter Unified Roadmap — Implementation Controller

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:executing-plans` or `superpowers:subagent-driven-development` task-by-task. Every code-affecting task uses TDD where practical and `verification-regression` before completion claims.

**Goal:** converge WaterfallHunter into a stable, high-recall-first, progressively calibrated SIGNAL_ONLY system with a professional institutional dashboard, clean repository/control plane, continuous paper evidence, and independently restorable DR.

**Architecture:** repair runtime correctness before model tuning; preserve canonical backend decision ownership; migrate architecture by strangler boundaries rather than rewrite; evaluate recall/balanced/precision model tiers in parallel shadow evidence before any promotion.

**Tech Stack:** Python/FastAPI/SQLite/asyncio, Next.js/React/TypeScript/Playwright, Docker Compose/systemd, Prometheus/Grafana/Alertmanager, GitHub Actions, private GitHub Release DR.

**Spec:** `docs/superpowers/specs/2026-09-03-waterfallhunter-unified-master-plan.md`

## Global Constraints

- `LIVE_TRADING_ENABLED=false`; no live order placement is designed or enabled.
- Missing market evidence remains `UNAVAILABLE`, never directional evidence.
- Frontend never duplicates canonical backend ranking/eligibility/scoring logic.
- Safety/data-integrity gates are not weakened to manufacture signal count.
- Model quality gates/weights may change only in versioned research/challenger profiles with scientific validation.
- Every phase ends with a senior re-check against current GitHub/runtime state.
- Only `release-production-certification` may declare production readiness states.
- Host cleanup is allowlist-only and must not touch system, VS Code/Insiders, SSH, unrelated Docker, or unrelated host data.
## Phase 0 — Control Plane & Continuity

**Exit condition:** current work is recoverable after interruption and no stale branch/worktree can masquerade as canonical state.

- [ ] Freeze current `main`, Production SHA, open PR/Issue inventory, dirty worktrees, and active release/DR references.
- [ ] Preserve unpublished dirty worktree changes before any cleanup.
- [ ] Reconcile PR #115 Mission Continuity against current `main`, current local unpublished diff, reviews, and exact-head CI.
- [ ] If #115 remains semantically valid, finish RED→GREEN review fixes, merge through protected `main`, and verify cold-resume behavior; otherwise preserve/close with evidence.
- [ ] Remove the stale local `main` ownership hazard only after confirming no unique work in `watch-fairness-20260902`.
- [ ] Commit and review the Unified Master Plan + this Roadmap as governance artifacts.

**Senior re-check:** re-fetch `main`, PR #115, worktree registry, dirty status, and mission-resume evidence from fresh processes. No application deploy is implied by this phase.

## Phase 1 — P0 Runtime & Dashboard Transport

**Exit condition:** PR #117 has no current unresolved correctness/performance review finding and is verified on its exact head.

- [ ] Reproduce each of the five current #117 review findings independently.
- [ ] Add RED regressions for stalled SSE→poll recovery, transition-query complexity, WS snapshot expiry during REST trade await, raw diagnostics freshness, and raw endpoint event-loop blocking.
- [ ] Apply one minimal root-cause fix per finding; no strategy/model semantics change.
- [ ] Rebase/reconcile #117 onto current `main` without duplicating PR #104.
- [ ] Run focused concurrency/contract/browser tests, full backend, frontend tests/typecheck/build/E2E, hygiene, runtime parity, container/artifact and security checks.
- [ ] Resolve only review threads proven fixed or technically invalid on the exact final head.
## Phase 2 — Production Freshness & Throughput Root Cause

**Exit condition:** the universe freshness SLO is attainable under measured CPU/memory limits; healthy status cannot hide stale-universe degradation.

- [ ] After Phase 1 release eligibility, deploy only through the guarded exact-artifact workflow and certify runtime identity.
- [ ] Measure per-stage p50/p95 evaluation latency, in-flight work, due backlog, REST/WS reuse, CPU, RSS slope, DB/API latency, and candidate-age distribution.
- [ ] Define explicit universe-freshness SLI/SLO and expose it through `/api/health`, Prometheus, Grafana, and Alertmanager.
- [ ] Trace expensive work amplification before changing concurrency; prefer causal reuse, coalescing, bounded caches, scheduling fairness, and partial evidence reuse.
- [ ] Tune concurrency only after a measured memory/CPU model proves headroom; never use memory-limit increases as the root-cause fix.
- [ ] Run load + soak long enough to cover multiple full-universe cycles and prove p95/max freshness behavior.

**Senior re-check:** independently sample Production candidate ages, backlog, service times, RSS/CPU and health semantics. If the 180s target is physically unattainable for the current universe, revise the scheduler/service-time architecture rather than mislabel stale data as healthy.

## Phase 3 — Institutional Dashboard Professionalization

**Exit condition:** English-first Decision Terminal is structurally separated into Decision, Candidates, Research & Lab, and Operations without semantic duplication.

- [ ] Build a root app shell with persistent validated transport state and English institutional navigation.
- [ ] Move Decision Terminal to canonical actionable/current evidence only; keep `ENTRY_READY` uniquely actionable.
- [ ] Build Candidates workspace with server-provided canonical ordering, filters/search, freshness and drill-down.
- [ ] Move Backtest/Replay/Outcome/Lifecycle/Raw diagnostics to Research & Lab with lazy/on-demand loading.
- [ ] Build Operations workspace for provider/worker/freshness/SSE/API/resource/revision/DR status.
- [ ] Add i18n/RTL-ready layout primitives without exposing a second language yet.
- [ ] Verify desktop/tablet/mobile, keyboard/focus/ARIA, reduced motion, loading/error/stale/offline states, network/parse/render cost, and Playwright flows.
## Phase 4 — Repository/Backend Architecture Strangler

**Exit condition:** `main.py` is no longer the dominant ownership boundary for unrelated concerns, while runtime/model behavior remains equivalent.

- [ ] Introduce app construction/lifespan/dependency seams around existing behavior rather than rewriting the service.
- [ ] Extract API route ownership by bounded domain: health/decision/dashboard/research/backtest/operations.
- [ ] Move orchestration use-cases into services and persistence queries into repositories only where ownership becomes clearer/testable.
- [ ] Keep exchanges/AI/Telegram as adapters behind explicit interfaces; do not duplicate domain semantics.
- [ ] Preserve SQLite as canonical storage unless measured coordination/locking evidence justifies a database migration.
- [ ] Migrate in independently reviewable slices with import/startup/task-shutdown/transaction/runtime-parity tests after each slice.

**Senior re-check:** compare golden decision outputs, lifecycle transitions, persistence hashes, API contracts, worker ownership and runtime task counts before/after each extraction.

## Phase 5 — Progressive Signal Ladder: Recall → Balanced → Precision

**Exit condition:** three versioned challenger profiles can be evaluated simultaneously from identical point-in-time evidence, with no automatic Production promotion.

- [ ] Keep safety-critical gates invariant: stale/invalid evidence, invalid lifecycle, extreme Anti-Chase, unusable execution, missing required trade-plan safety, corrupted provenance.
- [ ] Define `RECALL`, `BALANCED`, and `PRECISION` challenger profiles for quality thresholds/weights/confirmation topology only.
- [ ] Start RECALL with the broadest scientifically defensible quality acceptance and highest signal volume; do not count unavailable evidence as confirmation.
- [ ] Tighten monotonically through BALANCED to PRECISION so later tiers are explainable subsets or stricter decisions, not unrelated strategies.
- [ ] Persist tier decisions, rejected-by-next-tier reasons, score components, evidence coverage, trade/reference plans and outcomes side-by-side.
- [ ] Run purged/embargoed walk-forward development and untouched final evaluation with costs, PF, EV, MDD, MAE/MFE, late rate, FPR, signal/day, regime and symbol concentration.
- [ ] Prefer stable parameter plateaus; never tune the final holdout after observing it.
## Phase 6 — Continuous Paper Portfolio & Self-Improvement Evidence Loop

**Exit condition:** every canonical/challenger signal can be replayed in a bounded paper portfolio with durable outcomes and automated challenger analysis, without self-modifying Production policy.

- [ ] Define a configurable paper starting capital and deterministic risk/notional policy for research only.
- [ ] Consume persisted signal decisions only after persistence; model fills, fees, slippage, funding, partial fills, leverage constraints, liquidation and capacity from available evidence.
- [ ] Maintain continuous equity, drawdown, open/closed paper positions, outcome attribution and per-tier performance.
- [ ] Generate automated challenger reports identifying false positives, false negatives, gate contribution and threshold/weight sensitivity.
- [ ] Allow the system to propose versioned challenger configurations automatically, but require scientific validation and explicit promotion workflow before Production policy changes.
- [ ] Surface paper portfolio and challenger evidence in Research & Lab, clearly marked non-live/non-equivalent where appropriate.

**Senior re-check:** verify no code path can turn paper portfolio actions into real orders, no outcome leakage enters decision-time features, and all proposed changes are reproducible from immutable evidence.

## Phase 7 — AI Advisor & Telegram Productization

**Exit condition:** AI and messaging states are observable, bounded and semantically subordinate to deterministic decisions.

- [ ] Expose AI Advisor configured/model/reachable/latency/last-success/last-error/advisory-age metrics without logging secrets.
- [ ] Keep AI advisory unable to create, suppress or mutate canonical deterministic signals; persist advisory provenance separately.
- [ ] Display advisor state and advisory text in Decision/Research surfaces with unavailable/failure semantics.
- [ ] Reconcile interactive Telegram bot versus durable signal delivery; keep delivery default-off until separately authorized.
- [ ] Verify outbox persistence-before-notification, cutover boundary, retry/rate-limit/dead-letter behavior, and preview/test paths without sending unauthorized production signals.
- [ ] Document exact enablement preflight and rollback; no Telegram activation is implied by implementation completion.
## Phase 8 — Semantic Liveness, Observability & Bounded Recovery

**Exit condition:** degradation is detected before the dashboard becomes misleading, and recovery is bounded by cause-aware policy.

- [ ] Distinguish process liveness, endpoint readiness, hunter progress, universe freshness, provider health and signal-funnel health.
- [ ] Add SLOs/alerts for candidate-age p50/p95/max, backlog, evaluation latency, REST fallback ratio, SSE payload/connection health, DB/API latency, RSS slope and paper outcome worker lag.
- [ ] Extend existing bounded health recovery only for a demonstrated recoverable semantic-liveness failure; do not create a competing restart supervisor.
- [ ] Preserve three-failure/cooldown/recovery-budget safeguards or version them only with evidence.
- [ ] Build incident dashboard and release-SHA correlation sufficient to distinguish containment from root-cause closure.

## Phase 9 — Disaster Recovery Hardening (`cavack/wfh-dr`)

**Exit condition:** the latest Production backup is encrypted off-host, provenance-bound, independently restored, audited and tied to exact source/runtime identity.

- [ ] Keep `wfh-dr` private and separate from development source; no plaintext Production DB is committed or released.
- [ ] Extend backup manifest/certificate provenance to bind backup time, source/runtime revision, schema/audit identity and logical counts in addition to crypto/chunk hashes.
- [ ] Re-verify the latest Release by exact tag using the restore workflow and retain the restore-verification report.
- [ ] Preserve immutable Release assets and AES-256-GCM integrity; rotate secrets only if exposure evidence exists.
- [ ] Compensate for unavailable private-repo branch protection on the current GitHub plan with minimal DR code surface, explicit review/CI workflow, immutable releases and restore certification.
- [ ] Test restore-to-isolated-target and migration rehearsal without overwriting Production.

**Senior re-check:** download exact remote assets independently, verify digest/decrypt/SQLite integrity/schema/logical counts/provenance and confirm source/destination failure-domain separation.
## Phase 10 — GitHub & Host Hygiene

**Exit condition:** active work is obvious, historical state is preserved but no longer operationally noisy, and project-scoped disk/control-plane debt is reduced safely.

- [ ] Reconcile every open PR/Issue against current `main`; close only with evidence of merge/supersession/no-unique-work.
- [ ] Decide Dependabot PRs individually with compatibility/security evidence; do not mass-merge dependency updates.
- [ ] Remove remote branches only after PR disposition, unique-commit comparison, dirty-worktree check and release/DR reference check.
- [ ] Audit all workflows; remove/disable obsolete temporary/one-shot/patch workflows only after proving canonical replacements.
- [ ] Audit Actions retention, labels, environments, secrets-by-name/reference, releases, templates, topics and merge/protection settings.
- [ ] Generate a host cleanup manifest before deletion; preserve dirty work, current/rollback images, Production volumes, DR/research evidence and certification artifacts.
- [ ] Remove only classified WaterfallHunter worktrees/reproducible artifacts/project images; never use broad `docker system prune` or filesystem deletion under Docker internals.
- [ ] Never touch VS Code/VS Code Insiders, SSH, system directories, unrelated Docker workloads, Remote Desktop/Codex tooling or unrelated host files.

**Senior re-check:** verify GitHub inventory, current branches/worktrees, Docker/runtime health, rollback target, disk usage and all protected host paths after each cleanup batch.

## Phase 11 — Final Release & Production Certification

**Exit condition:** only the intended release revision is deployed and its behavior is verified under the appropriate soak.

- [ ] Reconcile exact final PR head with current `main`; require all relevant review threads resolved and exact-head CI/security/dependency evidence green.
- [ ] Require migration/backup/restore/rollback evidence when schema/data behavior changes.
- [ ] Deploy immutable CI-tested artifact/image digests only through explicit Production dispatch; normal `main` push must not deploy.
- [ ] Verify `/livez`, `/readyz`, `/healthz`, revision labels, dashboard/API/SSE, workers, universe freshness, AI/paper/Telegram states and SIGNAL_ONLY invariants.
- [ ] Hold risk-proportional runtime/memory/freshness soak and compare against pre-release baselines.
- [ ] Only then may `release-production-certification` declare `PRODUCTION_VERIFIED`.

## Execution Order

`0 → 1 → 2 → (3 || 4) → 5 → 6 → 7 → 8 → 9 → 10 → 11`

Phases 3 and 4 may interleave only when file ownership is non-overlapping; model work (Phase 5) does not begin promotion analysis until Phase 2 establishes trustworthy freshness. Hygiene deletion (Phase 10) is deliberately late, although read-only inventory/disposition analysis may run earlier.
