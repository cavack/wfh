#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPOSITORY_ROOT / "backend" / "src"))
from audit_host_inventory import DELETE, PROTECTED, classify_docker_resource, classify_path  # noqa: E402
from waterfallhunter.core.signal_metadata import canonical_sha256  # noqa: E402
from waterfallhunter.core.sqlite_backup_certification import (  # noqa: E402
    BackupCertificationError,
    audit_sqlite_snapshot,
)


def _load(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid JSON object: {path}")
    return data


def validate_release_certificate(path: Path) -> dict[str, object]:
    data = _load(path)
    sha = str(data.get("release_sha", ""))
    claimed = str(data.get("certificate_sha256", ""))
    material = {key: value for key, value in data.items() if key != "certificate_sha256"}
    evidence = data.get("evidence")
    core_revisions = evidence.get("core_revisions") if isinstance(evidence, dict) else None
    expected_core = {"waterfall-backend", "waterfall-frontend", "waterfall-watchdog"}
    if not (
        data.get("certificate_type") == "waterfallhunter_release_v1"
        and data.get("status") == "PASS"
        and _lower_hex(sha, 40)
        and _lower_hex(claimed, 64)
        and claimed == canonical_sha256(material)
        and data.get("production_healthy") is True
        and data.get("live_trading_enabled") is False
        and isinstance(evidence, dict)
        and evidence.get("healthy") is True
        and evidence.get("running_revision") == sha
        and evidence.get("checkout_revision") == sha
        and evidence.get("live_trading_enabled") is False
        and isinstance(core_revisions, dict)
        and set(core_revisions) == expected_core
        and all(revision == sha for revision in core_revisions.values())
    ):
        raise ValueError("release certificate is not a complete passing WaterfallHunter release certificate")
    return data


def _lower_hex(value: object, length: int) -> bool:
    text = str(value or "")
    return len(text) == length and all(character in "0123456789abcdef" for character in text)


def validate_db_certificate(path: Path) -> dict[str, object]:
    data = _load(path)
    digest = str(data.get("sha256", ""))
    source_revision = str(data.get("source_revision", ""))
    claimed_certificate_hash = str(data.get("certificate_sha256", ""))
    material = {key: value for key, value in data.items() if key != "certificate_sha256"}
    wrapped = data.get("sqlite_backup_certification")
    if not isinstance(wrapped, dict):
        raise ValueError("database certificate core certification missing")
    backup_audit = wrapped.get("backup_audit")
    if not isinstance(backup_audit, dict):
        raise ValueError("database certificate backup audit missing")
    wrapped_hash = str(wrapped.get("certification_sha256", ""))
    wrapped_material = {key: value for key, value in wrapped.items() if key != "certification_sha256"}
    backup_path = Path(str(data.get("backup_path") or ""))
    if not (
        data.get("certificate_type") == "waterfallhunter_db_backup_v1"
        and data.get("status") == "PASS"
        and _lower_hex(digest, 64)
        and _lower_hex(source_revision, 40)
        and _lower_hex(claimed_certificate_hash, 64)
        and claimed_certificate_hash == canonical_sha256(material)
        and data.get("device_separation_enforced") is False
        and data.get("independent_disaster_recovery") is False
        and data.get("source_volume_preserved_until_post_cutover") is True
        and str(data.get("integrity_check", "")).lower() == "ok"
        and backup_path.is_absolute()
        and wrapped.get("contract_version") == "sqlite_backup_certification_v1"
        and wrapped.get("status") == "BACKUP_RESTORE_CERTIFIED"
        and wrapped.get("restore_matches_backup") is True
        and wrapped.get("production_migration_authorized") is False
        and wrapped.get("production_deployment_authorized") is False
        and _lower_hex(wrapped_hash, 64)
        and wrapped_hash == canonical_sha256(wrapped_material)
        and str(wrapped.get("backup_path") or "") == str(backup_path)
        and str(backup_audit.get("file_sha256") or "") == digest
        and str(backup_audit.get("integrity_check") or "").lower() == "ok"
    ):
        raise ValueError("database certificate is not a complete passing WaterfallHunter backup certificate")
    try:
        current_audit = audit_sqlite_snapshot(backup_path)
    except (BackupCertificationError, OSError) as exc:
        raise ValueError("certified database backup is unreadable") from exc
    if (
        current_audit.get("audit_sha256") != backup_audit.get("audit_sha256")
        or current_audit.get("file_sha256") != digest
    ):
        raise ValueError("certified database backup no longer matches its certificate")
    return data


def _target_contains_certified_backup(target: Path, backup: Path) -> bool:
    target_path = target.resolve(strict=False)
    backup_path = backup.resolve(strict=False)
    return target_path == backup_path or target_path in backup_path.parents


def _validated_delete_entries(inventory: dict[str, object]) -> list[dict[str, object]]:
    entries = inventory.get("entries")
    if not isinstance(entries, list):
        raise ValueError("inventory entries missing")
    approved: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("disposition") != DELETE:
            continue
        kind = str(entry.get("type", ""))
        name = str(entry.get("path_or_resource", ""))
        if kind == "path":
            disposition, reason = classify_path(Path(name))
        elif kind.startswith("docker-"):
            resource_kind = kind.removeprefix("docker-")
            labels = entry.get("labels") if isinstance(entry.get("labels"), dict) else {}
            disposition, reason = classify_docker_resource(resource_kind, name, labels)
        else:
            raise ValueError(f"unknown cleanup entry type: {kind}")
        if disposition == PROTECTED:
            raise ValueError(f"protected cleanup target refused: {name}: {reason}")
        if disposition != DELETE:
            raise ValueError(f"cleanup target is not allowlisted: {name}: {reason}")
        approved.append(entry)
    return approved


def _delete_entry(entry: dict[str, object]) -> None:
    kind = str(entry["type"])
    name = str(entry["path_or_resource"])
    if kind == "path":
        path = Path(name)
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)
        return
    resource_kind = kind.removeprefix("docker-")
    command = {
        "container": ["docker", "rm", "-f", name],
        "volume": ["docker", "volume", "rm", name],
        "network": ["docker", "network", "rm", name],
        "image": ["docker", "image", "rm", name],
    }.get(resource_kind)
    if command is None:
        raise ValueError(f"unsupported Docker cleanup type: {resource_kind}")
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0 and "No such" not in (result.stderr + result.stdout):
        raise RuntimeError(f"Docker cleanup failed for {kind} {name}: {result.stderr.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete only certified, allowlisted legacy WaterfallHunter artifacts.")
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--release-certificate", type=Path)
    parser.add_argument("--db-certificate", type=Path)
    parser.add_argument("--certificate", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        inventory = _load(args.inventory)
        approved = _validated_delete_entries(inventory)
        if not args.execute:
            print(json.dumps({"mode": "dry-run", "delete_count": len(approved), "targets": [e["path_or_resource"] for e in approved]}, indent=2))
            return 0
        if args.release_certificate is None or args.db_certificate is None:
            raise ValueError("release certificate and database certificate are required for --execute")
        release = validate_release_certificate(args.release_certificate)
        db = validate_db_certificate(args.db_certificate)
        certified_backup = Path(str(db["backup_path"]))
        removed: list[dict[str, object]] = []
        for entry in approved:
            if entry.get("type") == "path" and _target_contains_certified_backup(
                Path(str(entry.get("path_or_resource") or "")),
                certified_backup,
            ):
                raise ValueError(
                    f"cleanup target contains certified database backup: {entry.get('path_or_resource')}"
                )
            _delete_entry(entry)
            removed.append({"type": entry["type"], "path_or_resource": entry["path_or_resource"]})
        certificate = {
            "certificate_type": "waterfallhunter_cleanup_v1",
            "status": "PASS",
            "completed_at": time.time(),
            "release_sha": release["release_sha"],
            "db_backup_sha256": db["sha256"],
            "inventory_sha256": hashlib.sha256(args.inventory.read_bytes()).hexdigest(),
            "removed": removed,
        }
        if args.certificate:
            args.certificate.parent.mkdir(parents=True, exist_ok=True)
            args.certificate.write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": "PASS", "removed": len(removed)}))
        return 0
    except Exception as exc:
        print(f"cleanup refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
