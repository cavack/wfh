# WaterfallHunter Engineering Skill System

Repository-local engineering skills for `cavack/wfh`. The system has one orchestrator and twelve specialists. It is designed to keep repository evidence fresh, separate model/scientific/release concerns, and prevent incidental changes to WaterfallHunter decision semantics.

## Skill index

| Skill | Primary trigger example |
|---|---|
| `engineering-orchestrator` | "Audit and fix this WaterfallHunter issue end-to-end." |
| `repository-architecture-auditor` | "Review repository structure, coupling, dead code, or architecture debt." |
| `runtime-reliability-performance` | "Investigate OOM, SSE memory, concurrency, latency, or soak regressions." |
| `backend-data-architecture` | "Refactor FastAPI/services/workers/SQLite/migrations or assess scale design." |
| `api-contract-schema-guardian` | "Change or validate API/Pydantic/OpenAPI/SSE/dashboard contracts." |
| `frontend-dashboard-ux` | "Improve Next.js dashboard behavior, UX, mobile, accessibility, or render performance." |
| `strategy-score-lifecycle` | "Change or audit ScoreV2, lifecycle, anti-chase, ranking, leverage, or eligibility." |
| `scientific-backtest-validation` | "Evaluate backtests, holdout, walk-forward, leakage, robustness, or promotion evidence." |
| `market-data-evidence-quality` | "Validate exchange data, freshness, timestamps, derivatives, order book, or cross-exchange evidence." |
| `verification-regression` | "Prove this bugfix/refactor/feature is complete without regressions." |
| `security-supply-chain` | "Review vulnerabilities, dependencies, secrets, containers, SBOM, GitHub security, or abuse surfaces." |
| `observability-incident-response` | "Investigate an incident or improve metrics, alerts, tracing, logging, or SLOs." |
| `release-production-certification` | "Prepare or certify merge, migration, deployment, rollback, or production verification." |

## Shared evidence taxonomy

Repository-grounded conclusions use these labels when material:

- `VERIFIED_FACT` — directly established from current source/runtime evidence.
- `REPRODUCED_DEFECT` — behavior reproduced or otherwise demonstrated with concrete failing evidence.
- `INFERENCE` — reasoned conclusion not yet directly reproduced.
- `DEBT` — maintainability/architecture/quality weakness without demonstrated correctness failure.
- `PROPOSAL` — recommended change not yet implemented/validated.

## Freshness rule

Before trusting a prior audit, bug report, issue, or design-time observation, resolve the current target branch/SHA and inspect relevant open PRs, issues, and recent commits. Historical findings are context, not permanent truth.

## Protected invariants

Infrastructure, UX, performance, refactor, observability, security, and release work must not silently change:

- ScoreV2 weights or evidence semantics;
- lifecycle transition semantics;
- strict/experimental eligibility boundaries;
- anti-chase behavior;
- signal metadata/provenance and immutable-ledger behavior;
- persistence-before-notification ordering;
- scientific holdout/walk-forward rules;
- production execution policy.

A required change to these boundaries is explicitly routed through `strategy-score-lifecycle` and, for promotion/evidence claims, `scientific-backtest-validation`.

## Routing examples

### Runtime bug

`engineering-orchestrator` → `runtime-reliability-performance` → `verification-regression` → `observability-incident-response` when runtime evidence is involved → `release-production-certification` if the change reaches deployment.

### Frontend/dashboard bug

`engineering-orchestrator` → `api-contract-schema-guardian` when payload semantics are involved → `frontend-dashboard-ux` → `verification-regression`.

### Strategy/model change

`engineering-orchestrator` → `market-data-evidence-quality` → `strategy-score-lifecycle` → `scientific-backtest-validation` → `verification-regression` → `release-production-certification`.

### Refactor

`engineering-orchestrator` → `repository-architecture-auditor` → `backend-data-architecture` or `frontend-dashboard-ux` → `api-contract-schema-guardian` when interfaces are affected → `verification-regression`.

### Production incident

`engineering-orchestrator` → `observability-incident-response` → indicated runtime/backend/frontend specialist → `verification-regression` → `release-production-certification`.

## Readiness ownership

The system uses:

`NOT_READY` → `ANALYSIS_COMPLETE` → `CODE_READY` → `MERGE_READY` → `DEPLOY_READY` → `DEPLOYED_UNVERIFIED` → `PRODUCTION_VERIFIED`.

Only `release-production-certification` may declare the final three production states. Passing a targeted test or CI alone never equals production verification.

## External tools and plugins

External tools are optional evidence/capability sources, not hard dependencies:

- GitHub is preferred for repository/PR/CI truth when connected.
- CodeRabbit, Sonar/CodeQL, Sentry, Prometheus/Grafana, Linear, StrategyTune and similar tools may strengthen specialist evidence when available.
- Firecrawl, Parallel Search and web research are for external documentation/research, not substitutes for repository evidence.
- Skillquiver/Duende-style libraries may inform skill-authoring patterns but are not required to run WaterfallHunter logic.
- GeoAI-style skills are outside the core system unless a concrete geospatial or infrastructure-latency requirement exists.

Unavailable plugins must not block core repository work.

## Behavioral validation

See `tests/README.md` and `tests/scenarios.md`. Every skill is pressure-tested RED/GREEN with a fresh conversation/context in addition to repository-local static validation.

## Safety boundary

This skill system does not by itself authorize live-order execution, model-threshold changes, Telegram delivery-policy changes, production migrations, merges, or deployments. Those actions require the user request plus the relevant specialist/release gates.
