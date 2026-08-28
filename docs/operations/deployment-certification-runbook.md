# Signal-only deployment certification runbook

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
all table counts and schema identity, binds source identity to the opened backup
inode, hash-binds `backup_started_at`/`backup_completed_at`, performs an
isolated restore, and compares the restored snapshot. A local `/srv` copy is not
an independent backup. Deployment certification rejects backups older than seven
days (`MAXIMUM_BACKUP_AGE_SECONDS`) and re-audits the immutable backup file
read-only before accepting rollback evidence.

### Encrypted private-GitHub alternative

When no independent block device exists, a recorded owner authorization may
instead approve an encrypted off-host backup to the private `cavack/wfh-dr`
repository. If the active release handoff already records that exact approval,
do not request it again. This does not authorize migration or deployment.

Preconditions:

- `cavack/wfh-dr` is private and not archived;
- `/root/.wfh-dr/wfh-dr-aes256.key` is a root-owned `0600` regular file and its
  value is never printed;
- the `WFH_DR_AES256_KEY_B64` Actions secret exists in `cavack/wfh-dr`;
- SQLite Online Backup—not raw `cp`—creates the temporary snapshot;
- the release tag and staging paths are new and the destination failure domain
  names `github.com` truthfully.

Run from an isolated worktree at the exact tested `main` revision:

```bash
PYTHONPATH=backend/src:. python scripts/certify_remote_sqlite_backup.py \
  --source /absolute/production/waterfall_registry.db \
  --staging-dir /srv/wfh-release-backups/remote-dr-<utc>-<sha> \
  --restore-target /srv/wfh-release-backups/remote-dr-<utc>-<sha>/restored.db \
  --report /srv/wfh-release-backups/remote-dr-<utc>-<sha>/backup-certification.json \
  --key-file /root/.wfh-dr/wfh-dr-aes256.key \
  --remote-repository cavack/wfh-dr \
  --release-tag wfh-production-dr-<utc>-<sha> \
  --source-failure-domain production-root-vda1 \
  --destination-failure-domain github.com-private-release:cavack/wfh-dr
```

Only the authenticated manifest and encrypted chunks may be published. After
GitHub asset IDs, sizes, and SHA-256 digests are verified, the command removes
the plaintext staging snapshot before re-downloading, decrypting, restoring,
and auditing the release. The resulting certificate must say
`BACKUP_RESTORE_CERTIFIED` and keep both Production authorization flags false.

Prove key recovery and restoreability outside the Production host by dispatching
the private DR workflow with plaintext artifact emission disabled, then seal its
exact successful run and report artifact:

```bash
gh workflow run restore.yml -R cavack/wfh-dr \
  -f release_tag=wfh-production-dr-<utc>-<sha> \
  -f emit_plaintext_artifact=false

PYTHONPATH=backend/src:. python scripts/verify_github_remote_restore.py \
  --backup-certification /srv/wfh-release-backups/remote-dr-<utc>-<sha>/backup-certification.json \
  --github-repository cavack/wfh-dr \
  --github-run-id <exact-successful-restore-run-id> \
  --report /srv/wfh-release-backups/remote-dr-<utc>-<sha>/independent-restore-verification.json
```

The deployment request must include this
`github_actions_remote_restore_verification_v1` object as
`independent_restore_verification`. Remote backup evidence cannot reach owner
approval readiness without it.

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

For the remote certificate, use the retained restored baseline and the
single-working-target mode to cap disk usage:

```bash
PYTHONPATH=backend/src:. python scripts/rehearse_sqlite_migration.py \
  --backup-certification /srv/wfh-release-backups/remote-dr-<utc>-<sha>/backup-certification.json \
  --sequential-working-target /srv/wfh-release-backups/remote-dr-<utc>-<sha>/sequential-rehearsal.db \
  --source-revision <40-character-tested-git-sha> \
  --report /srv/wfh-release-backups/remote-dr-<utc>-<sha>/migration-rehearsal.json
```

The migrated artifact is deleted before the same path is restored to the
baseline. Success requires `sqlite_migration_rollback_rehearsal_v2`, retained
rollback evidence matching the baseline, and both Production authorization
flags false.

## 3. Artifact, test, readiness, and soak packet

Build one `deployment_certification_request_v1` JSON packet containing:

- exact Git/CI revision and complete `deployment_provenance_v1` links;
- the backup and rehearsal reports above;
- for remote DR, authoritative independent restore evidence from the exact
  successful `cavack/wfh-dr` workflow run and release tag;
- backend, frontend, E2E, migration, load, fault, security and secret-scan PASS
  claims in the packet; these claims cannot authorize certification by themselves;
- an independently queried GitHub Actions run for the exact source revision, with
  successful backend/frontend/dependency-audit/container-validation/repository-hygiene
  jobs and a tested-backend image digest emitted by the same container-validation
  job after that exact image is tested; the operator derives the verification report
  hash from this GitHub-controlled run evidence rather than trusting a packet hash;
- zero blocker review findings;
- liveness, health, readiness, schema readiness and database readiness bound to
  source revision, running image digest, runtime fingerprint, staging
  environment, and `observed_at` (max age one hour);
- at least 24 hours signal-only shadow soak, request error rate at or below
  0.1%, zero OOM/schema errors, and zero live-order paths. The soak packet must
  bind its start/end, staging environment, source revision, built-image digest,
  and runtime fingerprint to the artifact being certified. Provenance must
  include the same `runtime_fingerprint_sha256`.

Evaluate it offline:

```bash
PYTHONPATH=backend/src:. python scripts/evaluate_deployment_certification.py \
  --input /absolute/path/deployment-evidence.json \
  --report /absolute/path/deployment-certification.json \
  --github-repository cavack/wfh \
  --github-run-id <exact-successful-run-id-for-source-revision>
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
