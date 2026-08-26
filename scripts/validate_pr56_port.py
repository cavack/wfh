#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BASE = "d6a23c1f69794aac31b1dce5e5a07ea69b614585"
MERGE_HEAD = "ff462dfa186964a2180aa57611a4c6a2c0641bb3"
IMAGE = "waterfallhunter-waterfall-backend:release-d6a23c1f697"
ROOT = Path.cwd()


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("$ " + " ".join(args), flush=True)
    result = subprocess.run(args, text=True)
    if check and result.returncode != 0:
        print(f"COMMAND_FAILED_RC={result.returncode}")
        raise SystemExit(result.returncode)
    return result


def capture(args: list[str]) -> str:
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        raise SystemExit(result.returncode)
    return result.stdout.strip()


def docker_py(extra_env: list[str], args: list[str], *, tmpfs: str = "128m") -> None:
    command = [
        "docker", "run", "--rm", "--read-only",
        "--tmpfs", f"/tmp:rw,noexec,nosuid,nodev,size={tmpfs}",
        "--entrypoint", "/opt/venv/bin/python",
        "-e", "HOME=/tmp",
        "-e", "TMPDIR=/tmp",
        "-e", "LIVE_TRADING_ENABLED=false",
        "-e", "EXPERIMENTAL_PRETRIGGER_ENABLED=false",
        "-e", "TELEGRAM_TOKEN=",
        "-e", "TELEGRAM_CHAT_ID=",
        "-e", "TELEGRAM_SIGNAL_DELIVERY_ENABLED=false",
        "-e", "REGISTRY_DB_PATH=/tmp/waterfall_registry.db",
        "-e", "PYTHONPATH=/project/backend/src:/project",
    ]
    for item in extra_env:
        command += ["-e", item]
    command += [
        "-v", f"{ROOT}:/project:ro",
        "-w", "/tmp",
        IMAGE,
        *args,
    ]
    run(command)


def main() -> int:
    print("=== PR56 PORT VALIDATION ===")

    head = capture(["git", "rev-parse", "HEAD"])
    if head != BASE:
        print(f"ABORT_WRONG_HEAD={head}")
        return 20

    merge_head_path = capture(["git", "rev-parse", "--git-path", "MERGE_HEAD"])
    if not Path(merge_head_path).is_file():
        print("ABORT_MERGE_STATE_MISSING")
        return 21

    merge_head = capture(["git", "rev-parse", "MERGE_HEAD"])
    if merge_head != MERGE_HEAD:
        print(f"ABORT_WRONG_MERGE_HEAD={merge_head}")
        return 22

    unmerged = capture(["git", "diff", "--name-only", "--diff-filter=U"])
    if unmerged:
        print("ABORT_UNMERGED_FILES")
        print(unmerged)
        return 23

    run(["docker", "image", "inspect", IMAGE], check=True)

    markers = subprocess.run(
        [
            "grep", "-R", "-nE", r"^(<<<<<<<|=======|>>>>>>>)",
            "backend/src/waterfallhunter", "backend/tests", "scripts",
        ],
        text=True,
        capture_output=True,
    )
    if markers.returncode == 0:
        print(markers.stdout, end="")
        print("ABORT_CONFLICT_MARKERS_REMAIN")
        return 24
    if markers.returncode not in (1,):
        print(markers.stderr, end="", file=sys.stderr)
        return markers.returncode

    print("PRECHECK=PASS")

    print("\n=== REGENERATE WAVE1D CORPUS ===")
    # Generator must write to the host worktree, so this one mount is rw and runs as root.
    run([
        "docker", "run", "--rm", "--user", "0:0",
        "--entrypoint", "/opt/venv/bin/python",
        "-e", "PYTHONPATH=/project/backend/src:/project",
        "-v", f"{ROOT}:/project",
        "-w", "/project",
        IMAGE,
        "scripts/build_wave1d_semantics_corpus.py",
    ])
    run(["git", "add", "backend/tests/golden/wave1d_semantics_corpus.json"])
    print("CORPUS_GENERATE_RC=0")

    print("\n=== TARGETED TESTS ===")
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
    docker_py([], ["-m", "pytest", "-q", "-p", "no:cacheprovider", *targeted])
    print("TARGETED_RC=0")

    print("\n=== FULL BACKEND TESTS ===")
    docker_py([], [
        "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "/project/backend/tests",
    ])
    print("FULL_TEST_RC=0")

    print("\n=== RUNTIME PARITY ===")
    docker_py([], ["/project/scripts/verify_runtime_parity.py"], tmpfs="64m")
    print("PARITY_RC=0")

    print("\n=== FINAL DIFF CHECK ===")
    run(["git", "diff", "--cached", "--check"])
    print("DIFF_CHECK_RC=0")

    changed = capture(["git", "diff", "--cached", "--name-only"])
    if any(line.startswith("frontend/") for line in changed.splitlines()):
        print("ABORT_FRONTEND_CHANGED")
        print(changed)
        return 25

    required_needles = {
        "backend/src/waterfallhunter/main.py": [
            "lifecycle_v2_decision_clock_at = time.time()",
            "decision_clock_at=lifecycle_v2_decision_clock_at",
            "async with _semaphore:",
            "should_flush = False",
        ],
        "backend/src/waterfallhunter/core/notifier.py": [
            "signal_delivery_enabled",
            "signal_delivery_cutover_at",
            "SIGNAL_DELIVERY_DISABLED",
            "Suppressing pre-cutover STRICT",
        ],
    }
    for rel, needles in required_needles.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        for needle in needles:
            if needle not in text:
                print(f"ABORT_REQUIRED_INVARIANT_MISSING={rel}:{needle}")
                return 26

    print("\n=== CHANGED FILES ===")
    print(changed)
    print("\n=== DIFF STAT ===")
    run(["git", "diff", "--cached", "--stat"])

    print("\n========================================")
    print("PORT_VALIDATION_STATUS=PASS")
    print("TARGETED_RC=0")
    print("FULL_TEST_RC=0")
    print("PARITY_RC=0")
    print("DIFF_CHECK_RC=0")
    print("FRONTEND_CHANGED=NO")
    print("DO_NOT_COMMIT_YET=YES")
    print("NO_PUSH=YES")
    print("NO_PRODUCTION_CHANGE=YES")
    print("========================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
