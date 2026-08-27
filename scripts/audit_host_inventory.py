#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path

DELETE = "DELETE_AFTER_CERTIFICATION"
KEEP = "KEEP"
PROTECTED = "PROTECTED"
REVIEW = "REVIEW"

CANONICAL_PATHS = {
    Path("/srv/waterfallhunter"),
    Path("/srv/waterfallhunter/app"),
    Path("/srv/waterfallhunter/data"),
    Path("/srv/waterfallhunter/backups"),
    Path("/srv/waterfallhunter/runtime"),
    Path("/etc/waterfallhunter"),
    Path("/etc/waterfallhunter/waterfallhunter.env"),
}
PROTECTED_PREFIXES = (
    Path("/root/.codex"), Path("/root/.vscode-server"),
    Path("/root/.vscode-server-insiders"), Path("/root/.claude"),
    Path("/root/.gemini"), Path("/root/.ssh"), Path("/home"),
)
EXACT_LEGACY_PATHS = {
    Path("/srv/wfh-worktrees"), Path("/srv/wfh-loq-dev"),
    Path("/srv/wfh-releases"), Path("/srv/wfh-release-backups"),
    Path("/srv/wfh-operator-scripts"), Path("/srv/wfh-agent-package.zip"),
    Path("/srv/waterfallhunter_backup.tar.gz"), Path("/root/github/wfh"),
    Path("/root/github/wfh-quarantine"), Path("/root/github/wfh-rewrite.git"),
    Path("/root/github/wfh-verify"), Path("/root/github/wfh-backup.git"),
}
LEGACY_ROOT_GLOBS = (
    "/root/wfh-*", "/root/codex-wfh-*", "/root/pr*-wfh-*",
)


def _within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def classify_path(path: Path) -> tuple[str, str]:
    path = Path(os.path.abspath(os.fspath(path)))
    if path in CANONICAL_PATHS:
        return KEEP, "canonical WaterfallHunter path"
    for protected in PROTECTED_PREFIXES:
        if path == protected or _within(path, protected):
            return PROTECTED, "general host/developer tooling is outside cleanup scope"
    if path in EXACT_LEGACY_PATHS:
        return DELETE, "known legacy WaterfallHunter artifact"
    if path.parent == Path("/root") and (path.name.startswith("wfh-") or path.name.startswith("codex-wfh-")):
        return DELETE, "known legacy WaterfallHunter root artifact"
    if path.parent == Path("/srv") and path.name.startswith("wfh-"):
        return DELETE, "known legacy WaterfallHunter srv artifact"
    return REVIEW, "not on canonical cleanup allowlist"


def classify_docker_resource(kind: str, name: str, labels: dict[str, str] | None = None) -> tuple[str, str]:
    labels = labels or {}
    project = labels.get("com.docker.compose.project", "")
    canonical_names = {
        "container": {"waterfall-backend", "waterfall-frontend", "waterfall-watchdog", "waterfall-prometheus", "waterfall-grafana"},
        "volume": {"waterfallhunter_data", "waterfallhunter_prometheus_data", "waterfallhunter_grafana_data", "waterfallhunter_alertmanager_data"},
        "network": {"waterfallhunter_edge", "waterfallhunter_application", "waterfallhunter_egress", "waterfallhunter_alerting"},
        "image": {
            "waterfallhunter-waterfall-backend:latest",
            "waterfallhunter-frontend:latest",
            "waterfallhunter-watchdog:latest",
        },
    }
    canonical_services = {
        "waterfall-backend", "frontend", "watchdog",
        "prometheus", "grafana", "alertmanager",
    }
    service = labels.get("com.docker.compose.service", "")
    if (
        name in canonical_names.get(kind, set())
        and (kind == "image" or project == "waterfallhunter")
    ) or (
        kind == "container"
        and project == "waterfallhunter"
        and service in canonical_services
    ):
        return KEEP, "canonical WaterfallHunter Docker resource"
    is_wfh = (
        name.startswith(("waterfall", "wfh-")) or "waterfallhunter" in name.lower()
        or project.startswith("waterfall") or bool(re.fullmatch(r"[0-9a-f]{40}", project))
        or (kind == "image" and name.startswith(("wfh-", "waterfallhunter-")))
    )
    if is_wfh:
        return DELETE, "legacy/orphan WaterfallHunter Docker resource"
    return REVIEW, "Docker resource not proven WaterfallHunter-owned"


def _size_bytes(path: Path) -> int:
    try:
        result = subprocess.run(["du", "-sb", str(path)], text=True, capture_output=True, check=False)
        if result.returncode == 0:
            return int(result.stdout.split()[0])
    except Exception:
        pass
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _path_entries() -> list[dict[str, object]]:
    candidates = set(EXACT_LEGACY_PATHS) | CANONICAL_PATHS
    for pattern in LEGACY_ROOT_GLOBS:
        candidates.update(Path("/").glob(pattern.lstrip("/")))
    entries: list[dict[str, object]] = []
    for path in sorted(candidates, key=lambda p: str(p)):
        if not path.exists() and not path.is_symlink():
            continue
        disposition, reason = classify_path(path)
        try:
            mtime = path.lstat().st_mtime
        except OSError:
            mtime = 0.0
        entries.append({
            "type": "path", "path_or_resource": str(path),
            "size_bytes": _size_bytes(path), "mtime": mtime,
            "disposition": disposition, "reason": reason,
        })
    return entries


def _docker_json(command: list[str]) -> list[dict[str, object]]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return []
    rows: list[dict[str, object]] = []
    for line in result.stdout.splitlines():
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
        except ValueError:
            continue
    return rows


def _docker_entries() -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    specs = {
        "container": ["docker", "ps", "-a", "--format", "{{json .}}"],
        "volume": ["docker", "volume", "ls", "--format", "{{json .}}"],
        "network": ["docker", "network", "ls", "--format", "{{json .}}"],
        "image": ["docker", "image", "ls", "--format", "{{json .}}"],
    }
    for kind, command in specs.items():
        for row in _docker_json(command):
            if kind == "image":
                repository = str(row.get("Repository") or "")
                tag = str(row.get("Tag") or "")
                name = f"{repository}:{tag}" if repository and tag and repository != "<none>" else ""
            else:
                name = str(row.get("Names") or row.get("Name") or "")
            if not name:
                continue
            inspect = subprocess.run(["docker", f"{kind}", "inspect", name] if kind not in {"container", "image"} else ["docker", "image", "inspect", name] if kind == "image" else ["docker", "inspect", name], text=True, capture_output=True, check=False)
            labels: dict[str, str] = {}
            if inspect.returncode == 0:
                try:
                    obj = json.loads(inspect.stdout)[0]
                    if kind in {"container", "image"}:
                        labels = obj.get("Config", {}).get("Labels", {})
                    else:
                        labels = obj.get("Labels", {})
                    labels = labels or {}
                except (ValueError, IndexError, TypeError):
                    labels = {}
            disposition, reason = classify_docker_resource(kind, name, labels)
            if disposition != REVIEW or "waterfall" in name.lower() or labels.get("com.docker.compose.project"):
                entries.append({
                    "type": f"docker-{kind}", "path_or_resource": name,
                    "size_bytes": 0, "mtime": 0.0, "disposition": disposition,
                    "reason": reason, "labels": labels,
                })
    return entries


def build_inventory() -> dict[str, object]:
    return {
        "inventory_version": "waterfallhunter_host_inventory_v1",
        "generated_at": time.time(),
        "entries": _path_entries() + _docker_entries(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory WaterfallHunter host artifacts without deleting anything.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inventory = build_inventory()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for entry in inventory["entries"]:
        counts[entry["disposition"]] = counts.get(entry["disposition"], 0) + 1
    print(json.dumps({"output": str(args.output), "counts": counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
