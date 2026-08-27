# GitHub to Ubuntu Production deployment

This runbook describes the guarded GitHub Actions transport for deploying the exact current `main` revision to the long-lived Ubuntu Docker Compose host.

It does **not** authorize a database migration, Telegram delivery, feature promotion, or live trading. `LIVE_TRADING_ENABLED=false` remains mandatory.

## 1. What this workflow does

`.github/workflows/deploy-production.yml` is manual-only (`workflow_dispatch`). A deployment run:

1. requires an exact 40-character `target_sha` and the confirmation token `DEPLOY_PAPER_ONLY`;
2. requires that SHA to be the current `origin/main` tip;
3. requires a successful `CI` push run for that exact SHA;
4. waits at the GitHub `production` Environment gate;
5. connects to the Ubuntu host with a dedicated SSH key and pinned `known_hosts` entry;
6. invokes the target revision's first-party `scripts/deploy_production.py` orchestrator;
7. captures the current application revision and image IDs before replacement;
8. validates Compose and builds the target backend/frontend/watchdog images with revision labels;
9. runs **read-only** SQLite migration preflight from the target backend image;
10. updates only `waterfall-backend`, `frontend`, and `watchdog` if preflight passes;
11. waits for all three Docker health checks, verifies OCI revision labels, and runs backend/frontend smoke checks;
12. restores the previous application images and Git revision on failure.

Prometheus, Grafana, and Alertmanager are not restarted by this workflow.

## 2. GitHub Production Environment

Create a GitHub Environment named exactly:

```text
production
```

Recommended protection:

- require an owner/reviewer before a deployment job can start;
- do not allow arbitrary branches; restrict deployments to the protected `main` branch;
- keep deployment secrets at Environment scope rather than in repository source.

The workflow itself has only:

```text
contents: read
actions: read
```

Merging the workflow therefore does not grant repository write authority to a deployment run.

## 3. Required secret configuration

Configure these values in the GitHub `production` Environment (or repository secrets if Environment-scoped secrets are unavailable):

| Secret | Meaning |
| --- | --- |
| `WFH_DEPLOY_HOST` | DNS name or IP address of the Ubuntu host |
| `WFH_DEPLOY_USER` | dedicated remote deployment user |
| `WFH_DEPLOY_PORT` | SSH port; optional, defaults to `22` |
| `WFH_DEPLOY_PATH` | absolute path of the existing WaterfallHunter Git checkout on the host |
| `WFH_DEPLOY_SSH_KEY` | private key used only for the deployment account |
| `WFH_DEPLOY_KNOWN_HOSTS` | exact pinned OpenSSH `known_hosts` line(s) for the host/port |

Do not commit these values to Git. Do not copy the Production `.env` into GitHub Actions.

### Host key pinning

Generate/verify the host key out of band and store the exact trusted line in `WFH_DEPLOY_KNOWN_HOSTS`. The workflow runs with:

```text
StrictHostKeyChecking=yes
UserKnownHostsFile=<workflow-controlled known_hosts>
```

Do not replace this with `StrictHostKeyChecking=no` or `ssh-keyscan` performed blindly inside the deployment run; that would defeat host identity verification.

## 4. Remote host prerequisites

The deployment user must be able to:

- read/write the existing WaterfallHunter checkout at `WFH_DEPLOY_PATH`;
- run `git fetch` against `origin`;
- run `docker` and `docker compose` for this project;
- read the project `.env` file without exposing its contents to CI logs.

The checkout must already have the correct `origin` remote and must be clean before a deployment. The deployment orchestrator rejects tracked or untracked drift rather than overwriting it.

The Production `.env` must contain exactly one effective assignment:

```text
LIVE_TRADING_ENABLED=false
```

The parser reads the file as data; it never sources or executes `.env` contents.

## 5. Dedicated deployment SSH key

Use a dedicated key for GitHub deployment rather than a personal interactive key. On the Ubuntu host, grant that public key only to the deployment account.

The deployment account should have the minimum OS permissions needed for the WaterfallHunter checkout and Docker Compose operation. Do not give the GitHub key broader shell/admin access than the deployment requires.

After installing the key, verify manually that the deployment account can perform **read-only** checks such as:

```bash
cd <WFH_DEPLOY_PATH>
git status --short
docker compose config --quiet
docker compose ps
```

Do not run a Production deployment as part of key setup.

## 6. Database migration remains separate

The deployment workflow never invokes:

```text
waterfallhunter.migrate_database --apply
```

It invokes only `--preflight` against the target backend artifact. If the Production database is not already compatible with the target revision, deployment stops before application cutover.

When a target revision genuinely requires a Production migration, follow `docs/operations/deployment-certification-runbook.md`: certified independent backup, isolated migration/rollback rehearsal, exact-artifact certification, then a separate explicit Production migration approval. Only after that migration is complete and verified should this deployment workflow be dispatched.

This separation prevents an application rollout from silently becoming an irreversible data mutation.

## 7. Dispatch procedure

After the target commit is merged to `main` and its **push** CI run is green:

1. Open GitHub Actions.
2. Select `Production Deploy (paper-only)`.
3. Choose **Run workflow** from `main`.
4. Enter the exact current `main` SHA as `target_sha`.
5. Enter exactly:

```text
DEPLOY_PAPER_ONLY
```

6. Submit the run.
7. Approve the `production` Environment gate only after checking the target SHA and CI evidence.

The verify job rejects a stale SHA even if that SHA once passed CI. This prevents deploying an older revision after `main` has advanced.

## 8. Success criteria

A deployment is successful only when all of the following are true:

- target SHA was current `origin/main`;
- exact target had a successful CI push run;
- remote worktree was clean;
- `LIVE_TRADING_ENABLED=false` was verified without evaluating `.env`;
- target images built successfully;
- read-only database migration preflight passed;
- all three application containers reached Docker `healthy` state within the deadline;
- all running OCI revision labels equal the target SHA;
- backend health smoke check passed;
- frontend dashboard smoke check passed.

The script emits a bounded JSON result containing target/previous revision and image IDs. It does not print `.env` contents or secret values.

## 9. Automatic application rollback

Before rebuilding, the orchestrator records the currently tagged backend/frontend/watchdog image IDs and current Git revision.

If preparation fails after checkout/build, it restores the old image tags and Git revision without touching running application containers.

If cutover has started and health/revision/smoke verification fails, it:

1. restores the previous three application image tags;
2. checks out the previous Git revision;
3. runs `docker compose up -d --no-build` for the three application services;
4. waits for those services to become healthy again;
5. reports the original deployment failure plus rollback status;
6. exits non-zero even when rollback succeeds.

Because the CD workflow never applies a database migration, this automatic rollback is intentionally application-only.

## 10. Failure handling

Do not repeatedly re-run a failed Production deployment until its failure cause is understood.

Useful read-only host checks:

```bash
cd <WFH_DEPLOY_PATH>
git status --short
git rev-parse HEAD
git rev-parse origin/main
docker compose ps
docker inspect --format '{{.State.Health.Status}}' waterfall-backend
docker inspect --format '{{.State.Health.Status}}' waterfall-frontend
docker inspect --format '{{.State.Health.Status}}' waterfall-watchdog
```

If rollback is reported incomplete, stop automated retries and recover using the exact `previous_sha` and image IDs recorded in the failed GitHub Actions log. Do not mutate the database as an application-recovery shortcut.

## 11. Authority boundaries

These remain independent decisions:

```text
MERGE_APPROVAL
!= PRODUCTION_MIGRATION_APPROVAL
!= PRODUCTION_DEPLOYMENT_APPROVAL
!= TELEGRAM_SEND_APPROVAL
!= FEATURE_PROMOTION_APPROVAL
!= LIVE_TRADING_APPROVAL
```

The existence of a green deployment workflow is operational capability, not authority to exercise unrelated Production actions.