# D15 — CI / Release / Production Certification

Source baseline: `main@65c063ffea6209ecd84b224656bbc627ff811898`

## Purpose

Separate code verification, merge authority, exact CI-tested artifacts, Production deployment, runtime verification, rollback, and final certification so that no earlier gate is mistaken for `PRODUCTION_VERIFIED`.

Authoritative references: `.github/workflows/ci.yml`, `.github/workflows/deploy-production.yml`, `scripts/deploy_production.sh`, `docs/OPERATIONS.md`, deployment certification runbooks, `skills/waterfallhunter/release-production-certification/SKILL.md`.

```mermaid
flowchart LR
    Source[Exact source SHA]
    Verify[Verification-regression\nblast-radius proportional]
    CI[Required CI gates\nbackend / frontend / dependency-audit / container-validation / repository-hygiene]
    Review[Review + merge authority\nMERGE_READY is not deploy authority]
    Main[Exact trusted main revision]
    Artifact[CI-tested revision-labelled\nbackend + frontend + watchdog images]
    Bundle[Hash-verified tested image bundle]
    Preflight[Production preflight\nSIGNAL_ONLY safety + backup/restore + schema/migration compatibility]
    Deploy[Guarded Production deployment\nserialized production environment]
    Deployed[DEPLOYED_UNVERIFIED]
    Health[/livez + /readyz + /healthz\nrevision + key smoke paths]
    Runtime[Worker/data freshness + risk-proportional soak]
    Cert[PRODUCTION_VERIFIED]
    Rollback[Rollback to preserved prior certified artifact/state]

    Source --> Verify --> CI --> Review --> Main --> Artifact --> Bundle --> Preflight --> Deploy --> Deployed --> Health --> Runtime --> Cert
    Preflight -- fail --> Rollback
    Health -- fail --> Rollback
    Runtime -- fail --> Rollback
```

## Current repository release mechanics

- Protected `main` currently requires the first-party status contexts `backend`, `frontend`, `dependency-audit`, `container-validation`, and `repository-hygiene`.
- The Production workflow is not a generic rebuild-on-host path. It receives exact CI-tested backend/frontend/watchdog image digests plus a tested bundle SHA-256, verifies the trusted `main` revision, downloads the exact artifact, verifies digests/revision metadata, and stages those tested inputs to the host over pinned SSH identity.
- Production deployment is serialized under the `waterfallhunter-production` concurrency group and uses the GitHub `production` environment.
- Backup/restore evidence, migration/schema preflight, preserved persistent-volume continuity, rollback target, safety flags, exact revision identity, health, smoke, worker/data freshness, and risk-proportional soak remain separate certification evidence.

## Readiness authority

Engineering workflows may establish `NOT_READY`, `ANALYSIS_COMPLETE`, `CODE_READY`, or `MERGE_READY`.

Only `release-production-certification` may declare:

- `DEPLOY_READY`: deployment prerequisites are satisfied, but Production has not yet been verified;
- `DEPLOYED_UNVERIFIED`: deployment occurred but runtime/smoke/soak evidence is incomplete;
- `PRODUCTION_VERIFIED`: exact deployed revision plus required runtime health, smoke, freshness, and proportional soak evidence are confirmed.

**CI success != Production verification.** A successful image start or merge is also insufficient by itself.

## Safety boundary

The deployment/certification path must preserve `SIGNAL_ONLY` and `LIVE_TRADING_ENABLED=false`. This diagram grants no deployment authority for the current documentation branch and makes no Production-readiness claim.
