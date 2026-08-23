"""Isolated canonical-migration and backup-based rollback rehearsal."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from waterfallhunter.core.migration_preflight import PreflightState, classify_database
from waterfallhunter.core.schema_contract import CURRENT_RUNTIME_SCHEMA_VERSION
from waterfallhunter.core.signal_metadata import canonical_sha256
from waterfallhunter.core.sqlite_backup_certification import (
    BackupCertificationError,
    audit_sqlite_snapshot,
    restore_sqlite_snapshot,
)
from waterfallhunter.migrate_database import main as migration_main


class MigrationRehearsalError(RuntimeError):
    """Raised when staging migration or rollback evidence is incomplete."""


_ROLLBACK_COMPARABLE_FIELDS = (
    "user_version",
    "schema_version",
    "object_counts",
    "table_counts",
    "schema_sha256",
)


def _verified_backup_path(certification: dict[str, Any]) -> Path:
    claimed_hash = str(certification.get("certification_sha256", ""))
    material = {
        key: value
        for key, value in certification.items()
        if key != "certification_sha256"
    }
    if claimed_hash != canonical_sha256(material):
        raise MigrationRehearsalError("BACKUP_CERTIFICATION_HASH_MISMATCH")
    if certification.get("status") != "BACKUP_RESTORE_CERTIFIED":
        raise MigrationRehearsalError("BACKUP_NOT_CERTIFIED")
    backup = Path(str(certification.get("backup_path", "")))
    try:
        audit = audit_sqlite_snapshot(backup)
    except (BackupCertificationError, OSError) as error:
        raise MigrationRehearsalError("CERTIFIED_BACKUP_UNREADABLE") from error
    if audit["file_sha256"] != certification["backup_audit"]["file_sha256"]:
        raise MigrationRehearsalError("CERTIFIED_BACKUP_CHECKSUM_MISMATCH")
    return backup


def _run_canonical_migration(target: Path, source_revision: str) -> dict[str, Any]:
    output = io.StringIO()
    with redirect_stdout(output):
        status = migration_main(
            [
                "--db-path",
                str(target),
                "--source-revision",
                source_revision,
                "--apply",
            ]
        )
    line = output.getvalue().strip()
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as error:
        raise MigrationRehearsalError("MIGRATION_OUTPUT_INVALID") from error
    if status != 0 or payload.get("ok") is not True:
        reasons = ",".join(str(value) for value in payload.get("reason_codes", []))
        raise MigrationRehearsalError(f"STAGING_MIGRATION_FAILED:{reasons}")
    return payload


def rehearse_migration_and_rollback(
    *,
    backup_certification: dict[str, Any],
    migration_target: Path,
    rollback_target: Path,
    source_revision: str,
) -> dict[str, Any]:
    """Migrate one restored clone, then prove rollback on another clean clone."""
    if len(source_revision) != 40 or any(
        character not in "0123456789abcdef" for character in source_revision
    ):
        raise MigrationRehearsalError("SOURCE_REVISION_INVALID")
    if migration_target.resolve(strict=False) == rollback_target.resolve(strict=False):
        raise MigrationRehearsalError("MIGRATION_AND_ROLLBACK_TARGETS_MUST_DIFFER")
    backup = _verified_backup_path(backup_certification)
    baseline_audit = audit_sqlite_snapshot(backup)
    pre_migration_audit = restore_sqlite_snapshot(
        source=backup,
        target=migration_target,
    )
    if any(
        baseline_audit[field] != pre_migration_audit[field]
        for field in _ROLLBACK_COMPARABLE_FIELDS
    ):
        raise MigrationRehearsalError("MIGRATION_CLONE_MISMATCH")

    migration_result = _run_canonical_migration(migration_target, source_revision)
    postflight = classify_database(db_path=migration_target)
    if (
        postflight.state is not PreflightState.MIGRATED_COMPATIBLE
        or postflight.user_version != CURRENT_RUNTIME_SCHEMA_VERSION
    ):
        raise MigrationRehearsalError("MIGRATION_POSTFLIGHT_FAILED")
    post_migration_audit = audit_sqlite_snapshot(migration_target)

    rollback_audit = restore_sqlite_snapshot(source=backup, target=rollback_target)
    rollback_mismatches = [
        field
        for field in _ROLLBACK_COMPARABLE_FIELDS
        if baseline_audit[field] != rollback_audit[field]
    ]
    if rollback_mismatches:
        raise MigrationRehearsalError(
            "ROLLBACK_RESTORE_MISMATCH:" + ",".join(rollback_mismatches)
        )
    body = {
        "contract_version": "sqlite_migration_rollback_rehearsal_v1",
        "status": "MIGRATION_AND_ROLLBACK_REHEARSED",
        "source_revision": source_revision,
        "backup_certification_sha256": backup_certification["certification_sha256"],
        "baseline_audit_sha256": baseline_audit["audit_sha256"],
        "migration_target": str(migration_target),
        "migration_result": migration_result,
        "post_migration_audit": post_migration_audit,
        "rollback_target": str(rollback_target),
        "rollback_audit": rollback_audit,
        "rollback_matches_baseline": True,
        "production_migration_authorized": False,
        "production_deployment_authorized": False,
    }
    return {**body, "rehearsal_sha256": canonical_sha256(body)}
