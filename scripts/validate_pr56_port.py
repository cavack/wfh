#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = "d6a23c1f69794aac31b1dce5e5a07ea69b614585"
MERGE_HEAD = "ff462dfa186964a2180aa57611a4c6a2c0641bb3"
IMAGE = "waterfallhunter-waterfall-backend:pr56-port-validation"
ROOT = Path.cwd()


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("$ " + " ".join(args), flush=True)
    result = subprocess.run(args, text=True)
    if check and result.returncode != 0:
        print(f"COMMAND_FAILED_RC={result.returncode}")
        raise SystemExit(result.returncode)
    return result


def capture(args: list[str]) -> str:
    return subprocess.check_output(args, text=True).strip()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


print("=== PR56 PORT VALIDATION V2 ===", flush=True)
require(capture(["git", "rev-parse", "HEAD"]) == BASE, "ABORT_WRONG_HEAD")
require(capture(["git", "rev-parse", "MERGE_HEAD"]) == MERGE_HEAD, "ABORT_WRONG_MERGE_HEAD")
require(not capture(["git", "diff", "--name-only", "--diff-filter=U"]), "ABORT_UNMERGED_FILES")

print("=== BUILD VALIDATION IMAGE FROM CURRENT WORKTREE ===", flush=True)
build_date = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
run([
    "docker", "build",
    "-f", str(ROOT / "backend" / "Dockerfile"),
    "-t", IMAGE,
    "--build-arg", "VCS_REF=pr56-port-validation",
    "--build-arg", f"BUILD_DATE={build_date}",
    "--build-arg", "VERSION=pr56-port-validation",
    str(ROOT / "backend"),
])
print("VALIDATION_IMAGE_BUILD=PASS", flush=True)

print("=== REGENERATE WAVE1D CORPUS ===", flush=True)
run([
    "docker", "run", "--rm", "--user", "0:0",
    "--entrypoint", "/opt/venv/bin/python",
    "-e", "PYTHONPATH=/app/src:/project",
    "-v", f"{ROOT}:/project",
    "-w", "/project",
    IMAGE,
    "scripts/build_wave1d_semantics_corpus.py",
])
run(["git", "add", "backend/tests/golden/wave1d_semantics_corpus.json"])
print("CORPUS_GENERATE=PASS", flush=True)

common = [
    "docker", "run", "--rm", "--read-only",
    "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=128m",
    "--entrypoint", "/opt/venv/bin/python",
    "-e", "HOME=/tmp",
    "-e", "TMPDIR=/tmp",
    "-e", "LIVE_TRADING_ENABLED=false",
    "-e", "EXPERIMENTAL_PRETRIGGER_ENABLED=false",
    "-e", "TELEGRAM_TOKEN=",
    "-e", "TELEGRAM_CHAT_ID=",
    "-e", "TELEGRAM_SIGNAL_DELIVERY_ENABLED=false",
    "-e", "REGISTRY_DB_PATH=/tmp/waterfall_registry.db",
    "-e", "PYTHONPATH=/app/src:/project",
    "-v", f"{ROOT}:/project:ro",
    "-w", "/tmp",
    IMAGE,
]

targeted = [
    "/project/backend/tests/test_ai_veto.py",
    "/project/backend/tests/test_ai_advisory_critical_path.py",
    "/project/backend/tests/test_hunter_flush_semaphore.py",
    "/project/backend/tests/test_hunter_progress_semantics.py",
    "/project/backend/tests/test_hunter_error_logging.py",
    "/project/backend/tests/test_shutdown_hunter_drain.py",
    "/project/backend/tests/test_notifier_durable_outbox.py",
    "/project/backend/tests/test_telegram_signal_delivery_gate.py",
    "/project/backend/tests/test_telegram_delivery_activation.py",
    "/project/backend/tests/test_metrics_async_boundary.py",
    "/project/backend/tests/test_lifecycle_websocket_consistency.py",
    "/project/backend/tests/test_lbank_execution_lbank_regressions.py",
    "/project/backend/tests/test_lifecycle_v2_decision_clock.py",
    "/project/backend/tests/test_stale_trigger_safety.py",
    "/project/backend/tests/test_wave1d_corpus_generation.py",
]

print("=== TARGETED INTEGRATION TESTS ===", flush=True)
run(common + ["-m", "pytest", "-q", "-p", "no:cacheprovider", *targeted])
print("TARGETED_TESTS=PASS", flush=True)

print("=== FULL BACKEND TESTS ===", flush=True)
run(common + ["-m", "pytest", "-q", "-p", "no:cacheprovider", "/project/backend/tests"])
print("FULL_BACKEND_TESTS=PASS", flush=True)

print("=== RUNTIME PARITY ===", flush=True)
run([
    "docker", "run", "--rm", "--read-only",
    "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
    "--entrypoint", "/opt/venv/bin/python",
    "-e", "PYTHONPATH=/app/src:/project",
    "-v", f"{ROOT}:/project:ro",
    "-w", "/project",
    IMAGE,
    "scripts/verify_runtime_parity.py",
])
print("RUNTIME_PARITY=PASS", flush=True)

run(["git", "diff", "--cached", "--check"])
print("FINAL_DIFF_CHECK=PASS", flush=True)

frontend = capture(["git", "diff", "--cached", "--name-only"])
frontend_changed = [line for line in frontend.splitlines() if line.startswith("frontend/")]
require(not frontend_changed, "ABORT_FRONTEND_CHANGED")

print("=== CHANGED FILES ===", flush=True)
run(["git", "diff", "--cached", "--name-only"], check=False)
print("=== DIFF STAT ===", flush=True)
run(["git", "diff", "--cached", "--stat"], check=False)
print("PORT_VALIDATION_STATUS=PASS", flush=True)
print("DO_NOT_COMMIT_YET=YES", flush=True)
print("NO_PUSH=YES", flush=True)
print("NO_PRODUCTION_CHANGE=YES", flush=True)
