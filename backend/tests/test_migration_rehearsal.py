from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from waterfallhunter.core.migration_rehearsal import (
    MigrationRehearsalError,
    rehearse_migration_and_rollback,
)
from waterfallhunter.core.schema_contract import CURRENT_RUNTIME_SCHEMA_VERSION
from waterfallhunter.core.sqlite_backup_certification import create_certified_backup


def _empty_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=0")


def _certification(tmp_path: Path) -> dict:
    source_dir = tmp_path / "source"
    destination_dir = tmp_path / "independent"
    source_dir.mkdir()
    destination_dir.mkdir()
    source = source_dir / "empty.db"
    _empty_database(source)
    return create_certified_backup(
        source=source,
        backup=destination_dir / "backup.db",
        restore_target=destination_dir / "restore-proof.db",
        source_failure_domain="production",
        destination_failure_domain="independent",
        enforce_distinct_device=False,
    )


def test_rehearsal_uses_canonical_migration_and_proves_backup_rollback(
    tmp_path: Path,
) -> None:
    certification = _certification(tmp_path)

    report = rehearse_migration_and_rollback(
        backup_certification=certification,
        migration_target=(tmp_path / "independent" / "migration-stage.db").resolve(),
        rollback_target=(tmp_path / "independent" / "rollback-stage.db").resolve(),
        source_revision="a" * 40,
    )

    assert report["status"] == "MIGRATION_AND_ROLLBACK_REHEARSED"
    assert report["migration_result"]["user_version"] == CURRENT_RUNTIME_SCHEMA_VERSION
    assert report["rollback_matches_baseline"] is True
    assert report["rollback_audit"]["user_version"] == 0
    assert report["production_migration_authorized"] is False
    assert len(report["rehearsal_sha256"]) == 64


def test_rehearsal_rejects_tampered_backup_certification(tmp_path: Path) -> None:
    certification = _certification(tmp_path)
    certification["status"] = "TAMPERED"

    with pytest.raises(MigrationRehearsalError, match="HASH_MISMATCH"):
        rehearse_migration_and_rollback(
            backup_certification=certification,
            migration_target=(tmp_path / "independent" / "migration.db").resolve(),
            rollback_target=(tmp_path / "independent" / "rollback.db").resolve(),
            source_revision="a" * 40,
        )
