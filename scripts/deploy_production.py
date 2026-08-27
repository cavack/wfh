from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

_APPLICATION_SERVICES = (
    "waterfall-backend",
    "frontend",
    "watchdog",
)
_CONTAINER_NAMES = (
    "waterfall-backend",
    "waterfall-frontend",
    "waterfall-watchdog",
)
_IMAGE_NAMES = {
    "waterfall-backend": "waterfallhunter-waterfall-backend",
    "frontend": "waterfallhunter-frontend",
    "watchdog": "waterfallhunter-watchdog",
}


class DeploymentError(RuntimeError):
    """Fail-closed deployment error safe to surface in CI logs."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    """Small subprocess boundary so deployment sequencing is unit-testable."""

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        check: bool = True,
    ) -> CommandResult:
        command = tuple(str(value) for value in args)
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
            )
        except (OSError, ValueError) as exc:
            raise DeploymentError(f"command could not start: {command[0]}") from exc

        result = CommandResult(
            returncode=int(completed.returncode),
            stdout=str(completed.stdout or ""),
            stderr=str(completed.stderr or ""),
        )
        if check and result.returncode != 0:
            rendered = " ".join(command[:4])
            raise DeploymentError(
                f"command failed ({result.returncode}): {rendered}"
            )
        return result


@dataclass(frozen=True, slots=True)
class DeploymentResult:
    target_sha: str
    previous_sha: str
    rolled_back: bool
    backend_image_id: str
    frontend_image_id: str
    watchdog_image_id: str


def _clean_output(value: str) -> str:
    return value.strip()


def _require_sha(value: str, *, label: str) -> str:
    candidate = str(value or "").strip()
    if not _SHA_RE.fullmatch(candidate):
        raise DeploymentError(f"{label} must be an exact 40-character target SHA")
    return candidate.lower()


def _parse_env_assignment(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[7:].lstrip()
    if "=" not in line:
        return None
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def _require_paper_only_env(repo_dir: Path) -> None:
    env_path = repo_dir / ".env"
    if not env_path.is_file() or env_path.is_symlink():
        raise DeploymentError(".env is missing or unsafe")
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DeploymentError(".env could not be read") from exc

    values: list[str] = []
    for raw_line in lines:
        parsed = _parse_env_assignment(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        if key == "LIVE_TRADING_ENABLED":
            values.append(value)

    if len(values) != 1 or values[0].lower() != "false":
        raise DeploymentError(
            "LIVE_TRADING_ENABLED must appear exactly once and equal false"
        )


def _require_clean_worktree(runner: CommandRunner, repo_dir: Path) -> None:
    status = runner.run(("git", "status", "--porcelain"), cwd=repo_dir)
    if _clean_output(status.stdout):
        raise DeploymentError("remote Git worktree is not clean")


def _fetch_and_require_exact_main(
    runner: CommandRunner,
    repo_dir: Path,
    target_sha: str,
) -> None:
    runner.run(("git", "fetch", "--prune", "origin", "main"), cwd=repo_dir)
    main_result = runner.run(("git", "rev-parse", "origin/main"), cwd=repo_dir)
    main_sha = _require_sha(_clean_output(main_result.stdout), label="origin/main SHA")
    if main_sha != target_sha:
        raise DeploymentError("target SHA does not equal current origin/main")


def _current_sha(runner: CommandRunner, repo_dir: Path) -> str:
    result = runner.run(("git", "rev-parse", "HEAD"), cwd=repo_dir)
    return _require_sha(_clean_output(result.stdout), label="current revision")


def _capture_image_ids(
    runner: CommandRunner,
    repo_dir: Path,
) -> dict[str, str]:
    image_ids: dict[str, str] = {}
    for service, image_name in _IMAGE_NAMES.items():
        result = runner.run(
            ("docker", "image", "inspect", image_name, "--format", "{{.Id}}"),
            cwd=repo_dir,
        )
        image_id = _clean_output(result.stdout)
        if not _IMAGE_ID_RE.fullmatch(image_id):
            raise DeploymentError(f"cannot identify rollback image for {service}")
        image_ids[service] = image_id
    return image_ids


def _restore_image_tags(
    runner: CommandRunner,
    repo_dir: Path,
    image_ids: dict[str, str],
) -> None:
    for service, image_name in _IMAGE_NAMES.items():
        runner.run(
            ("docker", "image", "tag", image_ids[service], image_name),
            cwd=repo_dir,
        )


def _commit_timestamp(
    runner: CommandRunner,
    repo_dir: Path,
    target_sha: str,
) -> str:
    result = runner.run(
        ("git", "show", "-s", "--format=%cI", target_sha),
        cwd=repo_dir,
    )
    timestamp = _clean_output(result.stdout)
    if not timestamp:
        raise DeploymentError("target commit timestamp is unavailable")
    return timestamp


def _build_target(
    runner: CommandRunner,
    repo_dir: Path,
    *,
    target_sha: str,
    build_date: str,
) -> None:
    runner.run(("docker", "compose", "config", "--quiet"), cwd=repo_dir)
    runner.run(
        (
            "docker",
            "compose",
            "build",
            "--build-arg",
            f"VCS_REF={target_sha}",
            "--build-arg",
            f"BUILD_DATE={build_date}",
            "--build-arg",
            "VERSION=main",
            *_APPLICATION_SERVICES,
        ),
        cwd=repo_dir,
    )


def _run_schema_preflight(runner: CommandRunner, repo_dir: Path) -> None:
    result = runner.run(
        (
            "docker",
            "compose",
            "run",
            "--rm",
            "--no-deps",
            "-e",
            "LIVE_TRADING_ENABLED=false",
            "waterfall-backend",
            "/opt/venv/bin/python",
            "-m",
            "waterfallhunter.migrate_database",
            "--preflight",
            "--db-path",
            "/app/data/waterfall_registry.db",
        ),
        cwd=repo_dir,
        check=False,
    )
    if result.returncode != 0:
        raise DeploymentError("migration preflight rejected the target revision")
    try:
        payload = json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise DeploymentError("migration preflight returned invalid JSON") from exc
    if payload.get("ok") is not True or payload.get("mode") != "preflight":
        raise DeploymentError("migration preflight did not report compatibility")


def _cutover(runner: CommandRunner, repo_dir: Path) -> None:
    runner.run(
        (
            "docker",
            "compose",
            "up",
            "-d",
            "--no-build",
            *_APPLICATION_SERVICES,
        ),
        cwd=repo_dir,
    )


def _health_status(
    runner: CommandRunner,
    repo_dir: Path,
    container: str,
) -> str:
    result = runner.run(
        (
            "docker",
            "inspect",
            "--format",
            "{{.State.Health.Status}}",
            container,
        ),
        cwd=repo_dir,
    )
    return _clean_output(result.stdout).lower()


def _wait_for_health(
    runner: CommandRunner,
    repo_dir: Path,
    *,
    timeout_seconds: int,
) -> None:
    timeout = max(0, int(timeout_seconds))
    deadline = time.monotonic() + timeout
    last_status: dict[str, str] = {}

    while True:
        all_healthy = True
        for container in _CONTAINER_NAMES:
            status = _health_status(runner, repo_dir, container)
            last_status[container] = status
            if status != "healthy":
                all_healthy = False
        if all_healthy:
            return
        if time.monotonic() >= deadline:
            rendered = ", ".join(
                f"{name}={status}" for name, status in sorted(last_status.items())
            )
            raise DeploymentError(f"application health deadline exceeded: {rendered}")
        time.sleep(min(2.0, max(0.05, deadline - time.monotonic())))


def _verify_revision_labels(
    runner: CommandRunner,
    repo_dir: Path,
    *,
    target_sha: str,
) -> None:
    template = '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
    for container in _CONTAINER_NAMES:
        result = runner.run(
            ("docker", "inspect", "--format", template, container),
            cwd=repo_dir,
        )
        observed = _clean_output(result.stdout).lower()
        if observed != target_sha:
            raise DeploymentError(
                f"running revision label mismatch for {container}"
            )


def _run_smoke_checks(runner: CommandRunner, repo_dir: Path) -> None:
    runner.run(
        (
            "docker",
            "exec",
            "waterfall-backend",
            "/opt/venv/bin/python",
            "-c",
            (
                "import urllib.request; "
                "urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5).read()"
            ),
        ),
        cwd=repo_dir,
    )
    runner.run(
        (
            "docker",
            "exec",
            "waterfall-frontend",
            "wget",
            "-q",
            "-T",
            "5",
            "-O",
            "/dev/null",
            "http://127.0.0.1:3000/dashboard/",
        ),
        cwd=repo_dir,
    )


def _rollback(
    runner: CommandRunner,
    repo_dir: Path,
    *,
    previous_sha: str,
    previous_image_ids: dict[str, str],
    cutover_started: bool,
    health_timeout_seconds: int,
) -> str | None:
    errors: list[str] = []
    try:
        _restore_image_tags(runner, repo_dir, previous_image_ids)
    except Exception as exc:  # noqa: BLE001 - rollback must continue best-effort
        errors.append(f"image tags: {exc}")
    try:
        runner.run(
            ("git", "checkout", "--detach", previous_sha),
            cwd=repo_dir,
        )
    except Exception as exc:  # noqa: BLE001 - rollback must continue best-effort
        errors.append(f"git revision: {exc}")

    if cutover_started:
        try:
            _cutover(runner, repo_dir)
            _wait_for_health(
                runner,
                repo_dir,
                timeout_seconds=max(30, health_timeout_seconds),
            )
        except Exception as exc:  # noqa: BLE001 - report rollback failure
            errors.append(f"application restart: {exc}")

    return "; ".join(errors) if errors else None


def deploy(
    *,
    target_sha: str,
    repo_dir: Path,
    runner: CommandRunner,
    health_timeout_seconds: int = 120,
) -> DeploymentResult:
    """Deploy one exact main revision without applying a Production migration."""
    normalized_target = _require_sha(target_sha, label="target SHA")
    repo_dir = Path(repo_dir).resolve()
    if not repo_dir.is_dir():
        raise DeploymentError("repository directory does not exist")

    _require_clean_worktree(runner, repo_dir)
    _fetch_and_require_exact_main(runner, repo_dir, normalized_target)
    _require_paper_only_env(repo_dir)

    previous_sha = _current_sha(runner, repo_dir)
    previous_image_ids = _capture_image_ids(runner, repo_dir)
    build_date = _commit_timestamp(runner, repo_dir, normalized_target)
    cutover_started = False

    try:
        runner.run(
            ("git", "checkout", "--detach", normalized_target),
            cwd=repo_dir,
        )
        _build_target(
            runner,
            repo_dir,
            target_sha=normalized_target,
            build_date=build_date,
        )
        _run_schema_preflight(runner, repo_dir)
        target_image_ids = _capture_image_ids(runner, repo_dir)

        _cutover(runner, repo_dir)
        cutover_started = True
        _wait_for_health(
            runner,
            repo_dir,
            timeout_seconds=health_timeout_seconds,
        )
        _verify_revision_labels(
            runner,
            repo_dir,
            target_sha=normalized_target,
        )
        _run_smoke_checks(runner, repo_dir)

        return DeploymentResult(
            target_sha=normalized_target,
            previous_sha=previous_sha,
            rolled_back=False,
            backend_image_id=target_image_ids["waterfall-backend"],
            frontend_image_id=target_image_ids["frontend"],
            watchdog_image_id=target_image_ids["watchdog"],
        )
    except Exception as exc:  # noqa: BLE001 - one fail-closed rollback boundary
        rollback_error = _rollback(
            runner,
            repo_dir,
            previous_sha=previous_sha,
            previous_image_ids=previous_image_ids,
            cutover_started=cutover_started,
            health_timeout_seconds=health_timeout_seconds,
        )
        detail = str(exc) if isinstance(exc, DeploymentError) else exc.__class__.__name__
        if rollback_error:
            raise DeploymentError(
                f"deployment failed: {detail}; rollback incomplete: {rollback_error}"
            ) from exc
        raise DeploymentError(f"deployment failed: {detail}; rollback completed") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deploy an exact PAPER_ONLY WaterfallHunter main revision safely."
    )
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--repo-dir", required=True)
    parser.add_argument("--health-timeout-seconds", type=int, default=120)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        result = deploy(
            target_sha=args.target_sha,
            repo_dir=Path(args.repo_dir),
            runner=CommandRunner(),
            health_timeout_seconds=args.health_timeout_seconds,
        )
    except DeploymentError as exc:
        print(f"deployment_error={exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "target_sha": result.target_sha,
                "previous_sha": result.previous_sha,
                "rolled_back": result.rolled_back,
                "backend_image_id": result.backend_image_id,
                "frontend_image_id": result.frontend_image_id,
                "watchdog_image_id": result.watchdog_image_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
