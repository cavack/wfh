# Paper-only deployment certification runbook

This runbook prepares evidence. It does not authorize a Production backup,
migration, deployment, restart, Telegram send, feature promotion, or live order.
Every artifact is immutable, hash-bound, and created at a new path.

## 1. Independent backup gate

Prerequisites:

- a mounted destination on a device and failure domain independent from the
  Production database;
- enough capacity for the backup, isolated restore, migration clone, rollback
  clone, and reports;
- a fresh owner message exactly authorizing the source and destination:
  `APPROVE_BACKUP_EXECUTION: <source> -> <independent destination>`.

After that approval only, run from the tested source revision:

```bash
PYTHONPATH=backend/src:. python scripts/certify_sqlite_backup.py \
  --source /absolute/production/registry.db \
  --backup /independent/wfh/registry-<utc>-<sha>.db \
  --restore-target /independent/wfh/restore-<utc>-<sha>.db \
  --report /independent/wfh/backup-certification-<utc>-<sha>.json \
  --source-failure-domain production-block-volume \
  --destination-failure-domain independent-backup-volume
```

The command uses SQLite Online Backup API, rejects same-device/same-domain
targets, never overwrites, runs full integrity and foreign-key checks, records
all table counts and schema identity, performs an isolated restore, and compares
the restored snapshot. A local `/srv` copy is not an independent backup.

## 2. Staging migration and rollback rehearsal

This is a separate write to isolated clone files and requires:

`APPROVE_STAGING_MIGRATION: <artifact SHA> on <exact clone paths>`

```bash
PYTHONPATH=backend/src:. python scripts/rehearse_sqlite_migration.py \
  --backup-certification /independent/wfh/backup-certification-<utc>-<sha>.json \
  --migration-target /independent/wfh/migration-stage-<utc>-<sha>.db \
  --rollback-target /independent/wfh/rollback-stage-<utc>-<sha>.db \
  --source-revision <40-character-tested-git-sha> \
  --report /independent/wfh/migration-rehearsal-<utc>-<sha>.json
```

The migration clone uses the canonical `waterfallhunter.migrate_database`
boundary and verifies the current schema. The rollback clone is freshly restored
from the same certified artifact and must match the pre-migration schema and all
table counts. Production is not a target of this rehearsal.

## 3. Artifact, test, readiness, and soak packet

Build one `deployment_certification_request_v1` JSON packet containing:

- exact Git/CI revision and complete `deployment_provenance_v1` links;
- the backup and rehearsal reports above;
- backend, frontend, E2E, migration, load, fault, security and secret-scan PASS;
- zero blocker review findings;
- liveness, health, readiness, schema readiness and database readiness;
- at least 24 hours paper-only shadow soak, request error rate at or below
  0.1%, zero OOM/schema errors, and zero live-order paths.

Evaluate it offline:

```bash
PYTHONPATH=backend/src:. python scripts/evaluate_deployment_certification.py \
  --input /absolute/path/deployment-evidence.json \
  --report /absolute/path/deployment-certification.json
```

Even a passing report says `READY_FOR_EXPLICIT_OWNER_APPROVAL` and keeps
`deployment_allowed=false`. It is evidence, not authority.

## 4. Separate Production approvals

Only after every gate is green, request each operation independently:

```text
APPROVE_PRODUCTION_MIGRATION: <artifact SHA> on <exact DB/container>
APPROVE_PRODUCTION_DEPLOYMENT: <image digests> on <exact services>
APPROVE_TELEGRAM_SEND: <bot/environment/chat scope>
APPROVE_FEATURE_PROMOTION: <profile/model/version>
```

Production migration and deployment must use the exact certified artifact,
preserve `LIVE_TRADING_ENABLED=false`, verify rollback points before mutation,
recheck schema/readiness after each stage, and stop on any mismatch, OOM,
readiness regression, or unexpected write. Live trading is outside this version.
