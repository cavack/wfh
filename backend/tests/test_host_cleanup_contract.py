from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "scripts/audit_host_inventory.py"
CLEANUP_PATH = ROOT / "scripts/cleanup_legacy_wfh.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audit_classification_protects_general_agent_tooling() -> None:
    audit = _load_module(AUDIT_PATH, "audit_host_inventory")
    assert audit.classify_path(Path("/root/.codex"))[0] == "PROTECTED"
    assert audit.classify_path(Path("/root/.vscode-server"))[0] == "PROTECTED"
    assert audit.classify_path(Path("/home/ubuntu/.ssh"))[0] == "PROTECTED"


def test_audit_classification_marks_known_legacy_wfh_roots_only() -> None:
    audit = _load_module(AUDIT_PATH, "audit_host_inventory_legacy")
    assert audit.classify_path(Path("/srv/wfh-worktrees"))[0] == "DELETE_AFTER_CERTIFICATION"
    assert audit.classify_path(Path("/root/wfh-v7-local-rollback"))[0] == "DELETE_AFTER_CERTIFICATION"
    assert audit.classify_path(Path("/srv/waterfallhunter/app"))[0] == "KEEP"
    assert audit.classify_path(Path("/srv/waterfallhunter/backups"))[0] == "KEEP"


def test_cleanup_refuses_unknown_path_even_if_inventory_marks_delete(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"entries": [{
        "type": "path",
        "path_or_resource": "/root/.codex",
        "disposition": "DELETE_AFTER_CERTIFICATION",
        "reason": "malicious fixture",
    }]}))
    release = tmp_path / "release.json"
    db = tmp_path / "db.json"
    release.write_text(json.dumps({
        "certificate_type": "waterfallhunter_release_v1", "status": "PASS",
        "release_sha": "a" * 40, "production_healthy": True,
        "live_trading_enabled": False,
    }))
    db.write_text(json.dumps({
        "certificate_type": "waterfallhunter_db_backup_v1", "status": "PASS",
        "sha256": "b" * 64, "integrity_check": "ok", "backup_path": "/safe/backup.db",
    }))
    result = subprocess.run([
        sys.executable, str(CLEANUP_PATH), "--inventory", str(inventory),
        "--release-certificate", str(release), "--db-certificate", str(db), "--execute",
    ], text=True, capture_output=True)
    assert result.returncode != 0
    assert "protected" in (result.stderr + result.stdout).lower()


def test_cleanup_requires_release_and_db_certificates(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"entries": []}))
    result = subprocess.run([
        sys.executable, str(CLEANUP_PATH), "--inventory", str(inventory), "--execute",
    ], text=True, capture_output=True)
    assert result.returncode != 0
    assert "certificate" in (result.stderr + result.stdout).lower()


def test_docker_image_classification_is_wfh_scoped() -> None:
    audit = _load_module(AUDIT_PATH, "audit_host_inventory_images")
    assert audit.classify_docker_resource("image", "wfh-rollback-backend:old", {})[0] == "DELETE_AFTER_CERTIFICATION"
    assert audit.classify_docker_resource("image", "waterfallhunter-waterfall-backend:latest", {})[0] == "KEEP"
    assert audit.classify_docker_resource("image", "python:3.13-slim", {})[0] == "REVIEW"
