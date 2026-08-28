"""Certification contract for encrypted off-host SQLite disaster-recovery backups."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from waterfallhunter.core.github_release_backup_verification import (
    TrustedRemoteBackupVerification,
)
from waterfallhunter.core.signal_metadata import canonical_sha256
from waterfallhunter.core.sqlite_backup_certification import (
    BackupCertificationError,
    audit_sqlite_snapshot,
)


class RemoteBackupCertificationError(RuntimeError):
    """Raised when remote backup evidence cannot be sealed safely."""


_COMPARABLE_FIELDS = (
    "user_version",
    "schema_version",
    "logical_content_sha256",
    "object_counts",
    "table_counts",
    "schema_sha256",
)


def _identity(path: Path) -> dict[str, int]:
    stat_result = path.stat()
    return {
        "device_id": int(stat_result.st_dev),
        "inode": int(stat_result.st_ino),
    }


def _require_source(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RemoteBackupCertificationError("BACKUP_SOURCE_INVALID")
    return path.resolve()


def _require_snapshot(path: Path, *, label: str) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RemoteBackupCertificationError(f"{label}_SNAPSHOT_INVALID")
    sidecars = [Path(f"{path}{suffix}") for suffix in ("-wal", "-shm")]
    if any(item.exists() for item in sidecars):
        raise RemoteBackupCertificationError(f"{label}_SNAPSHOT_HAS_SIDECARS")
    return path.resolve()


def _validate_assets(remote_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(remote_assets, list) or not remote_assets:
        raise RemoteBackupCertificationError("REMOTE_BACKUP_ASSETS_INVALID")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in remote_assets:
        if not isinstance(item, dict):
            raise RemoteBackupCertificationError("REMOTE_BACKUP_ASSETS_INVALID")
        name = item.get("name")
        asset_id = item.get("id")
        size = item.get("size_bytes")
        sha256 = item.get("sha256")
        if (
            not isinstance(name, str)
            or not name
            or name in seen
            or not isinstance(asset_id, int)
            or isinstance(asset_id, bool)
            or asset_id < 1
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 1
            or not isinstance(sha256, str)
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
        ):
            raise RemoteBackupCertificationError("REMOTE_BACKUP_ASSETS_INVALID")
        seen.add(name)
        normalized.append(
            {
                "name": name,
                "id": asset_id,
                "size_bytes": size,
                "sha256": sha256,
            }
        )
    return sorted(normalized, key=lambda item: item["name"])


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def validate_remote_encryption_evidence(
    *,
    encryption: dict[str, Any],
    backup_audit: dict[str, Any],
    remote_assets: list[dict[str, Any]],
) -> None:
    """Require the encrypted bundle metadata to be bound to the certified SQLite snapshot."""
    if not isinstance(encryption, dict):
        raise RemoteBackupCertificationError("REMOTE_BACKUP_ENCRYPTION_INVALID")
    manifest_name = encryption.get("manifest_asset_name")
    manifest_sha256 = encryption.get("manifest_sha256")
    plaintext_sha256 = encryption.get("plaintext_sha256")
    ciphertext_sha256 = encryption.get("ciphertext_sha256")
    chunk_count = encryption.get("chunk_count")
    if (
        encryption.get("algorithm") != "AES-256-GCM"
        or encryption.get("compression") != "zlib"
        or not isinstance(manifest_name, str)
        or not manifest_name
        or Path(manifest_name).name != manifest_name
        or not _valid_sha256(manifest_sha256)
        or not _valid_sha256(plaintext_sha256)
        or not _valid_sha256(ciphertext_sha256)
        or not isinstance(chunk_count, int)
        or isinstance(chunk_count, bool)
        or chunk_count < 1
        or plaintext_sha256 != backup_audit.get("file_sha256")
    ):
        raise RemoteBackupCertificationError("REMOTE_BACKUP_ENCRYPTION_INVALID")

    assets = _validate_assets(remote_assets)
    by_name = {item["name"]: item for item in assets}
    manifest = by_name.get(manifest_name)
    chunks = [item for item in assets if item["name"] != manifest_name]
    if (
        manifest is None
        or manifest.get("sha256") != manifest_sha256
        or len(chunks) != chunk_count
        or any(not str(item["name"]).endswith(".enc") for item in chunks)
    ):
        raise RemoteBackupCertificationError("REMOTE_BACKUP_ENCRYPTION_INVALID")


def _trusted_verification(
    value: TrustedRemoteBackupVerification | dict[str, Any],
) -> TrustedRemoteBackupVerification:
    try:
        if isinstance(value, TrustedRemoteBackupVerification):
            return value
        return TrustedRemoteBackupVerification.model_validate(value)
    except (TypeError, ValueError) as error:
        raise RemoteBackupCertificationError(
            "REMOTE_BACKUP_VERIFICATION_INVALID"
        ) from error


def build_remote_backup_certification(
    *,
    source: Path,
    source_identity: dict[str, int],
    source_failure_domain: str,
    destination_failure_domain: str,
    backup_audit: dict[str, Any],
    restored_backup_path: Path,
    repository: str,
    release_id: int,
    tag_name: str,
    remote_assets: list[dict[str, Any]],
    remote_verification: TrustedRemoteBackupVerification | dict[str, Any],
    backup_started_at: int,
    backup_completed_at: int,
    encryption: dict[str, Any],
) -> dict[str, Any]:
    """Seal one off-host remote backup after independent download and restore."""
    source_path = _require_source(source)
    if source_identity != _identity(source_path):
        raise RemoteBackupCertificationError("BACKUP_SOURCE_IDENTITY_CHANGED")
    if (
        not source_failure_domain.strip()
        or not destination_failure_domain.strip()
        or source_failure_domain == destination_failure_domain
    ):
        raise RemoteBackupCertificationError("FAILURE_DOMAIN_NOT_INDEPENDENT")
    if not isinstance(backup_started_at, int) or not isinstance(backup_completed_at, int):
        raise RemoteBackupCertificationError("BACKUP_TIMESTAMP_INVALID")
    if backup_started_at < 1 or backup_completed_at < backup_started_at:
        raise RemoteBackupCertificationError("BACKUP_TIMESTAMP_INVALID")
    if not isinstance(backup_audit, dict):
        raise RemoteBackupCertificationError("REMOTE_BACKUP_BASELINE_AUDIT_INVALID")
    claimed_audit_hash = backup_audit.get("audit_sha256")
    audit_material = {key: value for key, value in backup_audit.items() if key != "audit_sha256"}
    if (
        backup_audit.get("contract_version") != "sqlite_snapshot_audit_v1"
        or backup_audit.get("integrity_check") != "ok"
        or backup_audit.get("foreign_key_violation_count") != 0
        or not isinstance(claimed_audit_hash, str)
        or claimed_audit_hash != canonical_sha256(audit_material)
    ):
        raise RemoteBackupCertificationError("REMOTE_BACKUP_BASELINE_AUDIT_INVALID")
    restored_path = _require_snapshot(restored_backup_path, label="RESTORED")
    try:
        restore_audit = audit_sqlite_snapshot(restored_path)
    except (BackupCertificationError, OSError) as error:
        raise RemoteBackupCertificationError("REMOTE_BACKUP_SQLITE_AUDIT_FAILED") from error
    mismatches = [
        field for field in _COMPARABLE_FIELDS if backup_audit[field] != restore_audit[field]
    ]
    if mismatches:
        raise RemoteBackupCertificationError(
            "REMOTE_RESTORE_AUDIT_MISMATCH:" + ",".join(mismatches)
        )

    assets = _validate_assets(remote_assets)
    validate_remote_encryption_evidence(
        encryption=encryption,
        backup_audit=backup_audit,
        remote_assets=assets,
    )
    trusted = _trusted_verification(remote_verification)
    if (
        trusted.repository != repository
        or trusted.release_id != release_id
        or trusted.tag_name != tag_name
        or trusted.private_repository is not True
        or trusted.asset_ids != {item["name"]: item["id"] for item in assets}
        or trusted.asset_sha256 != {item["name"]: item["sha256"] for item in assets}
    ):
        raise RemoteBackupCertificationError("REMOTE_BACKUP_VERIFICATION_MISMATCH")

    body = {
        "contract_version": "sqlite_remote_backup_certification_v1",
        "status": "BACKUP_RESTORE_CERTIFIED",
        "source_path": str(source_path),
        "source_identity": source_identity,
        "source_failure_domain": source_failure_domain,
        "destination_failure_domain": destination_failure_domain,
        "off_host_separation_enforced": True,
        "storage_kind": "github_private_release",
        "remote_repository": repository,
        "remote_release_id": release_id,
        "remote_tag_name": tag_name,
        "remote_assets": assets,
        "remote_verification": trusted.model_dump(mode="python"),
        "backup_started_at": backup_started_at,
        "backup_completed_at": backup_completed_at,

        "backup_audit": backup_audit,
        "restore_audit": restore_audit,
        "restore_matches_backup": True,
        "local_restore_path": str(restored_path),
        "encryption": encryption,
        "rollback_source_sha256": backup_audit["file_sha256"],
        "production_migration_authorized": False,
        "production_deployment_authorized": False,
    }
    return {**body, "certification_sha256": canonical_sha256(body)}
