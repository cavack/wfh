# Automatic Production Deployment

WaterfallHunter Production is `SIGNAL_ONLY`. The supported runtime must keep `LIVE_TRADING_ENABLED=false`; deployment never authorizes order placement, order cancellation, or exchange-account execution.

## Trigger

Production deployment is the final dependent job in `.github/workflows/ci.yml`. It runs only after backend, frontend, dependency-audit, container-validation, and repository-hygiene jobs succeed for a `push` to `main`.

That job calls `.github/workflows/deploy-production.yml` through `workflow_call`. Pull requests never receive Production credentials, there is no `workflow_run` trust boundary, there is no manual revision input, and there is no dry-run deployment mode.

The deployment revision is the trusted `github.sha`. Both GitHub Actions and the host require that SHA to equal the current `origin/main` tip before Production mutation begins. An older successful CI run therefore cannot deploy over a newer main revision.

## GitHub Production environment

Create a GitHub Environment named `production` with:

| Secret | Purpose |
| --- | --- |
| `WFH_PROD_HOST` | Production SSH DNS hostname or IPv4 address. IPv6 literals are not supported by the current workflow contract. |
| `WFH_PROD_PORT` | SSH port; defaults to `22` when empty |
| `WFH_PROD_USER` | Dedicated deployment account |
| `WFH_PROD_SSH_KEY` | Private key for that account |
| `WFH_PROD_KNOWN_HOSTS` | Pinned OpenSSH `known_hosts` entry |

The reusable workflow uses `contents: read`, validates connection parameters, writes the private key with mode 600, and requires `StrictHostKeyChecking=yes`. Never replace pinned host identity with runtime `ssh-keyscan` and never commit credentials.

## Host preparation

Canonical checkout:

```text
/srv/waterfallhunter/app
```

The deployment account needs narrowly scoped access to:

- fetch `cavack/wfh`;
- update this application checkout;
- run Docker Compose for WaterfallHunter;
- read/write `/srv/waterfallhunter/app/.deploy` state, lock, backup, and evidence files;
- create/verify database backups;
- run the repository-managed migration CLI against the `waterfall_data` volume.

The checkout must not contain local tracked edits or untracked source/build-context files. The deployment script allows only the host-owned `.env` and `.deploy/` state paths outside Git and fails closed on other worktree drift before checkout/build.

The host-owned `.env` must exist before automatic deployment and is never replaced from Git. Required values include:

```text
LIVE_TRADING_ENABLED=false
TELEGRAM_TOKEN=<host-owned secret>
TELEGRAM_CHAT_ID=<host-owned value>
```

`TELEGRAM_SIGNAL_DELIVERY_ENABLED` and `TELEGRAM_SIGNAL_DELIVERY_CUTOVER_AT` are release-managed controls.

## Deployment sequence

For a validated current `main` tip, `scripts/deploy_production.sh` runs under an exclusive lock below `.deploy/state`:

1. validate the target SHA, Production `.env`, backup-retention value, required commands, and clean source worktree;
2. fetch `origin/main` and require exact equality with `WFH_DEPLOY_SHA`;
3. resolve the previous certified/running revision for rollback provenance;
4. verify `LIVE_TRADING_ENABLED=false`;
5. checkout the exact target revision and validate Compose;
6. build revision-labelled backend, frontend, and watchdog images;
7. create a timestamped SQLite backup and verify `PRAGMA integrity_check` plus SHA-256;
8. run managed migration preflight;
9. mark migration as potentially mutable before invoking migration apply;
10. apply migration with `--source-revision <SHA>` using non-interactive Compose execution;
11. preserve the pre-release `.env`, capture a fresh Telegram cutover timestamp, and enable signal delivery;
12. run `docker compose up -d --remove-orphans` without deleting persistent volumes;
13. require backend `/livez` and `/readyz`;
14. require healthy backend, frontend, and watchdog containers;
15. require all three OCI revision labels to equal the target SHA;
16. verify the running backend still has `live_trading_enabled=False`;
17. enforce bounded certified database-backup retention;
18. publish `.deploy/state/last-successful-deploy.txt` only after all preceding certification work succeeds;
19. remove the temporary pre-release `.env` rollback copy so secret-bearing environment backups do not accumulate.

## Database backup and migration

The live database is `/app/data/waterfall_registry.db` in the persistent `waterfall_data` volume. Backup files and checksum evidence live under:

```text
/srv/waterfallhunter/app/.deploy/backups/
```

A release stops if the new backup is missing, empty, fails SQLite integrity verification, or lacks a valid SHA-256 checksum.

Migration uses:

```bash
python -m waterfallhunter.migrate_database \
  --db-path /app/data/waterfall_registry.db \
  --preflight
```

then:

```bash
python -m waterfallhunter.migrate_database \
  --db-path /app/data/waterfall_registry.db \
  --apply \
  --source-revision <exact-current-main-sha>
```

Every `docker compose run` used by the streamed host deployment is explicitly non-interactive so it cannot consume the remaining deployment script from SSH stdin.

The script marks the database as potentially mutated before `--apply`, because a migration process can change state and then fail. Cleanup therefore remains rollback-aware even for partial apply failures.

`WFH_DEPLOY_BACKUP_RETENTION_COUNT` controls bounded backup retention and must be a positive integer. The default is 10.

## Telegram signal delivery

Telegram is a notification channel only. After build/migration prerequisites succeed, deployment sets:

```text
TELEGRAM_SIGNAL_DELIVERY_ENABLED=true
TELEGRAM_SIGNAL_DELIVERY_CUTOVER_AT=<activation-unix-timestamp>
```

The cutover is captured at Telegram activation time, not script startup. Events created before that boundary remain suppressed. Credentials remain host-owned and Telegram activation never changes `LIVE_TRADING_ENABLED=false` or authorizes exchange orders.

A temporary pre-release `.env` copy exists only for rollback during the active deployment. It is removed after successful certification rather than retained as a historical secret archive.

## Failure, signals, and rollback

Explicit deployment failures and `ERR`, `TERM`, `HUP`, and `INT` converge on the same bounded cleanup path.

Before mutable Production steps, cleanup restores the prior workspace/environment where needed. Once migration may have changed the database, the previous revision is restarted only if its managed-schema preflight proves compatibility with the current schema. If compatibility cannot be certified, automatic source rollback stops, the release containers are stopped to quarantine the incompatible runtime, and the backup/evidence is preserved for operator recovery.

When rollback is allowed, the script restores previous release settings, rebuilds/starts the previous revision, requires backend live/readiness, requires healthy backend/frontend/watchdog containers, verifies the previous OCI revision labels, and rechecks the `SIGNAL_ONLY` safety boundary.

The script never runs `docker compose down -v` and never deletes the `waterfall_data` volume.

## Deployment evidence

A successful certificate records at least:

- deployed SHA;
- previous certified/running SHA;
- deployment timestamp;
- database backup path and SHA-256;
- Telegram activation cutover timestamp;
- `live_trading_enabled=false`;
- `product_mode=SIGNAL_ONLY`.

The success certificate is not replaced until backup retention and all runtime certification checks have succeeded. Do not declare success from a Git checkout alone. Readiness, three-container health, OCI revision identity, database evidence, and the runtime boundary are part of certification.

## Recovery checklist

If automatic deployment fails after a mutable Production step:

1. inspect the GitHub Actions deploy job and host log;
2. read `.deploy/state/last-successful-deploy.txt` when present;
3. preserve the newest database backup and checksum evidence;
4. never run an older runtime against a newer database without positive schema-compatibility evidence;
5. if schema compatibility cannot be certified, keep the application containers quarantined until operator recovery is complete;
6. keep `LIVE_TRADING_ENABLED=false` throughout recovery;
7. restore Telegram settings from the active deployment's pre-release `.env` copy when rollback is possible;
8. fix/review the cause and let the normal validated main-push CI path perform the next deployment.
