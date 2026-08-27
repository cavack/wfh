---
name: release-production-certification
description: Use when WaterfallHunter changes are being prepared for merge, migration, deployment, rollback, post-deploy verification, or any claim of deploy or production readiness.
---

# WFH Release, Migration & Production Certification

## Overview

Own the final evidence gates that distinguish code completion, merge readiness, deploy readiness, a deployed-but-unverified state, and verified production behavior.

## When to Use

Use for PR completion, exact-head review, migrations, backup/restore preflight, deployment, rollback, runtime health verification, or any request to certify a WaterfallHunter change for production.

## Scope

Own exact SHA/diff identity, CI status, backend/frontend/container verification, security/dependency gates, review threads, migration preflight, backup/restore evidence, artifact/image identity, rollback, deployment checks, health endpoints, runtime revision, smoke tests, and post-deploy soak/observability.

## Workflow

1. Resolve exact PR head/commit and compare it with current target branch; re-check whether new commits made earlier evidence stale.
2. Inspect final diff and ensure scope contains only authorized files/semantics.
3. Require proportional verification from `verification-regression` and inspect CI on the exact head.
4. Inspect available CodeRabbit/Sonar/CodeQL/security/dependency evidence and unresolved review threads when configured.
5. For migrations, verify backup/restore readiness, schema preflight, ordering, rollback/forward-fix plan, and data-volume continuity.
6. Verify immutable artifact/image digest and revision metadata.
7. Perform authorized deployment only when prerequisites are satisfied; preserve rollback target.
8. Check `/livez`, `/readyz`, `/healthz`, runtime revision, key API/dashboard smoke paths, worker/data freshness, and relevant post-deploy telemetry.
9. Hold an appropriate soak for changes with memory/concurrency/worker risk before final production certification.

## Evidence and Readiness

This skill is the sole authority for these production states:

- `DEPLOY_READY` — exact-head merge/release evidence and deployment prerequisites are satisfied, but production has not yet been verified.
- `DEPLOYED_UNVERIFIED` — deployment occurred, but required runtime/smoke/soak evidence is incomplete.
- `PRODUCTION_VERIFIED` — deployed revision identity and required runtime health, smoke, data/worker freshness, and risk-proportional soak checks are confirmed.

Earlier states such as `NOT_READY`, `ANALYSIS_COMPLETE`, `CODE_READY`, and `MERGE_READY` may be supplied by the engineering workflow, but this skill independently revalidates them before release.

## Verification

Record exact SHA, CI run/check results, review status, security/dependency evidence, migration/backup evidence if relevant, image/artifact digest, deployment revision, health endpoints, smoke results, and post-deploy observations. Any missing required evidence downgrades the readiness state.

## Handoffs

Failed checks return to the owning specialist. Runtime soak failures → `runtime-reliability-performance` and `observability-incident-response`. Model-promotion uncertainty → `strategy-score-lifecycle` and `scientific-backtest-validation`.

## Common Mistakes

- Declaring `PRODUCTION_VERIFIED` from unit tests or CI alone.
- Verifying one SHA and deploying another.
- Ignoring unresolved review threads.
- Migrating without backup/restore or rollback evidence.
- Treating successful container start as sufficient smoke/soak verification.
