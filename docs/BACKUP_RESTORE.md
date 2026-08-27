# Backup and Restore

## Backup gate

Before a production migration or destructive cleanup, create a certified SQLite backup. Certification records source release SHA, schema/user version, file size, SHA-256, UTC timestamps, SQLite integrity result, and representative table counts.

Use `scripts/certify_sqlite_backup.py` for a certified backup and `scripts/rehearse_sqlite_migration.py` for isolated target migration/rollback rehearsal.

## Restore rule

Never overwrite the only good backup. Restore into a new file/volume, run `PRAGMA integrity_check`, verify schema and canonical table/view invariants, then cut runtime to the restored data only through the guarded deployment path.

## Retention

Keep a small bounded recovery set, normally two certified backups, while retaining at least one valid pre-migration recovery point until post-cutover certification is complete.

## Cleanup dependency

Legacy databases/backups are deletion-eligible only after proving they are neither the canonical production DB nor a required certified recovery artifact.
