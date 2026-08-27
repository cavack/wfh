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
        return [ROOT / raw.decode("utf-8") for raw in result.stdout.split(b"\0") if raw]

    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and not any(part in SCAN_EXCLUDED_PARTS for part in path.parts)
    )


def _main_deploy_sequence(text: str) -> str:
    return text.split('[[ "$WFH_DEPLOY_SHA"', maxsplit=1)[1]


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
    binary_suffixes = {".pyc", ".map", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf"}
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

    callers = []
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
        if "uses: ./.github/workflows/deploy-production.yml" in workflow.read_text(encoding="utf-8"):
            callers.append(workflow.name)
    assert callers == ["ci.yml"]


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


def test_host_deploy_uses_registered_backend_health_paths() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "wait_for_backend_endpoint /livez" in text
    assert "wait_for_backend_endpoint /readyz" in text
    assert "wait_for_backend_endpoint /api/livez" not in text
    assert "wait_for_backend_endpoint /api/readyz" not in text


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
    assert '[[ "$state" == "running" ]]' not in helper
    assert helper.count("return 0") == 1


def test_telegram_cutover_is_captured_at_activation_time() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    activation = text.split("activate_telegram_for_release() {", maxsplit=1)[1].split(
        "}\n", maxsplit=1
    )[0]
    assert 'TELEGRAM_CUTOVER_EPOCH="$(date -u +%s)"' in activation
    assert 'set_env_value TELEGRAM_SIGNAL_DELIVERY_CUTOVER_AT "$TELEGRAM_CUTOVER_EPOCH"' in activation
    assert "telegram_cutover_at=${TELEGRAM_CUTOVER_EPOCH}" in text


def test_successful_deploy_prunes_backups_before_publishing_certificate() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    main_sequence = _main_deploy_sequence(text)
    prune_index = main_sequence.index("prune_database_backups")
    certificate_index = main_sequence.index('cat > "${STATE_DIR}/last-successful-deploy.txt"')
    assert prune_index < certificate_index


def test_compose_run_commands_cannot_consume_streamed_deploy_script() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    normalized = text.replace("\\\n", " ")
    commands = [
        match.group(0)
        for match in re.finditer(r"docker compose run[^\n]+", normalized)
    ]
    assert len(commands) >= 4
    for command in commands:
        assert "--interactive=false" in command
        assert "-T" in command or "--no-TTY" in command


def test_host_deploy_rejects_any_dirty_source_worktree_before_checkout_and_build() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    helper = text.split("assert_clean_deploy_worktree() {", maxsplit=1)[1].split(
        "}\n", maxsplit=1
    )[0]
    assert "git status --porcelain" in helper
    assert ":(exclude).env" not in helper
    assert ":(exclude).deploy" not in helper
    main_sequence = _main_deploy_sequence(text)
    assert main_sequence.index("assert_clean_deploy_worktree") < main_sequence.index(
        'git checkout --detach "$WFH_DEPLOY_SHA"'
    )


def test_incompatible_post_migration_runtime_is_quarantined() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    rollback = text.split("rollback_previous_revision() {", maxsplit=1)[1].split(
        "terminate_with_cleanup() {", maxsplit=1
    )[0]
    incompatible = rollback.split(
        "if ! previous_revision_accepts_current_schema; then", maxsplit=1
    )[1].split("\n    fi", maxsplit=1)[0]
    assert "docker compose stop" in incompatible
    for service in ("waterfall-backend", "frontend", "watchdog"):
        assert service in incompatible


def test_successful_deploy_removes_secret_environment_rollback_copy() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    main_sequence = _main_deploy_sequence(text)
    certificate_index = main_sequence.index('cat > "${STATE_DIR}/last-successful-deploy.txt"')
    cleanup_index = main_sequence.index('rm -f -- "$ENV_BACKUP"')
    assert certificate_index < cleanup_index


def test_host_deploy_orders_backup_migration_telegram_and_runtime_certification() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    main_sequence = _main_deploy_sequence(text)
    ordered_markers = [
        "flock -n 9",
        '[[ "$(git rev-parse origin/main)" == "$WFH_DEPLOY_SHA" ]]',
        "assert_signal_only_runtime_boundary",
        "load_tested_release_artifacts",
        "install_systemd_units",
        "backup_database",
        "--preflight",
        "MIGRATION_MAY_HAVE_MUTATED=1",
        "--apply --source-revision",
        "activate_telegram_for_release",
        "docker compose up -d",
        "/livez",
        "/readyz",
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


def test_host_deploy_auto_uses_host_owned_compose_topology_override() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert 'PRODUCTION_COMPOSE_OVERRIDE="${STATE_DIR}/production-volumes.override.yml"' in text
    assert "configure_production_compose_topology" in text
    helper = text.split("configure_production_compose_topology() {", maxsplit=1)[1].split(
        "}\n", maxsplit=1
    )[0]
    assert '[[ -f "$PRODUCTION_COMPOSE_OVERRIDE" ]]' in helper
    assert 'export COMPOSE_FILE="${WFH_DEPLOY_ROOT}/docker-compose.yml:${PRODUCTION_COMPOSE_OVERRIDE}"' in helper
    main_sequence = _main_deploy_sequence(text)
    assert main_sequence.index("configure_production_compose_topology") < main_sequence.index(
        "docker compose config --quiet"
    )


def test_host_deploy_uses_one_canonical_compose_project_with_host_override() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    helper = text.split("configure_production_compose_topology() {", maxsplit=1)[1].split(
        "}\n", maxsplit=1
    )[0]
    assert 'COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-waterfallhunter}"' in helper
    assert "com.docker.compose.project" not in helper
    assert "waterfall-backend" not in helper


def test_host_deploy_removes_fixed_name_core_containers_before_activation_and_rollback() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "remove_fixed_name_core_containers()" in text
    helper = text.split("remove_fixed_name_core_containers() {", maxsplit=1)[1].split(
        "}\n", maxsplit=1
    )[0]
    for container in ("waterfall-backend", "waterfall-frontend", "waterfall-watchdog"):
        assert container in helper
    assert "docker rm -f" in helper

    rollback = text.split("rollback_previous_revision() {", maxsplit=1)[1].split(
        "terminate_with_cleanup() {", maxsplit=1
    )[0]
    rollback_up = rollback.index("docker compose up -d")
    assert rollback.rfind("remove_fixed_name_core_containers", 0, rollback_up) >= 0

    main_sequence = _main_deploy_sequence(text)
    target_up = main_sequence.index("docker compose up -d")
    assert main_sequence.rfind("remove_fixed_name_core_containers", 0, target_up) >= 0


def test_failed_deploys_also_enforce_backup_retention() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    cleanup = text.split("terminate_with_cleanup() {", maxsplit=1)[1].split(
        "on_error() {", maxsplit=1
    )[0]
    assert "prune_database_backups" in cleanup


def test_default_database_backup_retention_is_two() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert 'WFH_DEPLOY_BACKUP_RETENTION_COUNT="${WFH_DEPLOY_BACKUP_RETENTION_COUNT:-2}"' in text


def test_host_deploy_uses_canonical_host_owned_env_state_and_backup_paths() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert 'WFH_HOST_ROOT="${WFH_HOST_ROOT:-/srv/waterfallhunter}"' in text
    assert 'ENV_FILE="${WFH_ENV_FILE:-/etc/waterfallhunter/waterfallhunter.env}"' in text
    assert 'DEPLOY_STATE_DIR="${WFH_HOST_ROOT}/runtime"' in text
    assert 'BACKUP_DIR="${WFH_HOST_ROOT}/backups"' in text
    assert 'PRODUCTION_COMPOSE_OVERRIDE="${STATE_DIR}/production-volumes.override.yml"' in text
    assert 'export WFH_ENV_FILE="$ENV_FILE"' in text


def test_deploy_clean_worktree_no_longer_depends_on_runtime_files_inside_git() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    helper = text.split("assert_clean_deploy_worktree() {", maxsplit=1)[1].split("}\n", maxsplit=1)[0]
    assert "git status --porcelain" in helper
    assert ":(exclude).env" not in helper
    assert ":(exclude).deploy" not in helper


def test_schema_changing_rollback_restores_backup_before_previous_schema_preflight() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "restore_database_backup()" in text
    rollback = text.split("rollback_previous_revision() {", maxsplit=1)[1].split(
        "terminate_with_cleanup() {", maxsplit=1
    )[0]
    restore_index = rollback.index("restore_database_backup")
    preflight_index = rollback.index("previous_revision_accepts_current_schema")
    assert restore_index < preflight_index
    restore = text.split("restore_database_backup() {", maxsplit=1)[1].split(
        "prune_database_backups() {", maxsplit=1
    )[0]
    assert 'sha256sum "$DB_BACKUP"' in restore
    assert '${BACKUP_DIR}:/backup:ro' in restore
    assert "docker compose stop waterfall-backend frontend watchdog" in restore
    assert "PRAGMA integrity_check" in restore


def test_deploy_installs_and_enables_canonical_systemd_units_before_activation() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "install_systemd_units()" in text
    helper = text.split("install_systemd_units() {", maxsplit=1)[1].split("}\n", maxsplit=1)[0]
    for unit in (
        "waterfallhunter.service",
        "waterfallhunter-healthcheck.service",
        "waterfallhunter-healthcheck.timer",
    ):
        assert unit in helper
    assert "systemctl daemon-reload" in helper
    assert "systemctl enable waterfallhunter.service waterfallhunter-healthcheck.timer" in helper
    main_sequence = _main_deploy_sequence(text)
    assert main_sequence.index("install_systemd_units") < main_sequence.index("docker compose up -d")


def test_main_deploy_loads_ci_tested_images_instead_of_rebuilding_target() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    main_sequence = _main_deploy_sequence(text)
    assert "load_tested_release_artifacts" in main_sequence
    load_index = main_sequence.index("load_tested_release_artifacts")
    backup_index = main_sequence.index("backup_database")
    assert load_index < backup_index
    target_prefix = main_sequence[:backup_index]
    assert "docker compose build" not in target_prefix
    helper = text.split("load_tested_release_artifacts() {", maxsplit=1)[1].split("}\n", maxsplit=1)[0]
    assert 'docker load -i "$WFH_TESTED_IMAGE_BUNDLE"' in helper
    assert "WFH_TESTED_BACKEND_IMAGE_DIGEST" in helper
    assert "WFH_TESTED_FRONTEND_IMAGE_DIGEST" in helper
    assert "WFH_TESTED_WATCHDOG_IMAGE_DIGEST" in helper
    assert "WFH_TESTED_IMAGE_BUNDLE_SHA256" in helper


def test_ci_exports_and_uploads_exact_tested_image_bundle_to_deploy_job() -> None:
    ci_text = CI_WORKFLOW.read_text(encoding="utf-8")
    deploy_text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    container_job = ci_text.split("\n  container-validation:\n", maxsplit=1)[1].split(
        "\n  repository-hygiene:\n", maxsplit=1
    )[0]
    assert "outputs:" in container_job
    assert "tested_backend_image_digest" in container_job
    assert "tested_frontend_image_digest" in container_job
    assert "tested_watchdog_image_digest" in container_job
    assert "tested_image_bundle_sha256" in container_job
    assert "docker save" in container_job
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in container_job

    deploy_job = ci_text.split("\n  deploy-production:\n", maxsplit=1)[1]
    assert "tested_backend_image_digest: ${{ needs.container-validation.outputs.tested_backend_image_digest }}" in deploy_job
    assert "tested_frontend_image_digest: ${{ needs.container-validation.outputs.tested_frontend_image_digest }}" in deploy_job
    assert "tested_watchdog_image_digest: ${{ needs.container-validation.outputs.tested_watchdog_image_digest }}" in deploy_job
    assert "tested_image_bundle_sha256: ${{ needs.container-validation.outputs.tested_image_bundle_sha256 }}" in deploy_job

    assert "workflow_call:" in deploy_text
    assert "tested_backend_image_digest:" in deploy_text
    assert "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093" in deploy_text
    assert "WFH_TESTED_IMAGE_BUNDLE_SHA256" in deploy_text
    assert "WFH_TESTED_BACKEND_IMAGE_DIGEST" in deploy_text
