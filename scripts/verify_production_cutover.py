#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

REQUIRED_SERVICES = (
    "waterfall-backend", "frontend", "watchdog",
    "prometheus", "grafana", "alertmanager",
)
CORE_CONTAINERS = ("waterfall-backend", "waterfall-frontend", "waterfall-watchdog")
FAILURES_BEFORE_RECOVERY = 3
RECOVERY_COOLDOWN_SECONDS = 600
MAX_RECOVERIES_PER_HOUR = 3


def _compose_files(project_dir: Path) -> list[str]:
    files = [str(project_dir / "docker-compose.yml")]
    override = project_dir.parent / "runtime" / "production-volumes.override.yml"
    if override.is_file():
        files.append(str(override))
    return files


def _compose(project_dir: Path, env_file: Path, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        "/usr/bin/docker", "compose", "--project-name", "waterfallhunter",
        "--env-file", str(env_file),
    ]
    for compose_file in _compose_files(project_dir):
        cmd.extend(("-f", compose_file))
    cmd.extend(args)
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


def _backend_endpoint(project_dir: Path, env_file: Path, path: str) -> bool:
    code = (
        "import urllib.request; "
        f"urllib.request.urlopen('http://127.0.0.1:8000{path}', timeout=5).read(); "
        "print('OK')"
    )
    result = _compose(
        project_dir, env_file, "exec", "-T", "waterfall-backend",
        "/opt/venv/bin/python", "-c", code,
    )
    return result.returncode == 0 and result.stdout.strip().endswith("OK")


def _container_revision(container: str) -> str | None:
    result = subprocess.run(
        [
            "/usr/bin/docker", "inspect", "--format",
            '{{ index .Config.Labels "org.opencontainers.image.revision" }}',
            container,
        ],
        text=True, capture_output=True, check=False,
    )
    revision = result.stdout.strip()
    return revision if result.returncode == 0 and _is_git_sha(revision) else None


def _running_revisions() -> dict[str, str | None]:
    return {container: _container_revision(container) for container in CORE_CONTAINERS}


def _running_revision() -> str | None:
    return _container_revision("waterfall-backend")


def _checkout_revision(project_dir: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_dir, text=True, capture_output=True, check=False,
    )
    revision = result.stdout.strip()
    return revision if result.returncode == 0 and _is_git_sha(revision) else None


def _live_trading_enabled(project_dir: Path, env_file: Path) -> bool | None:
    result = _compose(
        project_dir, env_file, "exec", "-T", "waterfall-backend",
        "/opt/venv/bin/python", "-c",
        "from waterfallhunter.config import settings; print('true' if settings.live_trading_enabled else 'false')",
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _is_git_sha(value: object) -> bool:
    text = str(value or "")
    return len(text) == 40 and all(character in "0123456789abcdef" for character in text)


def _canonical_sha256(value: dict[str, object]) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def release_evidence_snapshot(project_dir: Path, env_file: Path) -> dict[str, object]:
    snapshot = health_snapshot(project_dir, env_file)
    endpoints = {
        path: _backend_endpoint(project_dir, env_file, path)
        for path in ("/livez", "/readyz", "/healthz")
    }
    core_revisions = _running_revisions()
    running_revision = core_revisions.get("waterfall-backend")
    checkout_revision = _checkout_revision(project_dir)
    live_trading_enabled = _live_trading_enabled(project_dir, env_file)
    snapshot.update(
        backend_endpoints=endpoints,
        running_revision=running_revision,
        core_revisions=core_revisions,
        checkout_revision=checkout_revision,
        live_trading_enabled=live_trading_enabled,
    )
    snapshot["healthy"] = bool(
        snapshot.get("healthy") is True
        and all(endpoints.values())
        and checkout_revision is not None
        and all(revision == checkout_revision for revision in core_revisions.values())
        and live_trading_enabled is False
    )
    return snapshot


def build_release_certificate(
    snapshot: dict[str, object], *, generated_at: int
) -> dict[str, object]:
    running_revision = str(snapshot.get("running_revision") or "")
    checkout_revision = str(snapshot.get("checkout_revision") or "")
    endpoints = snapshot.get("backend_endpoints")
    endpoints_ok = isinstance(endpoints, dict) and all(
        endpoints.get(path) is True for path in ("/livez", "/readyz", "/healthz")
    )
    core_revisions = snapshot.get("core_revisions")
    core_revisions_ok = bool(
        isinstance(core_revisions, dict)
        and set(core_revisions) == set(CORE_CONTAINERS)
        and all(
            _is_git_sha(revision) and str(revision) == checkout_revision
            for revision in core_revisions.values()
        )
    )
    if not (
        snapshot.get("healthy") is True
        and _is_git_sha(running_revision)
        and running_revision == checkout_revision
        and core_revisions_ok
        and snapshot.get("live_trading_enabled") is False
        and endpoints_ok
    ):
        raise ValueError("release evidence is incomplete or inconsistent")
    body: dict[str, object] = {
        "certificate_type": "waterfallhunter_release_v1",
        "status": "PASS",
        "release_sha": running_revision,
        "certified_at": int(generated_at),
        "production_healthy": True,
        "live_trading_enabled": False,
        "evidence": snapshot,
    }
    return {**body, "certificate_sha256": _canonical_sha256(body)}


def _write_release_certificate(path: Path, certificate: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o640)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(certificate, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


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
    parser.add_argument(
        "--release-certificate", type=Path,
        help="Write an exact-running-SHA release certificate after deep runtime checks pass.",
    )
    args = parser.parse_args()
    if not args.project_dir.is_dir() or not args.env_file.is_file():
        print(json.dumps({"healthy": False, "reason": "missing_project_or_env"}))
        return 2
    if args.release_certificate is not None and args.recover:
        print(json.dumps({"healthy": False, "reason": "release_certificate_disallows_recovery"}))
        return 2
    snapshot = (
        release_evidence_snapshot(args.project_dir, args.env_file)
        if args.release_certificate is not None
        else health_snapshot(args.project_dir, args.env_file)
    )
    if args.recover:
        ok, reason = maybe_recover(args.project_dir, args.env_file, args.state_file, snapshot)
        snapshot["recovery"] = reason
        snapshot["healthy"] = ok
    if args.release_certificate is not None:
        try:
            certificate = build_release_certificate(snapshot, generated_at=int(time.time()))
            _write_release_certificate(args.release_certificate, certificate)
            snapshot["release_certificate"] = str(args.release_certificate)
            snapshot["release_sha"] = certificate["release_sha"]
        except (OSError, ValueError) as exc:
            snapshot["healthy"] = False
            snapshot["release_certificate_error"] = str(exc)
    print(json.dumps(snapshot, sort_keys=True))
    return 0 if snapshot["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
