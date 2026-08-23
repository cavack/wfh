from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from waterfallhunter.core.sqlite_backup_certification import (
    BackupCertificationError,
    audit_sqlite_snapshot,
    create_certified_backup,
)


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;
            PRAGMA journal_mode=WAL;
            CREATE TABLE parent(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE child(
                id INTEGER PRIMARY KEY,
                parent_id INTEGER NOT NULL REFERENCES parent(id),
                value TEXT NOT NULL
            );
            CREATE INDEX child_parent_idx ON child(parent_id);
            INSERT INTO parent(id, name) VALUES (1, 'redacted');
            INSERT INTO child(id, parent_id, value) VALUES (1, 1, 'redacted');
            PRAGMA user_version=7;
            """
        )


def test_online_backup_restore_is_integrity_and_count_certified(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    destination_dir = tmp_path / "independent"
    source_dir.mkdir()
    destination_dir.mkdir()
    source = source_dir / "registry.db"
    backup = destination_dir / "registry.backup.db"
    restore = destination_dir / "restore-test.db"
    _database(source)

    report = create_certified_backup(
        source=source,
        backup=backup,
        restore_target=restore,
        source_failure_domain="production-block-volume",
        destination_failure_domain="independent-object-mount",
        enforce_distinct_device=False,
    )

    assert report["status"] == "BACKUP_RESTORE_CERTIFIED"
    assert report["restore_matches_backup"] is True
    assert report["backup_audit"]["integrity_check"] == "ok"
    assert report["backup_audit"]["foreign_key_violation_count"] == 0
    assert report["backup_audit"]["table_counts"] == {"child": 1, "parent": 1}
    assert report["backup_audit"]["schema_sha256"] == report["restore_audit"][
        "schema_sha256"
    ]
    assert report["production_migration_authorized"] is False
    assert len(report["certification_sha256"]) == 64
    assert audit_sqlite_snapshot(backup)["audit_sha256"] == report["backup_audit"][
        "audit_sha256"
    ]


def test_backup_fails_before_writing_when_failure_domain_is_not_independent(
    tmp_path: Path,
) -> None:
    source = tmp_path / "registry.db"
    _database(source)
    backup = tmp_path / "backup.db"

    with pytest.raises(BackupCertificationError, match="FAILURE_DOMAIN_NOT_INDEPENDENT"):
        create_certified_backup(
            source=source,
            backup=backup,
            restore_target=tmp_path / "restore.db",
            source_failure_domain="same-volume",
            destination_failure_domain="same-volume",
            enforce_distinct_device=False,
        )

    assert not backup.exists()


def test_backup_never_overwrites_an_existing_target(tmp_path: Path) -> None:
    source = tmp_path / "registry.db"
    backup = tmp_path / "backup.db"
    _database(source)
    backup.write_bytes(b"operator-owned")

    with pytest.raises(BackupCertificationError, match="BACKUP_TARGET_INVALID"):
        create_certified_backup(
            source=source,
            backup=backup,
            restore_target=tmp_path / "restore.db",
            source_failure_domain="source",
            destination_failure_domain="destination",
            enforce_distinct_device=False,
        )

    assert backup.read_bytes() == b"operator-owned"


def test_backup_and_restore_targets_must_be_distinct(tmp_path: Path) -> None:
    source = tmp_path / "registry.db"
    target = tmp_path / "snapshot.db"
    _database(source)

    with pytest.raises(BackupCertificationError, match="TARGETS_MUST_DIFFER"):
        create_certified_backup(
            source=source,
            backup=target,
            restore_target=target,
            source_failure_domain="source",
            destination_failure_domain="destination",
            enforce_distinct_device=False,
        )

    assert not target.exists()
