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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_host_inventory import DELETE, PROTECTED, classify_docker_resource, classify_path  # noqa: E402


def _load(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid JSON object: {path}")
    return data


def validate_release_certificate(path: Path) -> dict[str, object]:
    data = _load(path)
    sha = str(data.get("release_sha", ""))
    if not (
        data.get("certificate_type") == "waterfallhunter_release_v1"
        and data.get("status") == "PASS"
        and len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)
        and data.get("production_healthy") is True
        and data.get("live_trading_enabled") is False
    ):
        raise ValueError("release certificate is not a passing WaterfallHunter release certificate")
    return data


def validate_db_certificate(path: Path) -> dict[str, object]:
    data = _load(path)
    digest = str(data.get("sha256", ""))
    if not (
        data.get("certificate_type") == "waterfallhunter_db_backup_v1"
        and data.get("status") == "PASS"
        and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
        and str(data.get("integrity_check", "")).lower() == "ok"
        and data.get("backup_path")
    ):
        raise ValueError("database certificate is not a passing WaterfallHunter backup certificate")
    return data


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
        removed: list[dict[str, object]] = []
        for entry in approved:
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
