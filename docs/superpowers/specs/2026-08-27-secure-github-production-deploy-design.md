# Automatic GitHub Production Deployment Design

## Goal
Deploy every CI-certified `main` revision automatically to the Ubuntu WaterfallHunter runtime, including controlled database migration and Telegram signal delivery activation, while keeping the product strictly `SIGNAL_ONLY` and preventing order execution.

## Product boundary
WaterfallHunter is `SIGNAL_ONLY`.

- `LIVE_TRADING_ENABLED=false` is mandatory before, during, and after deployment.
- No order placement, order cancellation, automatic position execution, or exchange-account trading action is introduced.
- Product/runtime/user-facing `SIGNAL_ONLY`, `signal-only`, and `signal-only operation` terminology is replaced by `SIGNAL_ONLY` / `signal-only`.
- Historical/research replay may still simulate execution economics, but it must not describe the product runtime as signal-only operation.

## Architecture
GitHub Actions is the deployment control plane. CI remains the validation workflow for `main`. A second workflow runs only after the `CI` workflow completes successfully for `main`, resolves the exact certified SHA from `workflow_run.head_sha`, and deploys that immutable revision to Production over pinned-host-key SSH.

There is no manual dispatch or dry-run branch in the Production workflow.

## GitHub environment contract
Use a GitHub Environment named `production` with these environment secrets:

- `WFH_PROD_HOST`
- `WFH_PROD_PORT`
- `WFH_PROD_USER`
- `WFH_PROD_SSH_KEY`
- `WFH_PROD_KNOWN_HOSTS`

Telegram credentials remain host-owned in Production `.env`; the deployment does not copy credentials from source control. Host identity is pinned with `StrictHostKeyChecking=yes`.

## Host contract
Canonical application root: `/srv/waterfallhunter/app`.

The deploy identity must be able to fetch the repository, operate Docker Compose for this application, update the application checkout, execute the managed migration CLI against the application data volume, and read health/revision evidence. It must not require unrestricted root shell access solely for deployment.

The Production `.env` is host-owned and must already exist. Deployment fails unless:

- `LIVE_TRADING_ENABLED=false`;
- `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` are present when signal delivery is activated;
- the repository and Docker/Compose prerequisites are healthy.

## Automatic deployment sequence
1. GitHub `CI` succeeds for a push to `main`.
2. Deployment workflow binds `WFH_DEPLOY_SHA` to `workflow_run.head_sha` and verifies the SHA belongs to `origin/main`.
3. SSH connection uses the pinned known-hosts entry.
4. Host deployment acquires an exclusive lock to prevent overlapping releases.
5. Record the previous deployed SHA and current `.env` Telegram delivery settings for rollback provenance.
6. Fetch and checkout the exact target SHA in detached state.
7. Validate Compose and assert `LIVE_TRADING_ENABLED=false`.
8. Build revision-labelled backend/frontend/watchdog images.
9. Create a timestamped SQLite backup from the persistent `waterfall_data` volume using SQLite backup semantics before migration.
10. Run `python -m waterfallhunter.migrate_database --preflight` against the Production database from the target backend artifact.
11. Run `python -m waterfallhunter.migrate_database --apply --source-revision <SHA>` and require successful postflight/schema verification.
12. Set `TELEGRAM_SIGNAL_DELIVERY_ENABLED=true` and set `TELEGRAM_SIGNAL_DELIVERY_CUTOVER_AT` to the current deployment UTC Unix timestamp without changing Telegram credentials.
13. Start/update the Compose stack without deleting persistent volumes.
14. Require bounded `/livez` and `/readyz` success.
15. Verify running OCI revision labels equal the exact target SHA.
16. Verify the running configuration still has `LIVE_TRADING_ENABLED=false` and identifies the runtime/product boundary as `SIGNAL_ONLY`.
17. Persist deployment metadata including target SHA, previous SHA, backup path/hash, migration result, Telegram cutover timestamp, and postflight health.

## Failure and rollback semantics
Failures before migration/container replacement leave the current runtime in place.

After a database migration succeeds, rollback must not silently run old code against a newer incompatible schema. The deploy script therefore records migration state and only performs automatic source/container rollback when the previous revision declares compatibility with the current managed schema. Otherwise it stops the rollout, keeps the new database backup/evidence, and reports a hard deployment failure for operator recovery.

If container replacement fails after migration and schema compatibility permits rollback, restore the previous revision, restore previous Telegram delivery settings, rebuild/start it, and verify health/revision again. The pre-migration backup is retained and never automatically deleted.

## Telegram semantics
Telegram delivery is part of the automatic release path, but only for signal notifications.

- Credentials are never committed.
- Delivery is enabled only after successful migration/build preconditions.
- `TELEGRAM_SIGNAL_DELIVERY_CUTOVER_AT` is set to the current release timestamp so historical queued events from before the release cannot become newly eligible solely because deployment enabled delivery.
- Telegram activation never authorizes exchange order execution.

## Terminology migration
The canonical runtime/product execution mode becomes `SIGNAL_ONLY`.

Any API/contract field currently emitting `SIGNAL_ONLY` must emit `SIGNAL_ONLY`; corresponding backend tests, frontend copy, docs, configuration comments, and deployment certification vocabulary must be updated. A repository hygiene regression test prevents reintroduction of the deprecated product-boundary terms.

## Verification
The PR must demonstrate RED→GREEN tests for:

- automatic `workflow_run` deployment only after successful `CI` on `main`;
- exact-SHA binding;
- pinned SSH host verification;
- deployment locking;
- backup-before-migration ordering;
- managed migration preflight/apply/postflight;
- Telegram enablement with release cutover;
- `LIVE_TRADING_ENABLED=false` fail-closed behavior;
- `SIGNAL_ONLY` contract/copy semantics;
- bounded readiness and OCI revision checks;
- rollback behavior and migration compatibility handling;
- absence of destructive volume removal and plaintext secrets.

## Non-goals
- No automatic or manual live order placement.
- No `LIVE_TRADING_ENABLED=true` path.
- No destructive volume recreation.
- No unauthenticated SSH host trust.
- No deployment from uncertified pull-request or arbitrary branch revisions.
