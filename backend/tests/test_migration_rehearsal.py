from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from waterfallhunter.core.migration_rehearsal import (
    MigrationRehearsalError,
    rehearse_migration_and_rollback,
    rehearse_migration_and_rollback_sequential,
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
    migration_target = (tmp_path / "independent" / "migration.db").resolve()
    rollback_target = (tmp_path / "independent" / "rollback.db").resolve()

    with pytest.raises(MigrationRehearsalError, match="HASH_MISMATCH"):
        rehearse_migration_and_rollback(
            backup_certification=certification,
            migration_target=migration_target,
            rollback_target=rollback_target,
            source_revision="a" * 40,
        )


def test_rehearsal_rejects_targets_outside_certified_destination(tmp_path: Path) -> None:
    certification = _certification(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    migration_target = (outside / "migration.db").resolve()
    rollback_target = (outside / "rollback.db").resolve()

    with pytest.raises(MigrationRehearsalError, match="OUTSIDE_CERTIFIED_DESTINATION"):
        rehearse_migration_and_rollback(
            backup_certification=certification,
            migration_target=migration_target,
            rollback_target=rollback_target,
            source_revision="a" * 40,
        )


def test_rehearsal_rejects_wal_sidecar_on_certified_backup(tmp_path: Path) -> None:
    certification = _certification(tmp_path)
    Path(f"{certification['backup_path']}-wal").write_bytes(b"unexpected")
    migration_target = (tmp_path / "independent" / "migration.db").resolve()
    rollback_target = (tmp_path / "independent" / "rollback.db").resolve()

    with pytest.raises(MigrationRehearsalError, match="SQLITE_SIDECARS"):
        rehearse_migration_and_rollback(
            backup_certification=certification,
            migration_target=migration_target,
            rollback_target=rollback_target,
            source_revision="a" * 40,
        )


from waterfallhunter.core.github_release_backup_verification import TrustedRemoteBackupVerification
from waterfallhunter.core.remote_backup_certification import build_remote_backup_certification
from waterfallhunter.core.signal_metadata import canonical_sha256
from waterfallhunter.core.sqlite_backup_certification import audit_sqlite_snapshot, restore_sqlite_snapshot


def _remote_certification(tmp_path: Path) -> dict:
    source_dir = tmp_path / "source-remote"
    destination_dir = tmp_path / "remote-recovery"
    source_dir.mkdir()
    destination_dir.mkdir()
    source = source_dir / "empty.db"
    staging = destination_dir / "staging.db"
    restored = destination_dir / "restored.db"
    _empty_database(source)
    restore_sqlite_snapshot(source=source, target=staging)
    restore_sqlite_snapshot(source=staging, target=restored)
    verification_body = {
        "contract_version": "github_release_backup_verification_v1",
        "repository": "cavack/wfh-dr",
        "release_id": 77,
        "tag_name": "wfh-dr-test",
        "private_repository": True,
        "published_at_epoch": 1_787_957_000,
        "asset_ids": {
            "part-000.enc": 101,
            "waterfall_registry.manifest.json": 102,
        },
        "asset_sha256": {
            "part-000.enc": "a" * 64,
            "waterfall_registry.manifest.json": "b" * 64,
        },
    }
    trusted = TrustedRemoteBackupVerification.model_validate(
        {
            **verification_body,
            "verification_report_sha256": canonical_sha256(verification_body),
        }
    )
    backup_audit = audit_sqlite_snapshot(staging)
    return build_remote_backup_certification(
        source=source,
        source_identity={"device_id": source.stat().st_dev, "inode": source.stat().st_ino},
        source_failure_domain="production-vda1",
        destination_failure_domain="github-private-release:cavack/wfh-dr",
        backup_audit=backup_audit,
        restored_backup_path=restored,
        repository="cavack/wfh-dr",
        release_id=77,
        tag_name="wfh-dr-test",
        remote_assets=[
            {"name": "part-000.enc", "id": 101, "size_bytes": 1234, "sha256": "a" * 64},
            {"name": "waterfall_registry.manifest.json", "id": 102, "size_bytes": 456, "sha256": "b" * 64},
        ],
        remote_verification=trusted,
        backup_started_at=1_787_956_900,
        backup_completed_at=1_787_956_950,
        encryption={
            "algorithm": "AES-256-GCM",
            "compression": "zlib",
            "manifest_asset_name": "waterfall_registry.manifest.json",
            "manifest_sha256": "b" * 64,
            "plaintext_sha256": backup_audit["file_sha256"],
            "ciphertext_sha256": "c" * 64,
            "chunk_count": 1,
        },
    )


def test_rehearsal_accepts_certified_remote_restore_as_baseline(tmp_path: Path) -> None:
    certification = _remote_certification(tmp_path)
    destination = Path(certification["local_restore_path"]).parent
    report = rehearse_migration_and_rollback(
        backup_certification=certification,
        migration_target=(destination / "migration-stage.db").resolve(),
        rollback_target=(destination / "rollback-stage.db").resolve(),
        source_revision="a" * 40,
    )
    assert report["status"] == "MIGRATION_AND_ROLLBACK_REHEARSED"
    assert report["rollback_matches_baseline"] is True
    assert report["baseline_audit_sha256"] == audit_sqlite_snapshot(
        Path(certification["local_restore_path"])
    )["audit_sha256"]


def test_sequential_rehearsal_reuses_one_working_target_and_finishes_rolled_back(
    tmp_path: Path,
) -> None:
    certification = _certification(tmp_path)
    destination = tmp_path / "independent"
    working = (destination / "sequential-stage.db").resolve()

    report = rehearse_migration_and_rollback_sequential(
        backup_certification=certification,
        working_target=working,
        source_revision="a" * 40,
    )

    assert report["contract_version"] == "sqlite_migration_rollback_rehearsal_v2"
    assert report["status"] == "MIGRATION_AND_ROLLBACK_REHEARSED"
    assert report["working_target"] == str(working)
    assert report["migration_artifact_retained"] is False
    assert report["rollback_artifact_retained"] is True
    assert working.is_file()
    assert report["post_migration_audit"]["user_version"] == CURRENT_RUNTIME_SCHEMA_VERSION
    assert report["rollback_audit"]["user_version"] == 0
    assert report["rollback_matches_baseline"] is True
