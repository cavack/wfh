#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.request
from pathlib import Path

REQUIRED_SERVICES = (
    "waterfall-backend", "frontend", "watchdog",
    "prometheus", "grafana", "alertmanager",
)
FAILURES_BEFORE_RECOVERY = 3
RECOVERY_COOLDOWN_SECONDS = 600
MAX_RECOVERIES_PER_HOUR = 3


def _compose(project_dir: Path, env_file: Path, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        "/usr/bin/docker", "compose", "--project-name", "waterfallhunter",
        "--env-file", str(env_file), "-f", str(project_dir / "docker-compose.yml"),
        *args,
    ]
    return subprocess.run(cmd, cwd=project_dir, text=True, capture_output=True, check=False)


def _service_health(project_dir: Path, env_file: Path, service: str) -> tuple[bool, str]:
    cid = _compose(project_dir, env_file, "ps", "-q", service)
    container_id = cid.stdout.strip()
    if cid.returncode != 0 or not container_id:
        return False, "missing"
    inspect = subprocess.run(
        ["/usr/bin/docker", "inspect", "--format", "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}", container_id],
        text=True, capture_output=True, check=False,
    )
    state = inspect.stdout.strip()
    if inspect.returncode != 0:
        return False, "inspect_failed"
    runtime, _, health = state.partition("|")
    if runtime != "running":
        return False, runtime or "not_running"
    if health not in {"healthy", "none"}:
        return False, health
    return True, health


def health_snapshot(project_dir: Path, env_file: Path) -> dict[str, object]:
    services: dict[str, str] = {}
    healthy = True
    for service in REQUIRED_SERVICES:
        ok, status = _service_health(project_dir, env_file, service)
        services[service] = status
        healthy = healthy and ok
    frontend_http = False
    try:
        with urllib.request.urlopen("http://127.0.0.1:3000/dashboard/", timeout=5) as response:
            frontend_http = 200 <= response.status < 400
    except Exception:
        frontend_http = False
    healthy = healthy and frontend_http
    return {"healthy": healthy, "services": services, "frontend_http": frontend_http}


def _load_state(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {"consecutive_failures": 0, "recoveries": [], "last_recovery_at": 0.0}


def _save_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def maybe_recover(project_dir: Path, env_file: Path, state_file: Path, snapshot: dict[str, object]) -> tuple[bool, str]:
    now = time.time()
    state = _load_state(state_file)
    recoveries = [float(x) for x in state.get("recoveries", []) if now - float(x) < 3600]
    if bool(snapshot["healthy"]):
        state.update(consecutive_failures=0, recoveries=recoveries)
        _save_state(state_file, state)
        return True, "healthy"
    failures = int(state.get("consecutive_failures", 0)) + 1
    last = float(state.get("last_recovery_at", 0.0))
    state.update(consecutive_failures=failures, recoveries=recoveries)
    if failures < FAILURES_BEFORE_RECOVERY:
        _save_state(state_file, state)
        return False, f"failure_{failures}_of_{FAILURES_BEFORE_RECOVERY}"
    if now - last < RECOVERY_COOLDOWN_SECONDS:
        _save_state(state_file, state)
        return False, "cooldown"
    if len(recoveries) >= MAX_RECOVERIES_PER_HOUR:
        _save_state(state_file, state)
        return False, "recovery_budget_exhausted"
    result = _compose(project_dir, env_file, "up", "-d", "--remove-orphans")
    if result.returncode != 0:
        _save_state(state_file, state)
        return False, "recovery_command_failed"
    recoveries.append(now)
    state.update(consecutive_failures=0, recoveries=recoveries, last_recovery_at=now)
    _save_state(state_file, state)
    time.sleep(5)
    recovered = health_snapshot(project_dir, env_file)
    return bool(recovered["healthy"]), "recovered" if recovered["healthy"] else "recovery_unhealthy"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the canonical WaterfallHunter production runtime.")
    parser.add_argument("--health-only", action="store_true", help="Run runtime health checks only.")
    parser.add_argument("--recover", action="store_true", help="Allow bounded Compose recovery after repeated failures.")
    parser.add_argument("--project-dir", type=Path, default=Path("/srv/waterfallhunter/app"))
    parser.add_argument("--env-file", type=Path, default=Path("/etc/waterfallhunter/waterfallhunter.env"))
    parser.add_argument("--state-file", type=Path, default=Path("/srv/waterfallhunter/runtime/healthcheck-state.json"))
    args = parser.parse_args()
    if not args.project_dir.is_dir() or not args.env_file.is_file():
        print(json.dumps({"healthy": False, "reason": "missing_project_or_env"}))
        return 2
    snapshot = health_snapshot(args.project_dir, args.env_file)
    if args.recover:
        ok, reason = maybe_recover(args.project_dir, args.env_file, args.state_file, snapshot)
        snapshot["recovery"] = reason
        snapshot["healthy"] = ok
    print(json.dumps(snapshot, sort_keys=True))
    return 0 if snapshot["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
