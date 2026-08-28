#!/usr/bin/env python3
"""Create an encrypted off-host GitHub Release backup and restore certificate."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

WFH_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WFH_REPOSITORY_ROOT))
sys.path.insert(0, str(WFH_REPOSITORY_ROOT / "backend" / "src"))

TRUSTED_KEY_ROOT = Path("/root/.wfh-dr")
TRUSTED_KEY_NAME = "wfh-dr-aes256.key"

from scripts.certify_sqlite_backup import _canonical_absolute_path, _write_report_atomic
from waterfallhunter.core.github_release_backup_verification import (
    TrustedRemoteBackupVerificationError,
    resolve_github_release_backup_verification,
)
from waterfallhunter.core.remote_backup_bundle import (
    RemoteBackupBundleError,
    encrypt_sqlite_backup_bundle,
    restore_sqlite_backup_bundle,
)
from waterfallhunter.core.remote_backup_certification import (
    RemoteBackupCertificationError,
    build_remote_backup_certification,
)
from waterfallhunter.core.sqlite_backup_certification import (
    BackupCertificationError,
    _online_backup,
    audit_sqlite_snapshot,
)


class RemoteBackupCLIError(RuntimeError):
    """Raised when orchestration of the off-host backup fails closed."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repository(value: str) -> str:
    parts = value.split("/")
    if len(parts) != 2 or not all(parts) or any(".." in part for part in parts):
        raise argparse.ArgumentTypeError("repository must be owner/name")
    return value


def _tag(value: str) -> str:
    if not value or any(character.isspace() for character in value) or "/" in value:
        raise argparse.ArgumentTypeError("release tag contains unsupported characters")
    return value


def _load_key(path: Path) -> bytes:
    try:
        trusted_root = TRUSTED_KEY_ROOT.resolve(strict=True)
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise RemoteBackupCLIError("REMOTE_BACKUP_KEY_FILE_INVALID") from error
    if (
        not path.is_absolute()
        or path.is_symlink()
        or resolved != path
        or resolved.parent != trusted_root
        or resolved.name != TRUSTED_KEY_NAME
        or not resolved.is_file()
    ):
        raise RemoteBackupCLIError("REMOTE_BACKUP_KEY_FILE_INVALID")
    stat_result = resolved.stat()
    if stat_result.st_uid != 0 or stat_result.st_mode & 0o077:
        raise RemoteBackupCLIError("REMOTE_BACKUP_KEY_FILE_PERMISSIONS_INVALID")
    try:
        key = base64.b64decode(resolved.read_text(encoding="ascii").strip(), validate=True)
    except (OSError, ValueError) as error:
        raise RemoteBackupCLIError("REMOTE_BACKUP_KEY_INVALID") from error
    if len(key) != 32:
        raise RemoteBackupCLIError("REMOTE_BACKUP_KEY_INVALID")
    return key


def _gh(*arguments: str, timeout: int = 120) -> str:
    executable = Path("/usr/bin/gh")
    if not executable.is_file() or executable.is_symlink():
        raise RemoteBackupCLIError("GITHUB_CLI_UNAVAILABLE_OR_UNTRUSTED")
    try:
        completed = subprocess.run(
            [str(executable), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RemoteBackupCLIError("REMOTE_BACKUP_GITHUB_COMMAND_FAILED") from error
    return completed.stdout


def _gh_json(endpoint: str) -> dict[str, Any]:
    try:
        value = json.loads(_gh("api", endpoint, timeout=60))
    except json.JSONDecodeError as error:
        raise RemoteBackupCLIError("REMOTE_BACKUP_GITHUB_RESPONSE_INVALID") from error
    if not isinstance(value, dict):
        raise RemoteBackupCLIError("REMOTE_BACKUP_GITHUB_RESPONSE_INVALID")
    return value


def _assert_private_repository(repository: str) -> None:
    payload = _gh_json(f"repos/{repository}")
    if (
        payload.get("full_name") != repository
        or payload.get("private") is not True
        or payload.get("archived") is True
    ):
        raise RemoteBackupCLIError("REMOTE_BACKUP_REPOSITORY_NOT_PRIVATE")
    default_branch = payload.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        raise RemoteBackupCLIError("REMOTE_BACKUP_REPOSITORY_UNINITIALIZED")


def _asset_material(paths: list[Path]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in paths:
        result[path.name] = {
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
    return result


def _release_assets(
    *,
    repository: str,
    tag_name: str,
    expected: dict[str, dict[str, Any]],
) -> tuple[int, list[dict[str, Any]]]:
    release = _gh_json(f"repos/{repository}/releases/tags/{tag_name}")
    release_id = release.get("id")
    assets = release.get("assets")
    if not isinstance(release_id, int) or isinstance(release_id, bool) or release_id < 1:
        raise RemoteBackupCLIError("REMOTE_BACKUP_RELEASE_ID_INVALID")
    if release.get("draft") is not False or release.get("prerelease") is not False:
        raise RemoteBackupCLIError("REMOTE_BACKUP_RELEASE_NOT_PUBLISHED")
    if not isinstance(assets, list):
        raise RemoteBackupCLIError("REMOTE_BACKUP_RELEASE_ASSETS_INVALID")

    by_name = {
        str(item.get("name")): item
        for item in assets
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if set(by_name) != set(expected):
        raise RemoteBackupCLIError("REMOTE_BACKUP_RELEASE_ASSET_SET_MISMATCH")
    result: list[dict[str, Any]] = []
    for name, local in sorted(expected.items()):
        item = by_name[name]
        digest = item.get("digest")
        asset_id = item.get("id")
        if (
            not isinstance(asset_id, int)
            or isinstance(asset_id, bool)
            or asset_id < 1
            or item.get("state") != "uploaded"
            or item.get("size") != local["size_bytes"]
            or digest != f"sha256:{local['sha256']}"
        ):
            raise RemoteBackupCLIError("REMOTE_BACKUP_RELEASE_ASSET_MISMATCH")
        result.append(
            {
                "name": name,
                "id": asset_id,
                "size_bytes": local["size_bytes"],
                "sha256": local["sha256"],
            }
        )
    return release_id, result


def _remove_files(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def _safe_unlink_staging_artifact(
    path: Path,
    *,
    staging_dir: Path,
    allowed_names: set[str],
) -> None:
    try:
        root = staging_dir.resolve(strict=True)
        candidate = path.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise RemoteBackupCLIError("REMOTE_BACKUP_CLEANUP_PATH_INVALID") from error
    if (
        staging_dir.is_symlink()
        or path.is_symlink()
        or candidate.parent != root
        or path.name not in allowed_names
    ):
        raise RemoteBackupCLIError("REMOTE_BACKUP_CLEANUP_PATH_INVALID")
    candidate.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create an encrypted GitHub Release DR backup and prove re-download/restore."
    )
    parser.add_argument("--source", required=True, type=_canonical_absolute_path)
    parser.add_argument("--staging-dir", required=True, type=_canonical_absolute_path)
    parser.add_argument("--restore-target", required=True, type=_canonical_absolute_path)
    parser.add_argument("--report", required=True, type=_canonical_absolute_path)
    parser.add_argument("--key-file", required=True, type=_canonical_absolute_path)
    parser.add_argument("--remote-repository", required=True, type=_repository)
    parser.add_argument("--release-tag", required=True, type=_tag)
    parser.add_argument("--source-failure-domain", required=True)
    parser.add_argument("--destination-failure-domain", required=True)
    parser.add_argument("--max-chunk-bytes", type=int, default=1_500_000_000)
    args = parser.parse_args()

    if not args.staging_dir.is_dir() or args.staging_dir.is_symlink():
        parser.error("staging directory must already exist and be non-symlinked")
    if args.restore_target.parent != args.staging_dir:
        parser.error("restore target must be directly inside staging directory")
    if args.report.parent != args.staging_dir:
        parser.error("report must be directly inside staging directory")
    if args.restore_target.exists() or args.report.exists():
        parser.error("restore target and report must not already exist")

    staging_snapshot = args.staging_dir / "remote-staging-backup.db"
    bundle_dir = args.staging_dir / "encrypted-upload"
    download_dir = args.staging_dir / "remote-download"
    if any(path.exists() or path.is_symlink() for path in (staging_snapshot, bundle_dir, download_dir)):
        parser.error("staging artifacts already exist")

    release_created = False
    release_published = False
    success = False
    try:
        key = _load_key(args.key_file)
        _assert_private_repository(args.remote_repository)
        if args.source_failure_domain == args.destination_failure_domain:
            raise RemoteBackupCLIError("FAILURE_DOMAIN_NOT_INDEPENDENT")
        bundle_dir.mkdir(mode=0o700)
        backup_started_at = int(time.time())
        source_identity = _online_backup(args.source, staging_snapshot)
        backup_completed_at = int(time.time())
        backup_audit = audit_sqlite_snapshot(staging_snapshot)
        manifest = encrypt_sqlite_backup_bundle(
            source=staging_snapshot,
            output_dir=bundle_dir,
            prefix="waterfall_registry",
            key=key,
            max_chunk_bytes=args.max_chunk_bytes,
        )
        if (
            manifest.get("plaintext_sha256") != backup_audit.get("file_sha256")
            or manifest.get("plaintext_size_bytes") != backup_audit.get("file_size_bytes")
        ):
            raise RemoteBackupCLIError("REMOTE_BACKUP_ENCRYPTED_PLAINTEXT_IDENTITY_MISMATCH")
        manifest_path = bundle_dir / "waterfall_registry.manifest.json"
        upload_paths = [
            manifest_path,
            *[bundle_dir / item["name"] for item in manifest["chunks"]],
        ]
        local_assets = _asset_material(upload_paths)

        _gh(
            "release",
            "create",
            args.release_tag,
            "--repo",
            args.remote_repository,
            "--draft",
            "--title",
            f"WaterfallHunter DR {args.release_tag}",
            "--notes",
            "Encrypted off-host SQLite disaster-recovery backup. No plaintext database is stored in this release.",
            timeout=120,
        )
        release_created = True
        _gh(
            "release",
            "upload",
            args.release_tag,
            *[str(path) for path in upload_paths],
            "--repo",
            args.remote_repository,
            timeout=21_600,
        )
        _gh(
            "release",
            "edit",
            args.release_tag,
            "--repo",
            args.remote_repository,
            "--draft=false",
            timeout=120,
        )
        release_published = True

        release_id, remote_assets = _release_assets(
            repository=args.remote_repository,
            tag_name=args.release_tag,
            expected=local_assets,
        )
        trusted_remote = resolve_github_release_backup_verification(
            repository=args.remote_repository,
            release_id=release_id,
            tag_name=args.release_tag,
            expected_assets=remote_assets,
        )

        _remove_files(upload_paths)
        bundle_dir.rmdir()
        # Off-host publication is now independently verified. Retire the local
        # plaintext staging copy before re-download so disk peak stays bounded.
        _safe_unlink_staging_artifact(
            staging_snapshot,
            staging_dir=args.staging_dir,
            allowed_names={"remote-staging-backup.db"},
        )
        download_dir.mkdir(mode=0o700)
        _gh(
            "release",
            "download",
            args.release_tag,
            "--repo",
            args.remote_repository,
            "--dir",
            str(download_dir),
            timeout=21_600,
        )
        downloaded_manifest = download_dir / manifest_path.name
        if (
            not downloaded_manifest.is_file()
            or _sha256_file(downloaded_manifest) != local_assets[manifest_path.name]["sha256"]
        ):
            raise RemoteBackupCLIError("REMOTE_BACKUP_REDOWNLOAD_MANIFEST_MISMATCH")

        restore_sqlite_backup_bundle(
            manifest_path=downloaded_manifest,
            bundle_dir=download_dir,
            target=args.restore_target,
            key=key,
        )
        encryption = {
            "algorithm": "AES-256-GCM",
            "compression": "zlib",
            "manifest_asset_name": manifest_path.name,
            "manifest_sha256": local_assets[manifest_path.name]["sha256"],
            "plaintext_sha256": manifest["plaintext_sha256"],
            "ciphertext_sha256": manifest["ciphertext_sha256"],
            "chunk_count": len(manifest["chunks"]),
        }
        report = build_remote_backup_certification(
            source=args.source,
            source_identity=source_identity,
            source_failure_domain=args.source_failure_domain,
            destination_failure_domain=args.destination_failure_domain,
            backup_audit=backup_audit,
            restored_backup_path=args.restore_target,
            repository=args.remote_repository,
            release_id=release_id,
            tag_name=args.release_tag,
            remote_assets=remote_assets,
            remote_verification=trusted_remote,
            backup_started_at=backup_started_at,
            backup_completed_at=backup_completed_at,
            encryption=encryption,
        )
        _write_report_atomic(
            args.report,
            report,
            allowed_directory=args.staging_dir,
        )
        success = True
        print(
            json.dumps(
                {
                    "ok": True,
                    "status": report["status"],
                    "certification_sha256": report["certification_sha256"],
                    "remote_repository": args.remote_repository,
                    "remote_release_id": release_id,
                    "remote_tag_name": args.release_tag,
                    "report": str(args.report),
                    "local_restore_path": str(args.restore_target),
                    "production_migration_authorized": False,
                    "production_deployment_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (
        BackupCertificationError,
        RemoteBackupBundleError,
        RemoteBackupCertificationError,
        RemoteBackupCLIError,
        TrustedRemoteBackupVerificationError,
        OSError,
    ) as error:
        if release_created and not release_published:
            try:
                _gh(
                    "release",
                    "delete",
                    args.release_tag,
                    "--repo",
                    args.remote_repository,
                    "--yes",
                    "--cleanup-tag",
                    timeout=120,
                )
            except RemoteBackupCLIError:
                pass
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": str(error),
                    "published_remote_release_preserved": release_published,
                    "remote_repository": args.remote_repository,
                    "remote_tag_name": args.release_tag,
                },
                sort_keys=True,
            )
        )
        return 2
    finally:
        _safe_unlink_staging_artifact(
            staging_snapshot,
            staging_dir=args.staging_dir,
            allowed_names={"remote-staging-backup.db"},
        )
        if bundle_dir.exists() and not bundle_dir.is_symlink():
            shutil.rmtree(bundle_dir, ignore_errors=True)
        if download_dir.exists() and not download_dir.is_symlink():
            shutil.rmtree(download_dir, ignore_errors=True)
        if not success:
            _safe_unlink_staging_artifact(
                args.restore_target,
                staging_dir=args.staging_dir,
                allowed_names={args.restore_target.name},
            )


if __name__ == "__main__":
    raise SystemExit(main())
