from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from waterfallhunter.core.contracts import ExecutionMode, SignalDecisionPacket


ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-production.yml"
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy_production.sh"
SCAN_EXCLUDED_PARTS = {
    ".git",
    ".next",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}


def _tracked_text_files() -> list[Path]:
    git = shutil.which("git")
    if git is not None:
        result = subprocess.run(
            [git, "ls-files", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        return [
            ROOT / raw.decode("utf-8")
            for raw in result.stdout.split(b"\0")
            if raw
        ]

    # The production backend image intentionally omits git. Container
    # validation mounts a clean checkout read-only at ROOT, so conservatively
    # scan every visible repository file while excluding generated/VCS trees.
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and not any(part in SCAN_EXCLUDED_PARTS for part in path.parts)
    )


def test_execution_mode_is_signal_only() -> None:
    deprecated_mode = "SIMULATED" + "_ONLY"
    assert ExecutionMode.SIGNAL_ONLY.value == "SIGNAL_ONLY"
    assert deprecated_mode not in {member.value for member in ExecutionMode}


def test_signal_decision_defaults_to_signal_only() -> None:
    field = SignalDecisionPacket.model_fields["execution_mode"]
    assert field.default is ExecutionMode.SIGNAL_ONLY


def test_tracked_repository_text_does_not_use_deprecated_product_boundary_terms() -> None:
    forbidden = (
        "SIMULATED" + "_ONLY",
        "simulated" + "-only",
        "Simulated" + "-only",
        "simulated" + " trading",
        "Simulated" + " trading",
        "simulated" + "-trading",
        "Simulated" + "-trading",
    )
    deprecated_word = "pa" + "per"
    standalone_deprecated = re.compile(
        rf"(?i)(?<![A-Za-z0-9_]){deprecated_word}(?![A-Za-z0-9_])"
    )
    offenders: list[str] = []
    binary_suffixes = {
        ".pyc",
        ".map",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".pdf",
    }
    for path in _tracked_text_files():
        if path.suffix in binary_suffixes:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(term in text for term in forbidden) or standalone_deprecated.search(text):
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_production_deploy_is_chained_to_successful_main_push_ci() -> None:
    ci_text = CI_WORKFLOW.read_text(encoding="utf-8")
    deploy_text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_call:" in deploy_text
    assert "workflow_run:" not in deploy_text
    assert "workflow_dispatch" not in deploy_text
    assert "environment: production" in deploy_text
    assert "WFH_DEPLOY_SHA: ${{ github.sha }}" in deploy_text

    deploy_job = ci_text.split("\n  deploy-production:\n", maxsplit=1)[1]
    for dependency in (
        "backend",
        "frontend",
        "dependency-audit",
        "container-validation",
        "repository-hygiene",
    ):
        assert f"      - {dependency}\n" in deploy_job
    assert "github.event_name == 'push'" in deploy_job
    assert "github.ref == 'refs/heads/main'" in deploy_job
    assert "uses: ./.github/workflows/deploy-production.yml" in deploy_job


def test_privileged_deploy_does_not_use_workflow_run_head_code() -> None:
    ci_text = CI_WORKFLOW.read_text(encoding="utf-8")
    deploy_text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_run" not in deploy_text
    assert "github.event.workflow_run" not in deploy_text
    assert "github.event_name == 'push'" in ci_text
    assert "github.ref == 'refs/heads/main'" in ci_text
    deploy_job = deploy_text.split("jobs:\n  deploy:\n", maxsplit=1)[1]
    assert "    permissions:\n      contents: read\n" in deploy_job


def test_deployment_rejects_stale_main_revisions_at_both_boundaries() -> None:
    workflow_text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    script_text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    workflow_equality_gate = 'test "$(git rev-parse origin/main)" = "$WFH_DEPLOY_SHA"'
    script_equality_gate = '[[ "$(git rev-parse origin/main)" == "$WFH_DEPLOY_SHA" ]]'
    assert workflow_equality_gate in workflow_text
    assert script_equality_gate in script_text


def test_production_deploy_workflow_pins_ssh_host_identity() -> None:
    text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    assert "WFH_PROD_KNOWN_HOSTS" in text
    assert "StrictHostKeyChecking=yes" in text
    assert "ssh-keyscan" not in text
    assert "StrictHostKeyChecking=no" not in text


def test_host_deploy_uses_deploy_owned_lock_and_certified_previous_revision() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert 'LOCK_FILE="${WFH_DEPLOY_LOCK_FILE:-${STATE_DIR}/deploy.lock}"' in text
    assert "resolve_previous_revision" in text
    assert "restore_previous_workspace" in text
    assert 'PREVIOUS_SHA="$(resolve_previous_revision)"' in text


def test_host_deploy_tracks_possible_migration_mutation_before_apply() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    apply_index = text.index("--apply --source-revision")
    marker_index = text.rfind("MIGRATION_MAY_HAVE_MUTATED=1", 0, apply_index)
    assert marker_index >= 0


def test_host_deploy_failure_and_signal_paths_are_rollback_aware() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    fail_body = text.split("fail() {", maxsplit=1)[1].split("}\n", maxsplit=1)[0]
    assert "terminate_with_cleanup 1" in fail_body
    assert "trap on_error ERR" in text
    assert "trap 'on_signal TERM' TERM" in text
    assert "trap 'on_signal HUP' HUP" in text
    assert "trap 'on_signal INT' INT" in text
    signal_case = text.split('case "$signal" in', maxsplit=1)[1].split("esac", maxsplit=1)[0]
    assert "*) status=1 ;;" in signal_case
    assert "MIGRATION_MAY_HAVE_MUTATED" in text
    assert "RUNTIME_REPLACED" in text


def test_host_deploy_certifies_all_release_containers_healthy() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert text.count("wait_for_container_healthy waterfall-backend") >= 2
    assert text.count("wait_for_container_healthy waterfall-frontend") >= 2
    assert text.count("wait_for_container_healthy waterfall-watchdog") >= 2
    helper = text.split("wait_for_container_healthy() {", maxsplit=1)[1].split(
        "}\n", maxsplit=1
    )[0]
    assert "{{else}}running{{end}}" not in helper
    assert '[[ "$state" == "healthy" ]]' in helper
    assert '|| "$state" == "running"' not in helper


def test_telegram_cutover_is_captured_at_activation_time() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    activation = text.split("activate_telegram_for_release() {", maxsplit=1)[1].split(
        "}\n", maxsplit=1
    )[0]
    assert 'TELEGRAM_CUTOVER_EPOCH="$(date -u +%s)"' in activation
    assert 'set_env_value TELEGRAM_SIGNAL_DELIVERY_CUTOVER_AT "$TELEGRAM_CUTOVER_EPOCH"' in activation
    assert "telegram_cutover_at=${TELEGRAM_CUTOVER_EPOCH}" in text


def test_successful_deploy_prunes_certified_database_backups() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "WFH_DEPLOY_BACKUP_RETENTION_COUNT" in text
    assert "prune_database_backups" in text
    certificate_index = text.index('cat > "${STATE_DIR}/last-successful-deploy.txt"')
    prune_index = text.index("prune_database_backups", certificate_index)
    assert prune_index > certificate_index


def test_host_deploy_orders_backup_migration_telegram_and_runtime_certification() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    main_sequence = text.split('[[ "$WFH_DEPLOY_SHA"', maxsplit=1)[1]
    ordered_markers = [
        "flock -n 9",
        '[[ "$(git rev-parse origin/main)" == "$WFH_DEPLOY_SHA" ]]',
        "assert_signal_only_runtime_boundary",
        "docker compose build",
        "backup_database",
        "--preflight",
        "MIGRATION_MAY_HAVE_MUTATED=1",
        "--apply --source-revision",
        "activate_telegram_for_release",
        "docker compose up -d",
        "/api/livez",
        "/api/readyz",
        "wait_for_container_healthy waterfall-frontend",
        "wait_for_container_healthy waterfall-watchdog",
        "org.opencontainers.image.revision",
    ]
    positions = [main_sequence.index(marker) for marker in ordered_markers]
    assert positions == sorted(positions)


def test_host_deploy_never_enables_live_trading_or_destroys_persistent_volumes() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "LIVE_TRADING_ENABLED=true" not in text
    assert "docker compose down -v" not in text
    assert "StrictHostKeyChecking=no" not in text
