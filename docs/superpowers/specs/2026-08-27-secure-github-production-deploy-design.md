# Secure GitHub Production Deployment Design

## Goal
Create a controlled GitHub-to-Ubuntu deployment path for WaterfallHunter so a reviewed `main` revision can be deployed without manual source editing on the host.

## Safety invariants
- `LIVE_TRADING_ENABLED=false` is mandatory before, during, and after deployment.
- Deployment never enables Telegram signal delivery or experimental promotion implicitly.
- Only an explicitly selected immutable Git commit may be deployed.
- CI validation must complete before deployment is eligible.
- Runtime `.env`, databases, logs, backups, credentials, and other host state are never replaced from Git.
- A failed preflight, build, readiness check, revision check, or paper-only invariant aborts deployment.
- Previous revision is retained as the rollback target.
- Deployment uses least-privilege SSH credentials supplied through GitHub environment secrets; credentials are never committed.

## Architecture
GitHub Actions remains the control plane. A manually dispatched production workflow accepts a commit SHA, validates that it belongs to `main`, checks the required CI state, then connects to the Ubuntu host using a dedicated deploy identity. The host performs an immutable checkout/build in the canonical application directory, preserves runtime state, starts the compose stack, and verifies health/readiness plus OCI revision identity.

Production deployment is deliberately manual (`workflow_dispatch`) rather than automatic-on-merge. This preserves an explicit owner deployment boundary while eliminating `nano`, ad-hoc file copies, and mutable-source drift on the server.

## GitHub environment contract
Create a protected GitHub Environment named `production`. Configure required reviewers in GitHub UI if available. Store only these deployment credentials as environment secrets:

- `WFH_PROD_HOST`: production hostname/IP.
- `WFH_PROD_PORT`: SSH port, normally `22`.
- `WFH_PROD_USER`: dedicated deploy account.
- `WFH_PROD_SSH_KEY`: private key for that account.
- `WFH_PROD_KNOWN_HOSTS`: pinned `known_hosts` line generated out-of-band with the production host key.

Do not use `StrictHostKeyChecking=no` and do not populate known_hosts by trusting an unauthenticated runtime `ssh-keyscan` result.

## Host contract
Canonical application root: `/srv/waterfallhunter/app`.

The deploy account must be able to:
1. read/fetch the repository;
2. operate Docker Compose for this application;
3. update only the application checkout and deployment metadata;
4. read health endpoints/logs required for postflight;
5. not obtain unrestricted interactive root access solely for deployment.

The existing production `.env` remains host-owned and must already exist. Deployment refuses to proceed if it is absent or if `LIVE_TRADING_ENABLED` is not exactly false after Compose interpolation.

## Deployment sequence
1. Resolve the requested SHA and prove it is contained in `origin/main`.
2. Require successful CI for that exact revision before the production job proceeds.
3. SSH using pinned host-key verification.
4. Acquire a host deployment lock so two deployments cannot overlap.
5. Record the currently deployed Git revision as rollback provenance.
6. Fetch the requested revision and checkout it in detached state.
7. Validate `docker compose config` and fail closed unless `LIVE_TRADING_ENABLED=false`.
8. Build revision-labelled `waterfall-backend`, `frontend`, and `watchdog` images.
9. Start/update the stack without deleting persistent volumes.
10. Wait for `/livez` and `/readyz` to become healthy within a bounded timeout.
11. Verify running image OCI revision labels equal the requested SHA.
12. Verify paper-only/live-trading invariant again from the running deployment.
13. Persist the successful revision in deployment metadata.

## Failure and rollback semantics
A failure before container replacement leaves the current deployment untouched. A failure after replacement triggers a best-effort rollback to the previously recorded revision, followed by the same build/start/readiness/revision checks. If rollback cannot be certified, the workflow fails loudly and does not claim recovery.

Database migration is intentionally not automated by this first deployment slice. Any future schema-changing release must pass the repository's existing backup/migration/deployment certification gates and receive a separate explicit approval.

## Verification
Repository-side validation includes workflow syntax/static review and repository hygiene. First production activation additionally requires a dry-run/preflight path that performs SSH, repository, Docker, Compose, environment, and current-health checks without replacing containers.

A successful real deployment must report: requested SHA, previous SHA, build success, `/livez`, `/readyz`, running OCI revision, and `LIVE_TRADING_ENABLED=false`.

## Non-goals
- No live trading enablement.
- No Telegram activation.
- No automatic database migration.
- No automatic deployment on every merge.
- No secrets committed to GitHub source.
- No production source edits outside the controlled deployment path.
