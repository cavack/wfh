# Automatic Production Deployment

WaterfallHunter Production is `SIGNAL_ONLY`. The supported runtime must keep `LIVE_TRADING_ENABLED=false`; deployment never authorizes order placement or cancellation.

## Trigger

Production deployment is started by `.github/workflows/deploy-production.yml` only after the repository `CI` workflow completes successfully for a push to `main`.

The deployment revision is always `github.event.workflow_run.head_sha`. There is no manual revision input, no branch-name deployment, and no dry-run deployment mode.

## GitHub Production environment

Create a GitHub Environment named `production` and configure these environment secrets:

| Secret | Purpose |
| --- | --- |
| `WFH_PROD_HOST` | Production SSH hostname or IP address |
| `WFH_PROD_PORT` | SSH port; use `22` unless the host is configured differently |
| `WFH_PROD_USER` | Dedicated deployment account |
| `WFH_PROD_SSH_KEY` | Private key for the dedicated deployment account |
| `WFH_PROD_KNOWN_HOSTS` | Pinned OpenSSH `known_hosts` entry for the Production host |

The workflow uses `StrictHostKeyChecking=yes`. Do not replace the pinned host key with runtime discovery and do not commit SSH credentials to the repository.

## Host preparation

The canonical application checkout is:

```text
/srv/waterfallhunter/app
```

The deployment account needs narrowly scoped access to:

- fetch the `cavack/wfh` repository;
- update the application checkout;
- run Docker Compose for WaterfallHunter;
- read/write `/srv/waterfallhunter/app/.deploy` deployment evidence;
- create and verify database backups;
- run the repository-managed migration CLI against the `waterfall_data` volume.

The host-owned `.env` must exist before the first automatic deployment and must not be replaced from Git.

Required Production values include:

```text
LIVE_TRADING_ENABLED=false
TELEGRAM_TOKEN=<host-owned secret>
TELEGRAM_CHAT_ID=<host-owned value>
```

`TELEGRAM_SIGNAL_DELIVERY_ENABLED` and `TELEGRAM_SIGNAL_DELIVERY_CUTOVER_AT` are release-managed values. The deploy script updates them after backup/migration preconditions succeed.

## Deployment sequence

For each successful `main` CI revision, `scripts/deploy_production.sh` performs the following sequence under an exclusive deployment lock:

1. validate the exact 40-character Git SHA;
2. fetch `origin/main` and require the target SHA to be an ancestor of it;
3. require the existing Production `.env` and verify `LIVE_TRADING_ENABLED=false`;
4. checkout the exact target SHA in detached state;
5. validate `docker compose config`;
6. build revision-labelled backend, frontend, and watchdog images;
7. create a timestamped SQLite backup and verify `PRAGMA integrity_check` plus SHA-256;
8. run the managed database migration preflight;
9. run the managed migration apply operation with `--source-revision <SHA>` and require postflight verification;
10. preserve the existing `.env`, then set Telegram signal delivery enabled with the current release timestamp as the cutover boundary;
11. run `docker compose up -d --remove-orphans` without deleting persistent volumes;
12. wait for `/api/livez` and `/api/readyz` within bounded retry windows;
13. require backend, frontend, and watchdog OCI revision labels to equal the target SHA;
14. verify the running backend still reports `live_trading_enabled=False`;
15. write deployment evidence to `.deploy/state/last-successful-deploy.txt`.

## Database backup and migration

The live database is `/app/data/waterfall_registry.db` inside the persistent `waterfall_data` volume.

Before migration apply, the deployment script uses SQLite backup semantics to create a point-in-time copy under:

```text
/srv/waterfallhunter/app/.deploy/backups/
```

A deployment cannot proceed if the backup is missing, empty, fails SQLite integrity verification, or does not produce a valid SHA-256 checksum.

Migration uses the repository-managed command:

```bash
python -m waterfallhunter.migrate_database \
  --db-path /app/data/waterfall_registry.db \
  --preflight
```

followed by:

```bash
python -m waterfallhunter.migrate_database \
  --db-path /app/data/waterfall_registry.db \
  --apply \
  --source-revision <exact-main-sha>
```

The migration CLI verifies the resulting managed schema and WAL state. A migration error stops the release.

## Telegram signal delivery

Telegram activation is part of the release path, but it remains a notification channel only.

After migration succeeds, deployment sets:

```text
TELEGRAM_SIGNAL_DELIVERY_ENABLED=true
TELEGRAM_SIGNAL_DELIVERY_CUTOVER_AT=<release-unix-timestamp>
```

The cutover timestamp prevents pre-release queued events from becoming eligible merely because the new release enabled delivery. Telegram credentials remain host-owned and are never written by GitHub source files.

Telegram delivery does not change `LIVE_TRADING_ENABLED=false` and never authorizes exchange orders.

## Failure and rollback

Before database migration or runtime replacement, a failure leaves the current runtime in place.

If migration has already changed the database, the script does not blindly restore old application code. It first checks whether the previous revision accepts the current managed schema. If compatibility cannot be positively verified, automatic source rollback stops and the certified pre-migration backup remains available for operator recovery.

When rollback is compatible, the script restores the previous release configuration, rebuilds/starts the previous revision, and requires health, readiness, revision identity, and the `SIGNAL_ONLY` safety boundary again.

The deploy script never runs `docker compose down -v` and never deletes the `waterfall_data` volume.

## Deployment evidence

A successful deployment records at least:

- deployed SHA;
- previous SHA;
- release timestamp;
- database backup path;
- database backup SHA-256;
- Telegram cutover timestamp;
- `live_trading_enabled=false`;
- `product_mode=SIGNAL_ONLY`.

Do not declare a release successful from a Git checkout alone. The runtime health/readiness and OCI revision checks are part of the deployment certificate.

## Recovery checklist

If automatic deployment fails after a mutable Production step:

1. inspect the GitHub Actions deployment job and host deployment log;
2. read `.deploy/state/last-successful-deploy.txt` if a previous certificate exists;
3. preserve the newest database backup and checksum files;
4. do not run an older runtime against a newer database unless schema compatibility is positively verified;
5. keep `LIVE_TRADING_ENABLED=false` throughout recovery;
6. restore Telegram settings from the saved pre-deployment `.env` copy if notification delivery must be disabled;
7. rerun the normal CI/deployment path only after the failure cause is fixed and reviewed.
