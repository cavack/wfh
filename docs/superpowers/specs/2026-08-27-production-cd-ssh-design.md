# Guarded GitHub-to-Ubuntu CD Design

## Context

WaterfallHunter already has a strong CI pipeline and explicit paper-only deployment certification boundaries, but the repository has no workflow that can carry an approved revision from GitHub to the Ubuntu Docker Compose host. Production currently depends on operator-side deployment steps.

The current production invariants remain authoritative:

- `LIVE_TRADING_ENABLED=false` is mandatory.
- Deployment is paper-only and does not authorize a live order path.
- Telegram delivery is independently controlled and this deployment flow must not enable or alter it.
- Runtime migrations are explicit operations and must never be auto-applied by application startup or by this CD workflow.
- A deployment must use an exact revision from `main` and must stop on schema/readiness/health mismatch.

## Goal

Add a guarded, manually initiated GitHub Actions deployment path that can deploy an exact, already-CI-green `main` SHA to the Ubuntu Docker Compose host over pinned-host-key SSH, verify the target before cutover, and automatically restore the previous application revision/images if post-cutover health fails.

This design establishes the transport and rollback mechanism. It does **not** configure GitHub secrets, mutate Production, run a Production migration, enable Telegram delivery, or grant live-trading authority by itself.

## Selected approach

Use GitHub Actions `workflow_dispatch` plus OpenSSH to invoke a first-party deployment orchestrator stored in the repository.

Why this approach:

- It does not require a permanently privileged self-hosted GitHub runner on the Production host.
- It keeps deployment intent in GitHub audit logs.
- It uses first-party OpenSSH rather than an opaque third-party SSH action.
- It can enforce exact SHA, successful CI, clean remote worktree, host-key pinning, schema preflight, and rollback before any future automation is considered.
- It fits the existing single-host Docker Compose architecture without introducing registry/cluster infrastructure.

A future immutable-image registry flow can replace remote building after the current runtime is stable and deployment evidence proves the need. It is deliberately out of scope for this change.

## GitHub workflow

Create `.github/workflows/deploy-production.yml` with these properties:

- Trigger: `workflow_dispatch` only.
- Required input `target_sha`: exact 40-character commit SHA.
- Required input `confirm`: must equal `DEPLOY_PAPER_ONLY`.
- Permissions: `contents: read`, `actions: read`; no write permissions.
- Concurrency group: one Production deployment at a time, with `cancel-in-progress: false`.
- Job environment: `production` so repository owners can add GitHub Environment protection/required reviewers without changing workflow code.
- Validation before SSH:
  - checkout/fetch `main` with full history;
  - validate SHA syntax;
  - require `target_sha == origin/main`;
  - query GitHub Actions and require at least one successful `CI` push run for that SHA;
  - require all deployment connection material to be present.
- SSH security:
  - private key comes from `WFH_DEPLOY_SSH_KEY`;
  - host and user come from `WFH_DEPLOY_HOST` and `WFH_DEPLOY_USER`;
  - optional port comes from `WFH_DEPLOY_PORT`, defaulting to `22`;
  - exact known-host material comes from `WFH_DEPLOY_KNOWN_HOSTS`;
  - `StrictHostKeyChecking=yes`; never disable host-key checking;
  - deploy path comes from `WFH_DEPLOY_PATH` and must be an absolute path without shell metacharacters.

The workflow performs no migration. It checks out the requested exact SHA on the remote host and runs the first-party deployment orchestrator from that revision.

## Remote deployment orchestrator

Create `scripts/deploy_production.py` using only Python standard library plus external `git`/`docker` commands already required by the host.

### Preconditions

Before changing the checked-out revision or application containers, the orchestrator must:

1. require a 40-character lowercase/uppercase hexadecimal target SHA;
2. require the current working directory to be a Git worktree with no tracked/untracked changes;
3. fetch `origin main` and require `target_sha` to equal the current `origin/main` tip;
4. record the current revision as `previous_sha`;
5. require `.env` to exist;
6. parse `.env` without sourcing it and require exactly one effective `LIVE_TRADING_ENABLED=false` assignment;
7. never print `.env` contents or secret values;
8. record current image IDs for `waterfallhunter-waterfall-backend`, `waterfallhunter-frontend`, and `waterfallhunter-watchdog` before rebuilding.

If any precondition fails, no application cutover occurs.

### Build and schema preflight

After preconditions pass:

1. checkout the exact target SHA in detached mode;
2. run `docker compose config --quiet`;
3. build only `waterfall-backend`, `frontend`, and `watchdog` with deterministic source metadata:
   - `VCS_REF=<target_sha>`;
   - `BUILD_DATE=<target commit timestamp>`;
   - `VERSION=main`;
4. run the target backend image in a one-shot Compose container with the existing data volume and execute only:
   `python -m waterfallhunter.migrate_database --preflight --db-path /app/data/waterfall_registry.db`;
5. if the preflight reports incompatibility/migration required, stop and restore image tags/repository revision without restarting Production.

Production schema mutation remains a separate explicitly approved operation.

### Cutover and verification

Only after build and read-only schema preflight succeed:

1. start/update `waterfall-backend`, `frontend`, and `watchdog` with `docker compose up -d --no-build`;
2. wait for Docker health status `healthy` for all three application containers within a bounded timeout;
3. require the running containers' `org.opencontainers.image.revision` labels to equal the target SHA;
4. run explicit in-container backend and frontend smoke checks;
5. finish successfully only if every check passes.

Prometheus/Grafana/Alertmanager are not restarted by this application deployment unless a later dedicated operations change explicitly requires it.

## Rollback

Before building, retain references to the currently running application image IDs.

On any failure after the target checkout/build begins:

1. restore the three canonical application image tags to the previously recorded image IDs;
2. checkout `previous_sha` in detached mode;
3. if application cutover had occurred, run `docker compose up -d --no-build` for the three application services;
4. wait for all three containers to return to `healthy`;
5. report both the original deployment failure and rollback result;
6. return non-zero even when rollback succeeds, so GitHub records the deployment as failed.

Because this workflow never migrates Production, application rollback does not need a database rollback path.

## Tests

Add `backend/tests/test_deploy_production_script.py` using a fake command runner and temporary `.env` files. The tests must prove:

- invalid target SHA fails before any command execution;
- dirty worktree fails closed;
- non-main target SHA fails closed;
- missing or true `LIVE_TRADING_ENABLED` fails closed without evaluating `.env` as shell code;
- build happens before schema preflight and cutover;
- schema preflight failure restores previous tags/revision and never runs application `up`;
- post-cutover health failure restores image tags, previous revision, and restarts the old services;
- successful deployment verifies health and revision labels.

Add a workflow contract test that parses `.github/workflows/deploy-production.yml` as text and enforces the security-sensitive invariants: manual trigger, `production` environment, read-only permissions, required confirmation token, host-key checking, no `StrictHostKeyChecking=no`, and no migration `--apply` invocation.

## Repository skill

Add a reusable skill under `.agents/skills/safe-remote-compose-deployment/SKILL.md`. It applies to GitHub/CI-driven Docker Compose deployments to long-lived remote hosts and codifies the revision verification, no-secret-leak, preflight-before-cutover, bounded health verification, and rollback rules used by this implementation.

## Secret and environment configuration

The implementation references these GitHub Environment/Repository secrets but cannot read or create them through repository source code:

- `WFH_DEPLOY_HOST`
- `WFH_DEPLOY_USER`
- `WFH_DEPLOY_PORT` (optional; default `22`)
- `WFH_DEPLOY_PATH`
- `WFH_DEPLOY_SSH_KEY`
- `WFH_DEPLOY_KNOWN_HOSTS`

The `production` GitHub Environment should require an owner/reviewer approval before deployment. Secret values are never committed.

## Non-goals

- no Production deployment is executed by merging this PR;
- no Production database migration;
- no changes to signal scoring/lifecycle/ranking;
- no Telegram enablement;
- no live trading;
- no horizontal scaling changes;
- no GHCR/registry migration;
- no automatic deployment on every merge.

## Success criteria

The change is complete when:

- deployment unit/contract tests pass;
- the full backend suite remains green;
- frontend typecheck/build remains green;
- dependency audit, container validation, and repository hygiene remain green;
- CodeRabbit/review has no unresolved blocking finding;
- the workflow exists as a guarded manual action but has not been executed against Production without a separate deployment request and configured secrets.