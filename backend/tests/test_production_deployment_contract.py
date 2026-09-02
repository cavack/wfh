from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import yaml

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
    """Reject deprecated execution-boundary language from tracked repository text."""
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


def test_production_deploy_requires_explicit_main_dispatch_after_ci() -> None:
    """Require the manual Production gate to be structurally bound to protected main."""
    ci_text = CI_WORKFLOW.read_text(encoding="utf-8")
    deploy_text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    ci_workflow = yaml.load(ci_text, Loader=yaml.BaseLoader)

    assert isinstance(ci_workflow, dict)
    triggers = ci_workflow["on"]
    deploy_input = triggers["workflow_dispatch"]["inputs"]["deploy_production"]
    assert deploy_input["required"] == "true"
    assert deploy_input["type"] == "boolean"
    assert deploy_input["default"] == "false"

    deploy_job_contract = ci_workflow["jobs"]["deploy-production"]
    assert deploy_job_contract["needs"] == [
        "backend",
        "frontend",
        "dependency-audit",
        "container-validation",
        "repository-hygiene",
    ]
    assert deploy_job_contract["if"] == (
        "${{ github.event_name == 'workflow_dispatch' && "
        "github.ref == 'refs/heads/main' && inputs.deploy_production == true }}"
    )
    assert deploy_job_contract["uses"] == "./.github/workflows/deploy-production.yml"

    assert "workflow_call:" in deploy_text
    assert "workflow_run:" not in deploy_text
    assert "workflow_dispatch" not in deploy_text
    assert "environment: production" in deploy_text
    assert "WFH_DEPLOY_SHA: ${{ github.sha }}" in deploy_text

    callers = []
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
        if "uses: ./.github/workflows/deploy-production.yml" in workflow.read_text(encoding="utf-8"):
            callers.append(workflow.name)
    assert callers == ["ci.yml"]


def test_privileged_deploy_does_not_use_workflow_run_head_code() -> None:
    """Keep privileged deployment on explicit main dispatch, never workflow_run code."""
    ci_text = CI_WORKFLOW.read_text(encoding="utf-8")
    deploy_text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    ci_workflow = yaml.load(ci_text, Loader=yaml.BaseLoader)
    assert "workflow_run" not in deploy_text
    assert "github.event.workflow_run" not in deploy_text
    assert ci_workflow["jobs"]["deploy-production"]["if"] == (
        "${{ github.event_name == 'workflow_dispatch' && "
        "github.ref == 'refs/heads/main' && inputs.deploy_production == true }}"
    )
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

    monitoring = text.split("wait_for_monitoring_containers_healthy() {", maxsplit=1)[
        1
    ].split("}\n", maxsplit=1)[0]
    assert "wait_for_container_healthy waterfall-prometheus" in monitoring
    assert "wait_for_container_healthy waterfall-grafana" in monitoring
    assert "docker compose ps -q alertmanager" in monitoring
    assert 'wait_for_container_healthy "$alertmanager_container"' in monitoring
    assert text.count("wait_for_monitoring_containers_healthy") >= 3


def test_host_deploy_keeps_telegram_delivery_fail_closed() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assertion = text.split("assert_telegram_delivery_disabled() {", maxsplit=1)[1].split(
        "}\n", maxsplit=1
    )[0]
    assert "docker compose run --rm --no-deps --interactive=false -T waterfall-backend" in assertion
    assert "settings.telegram_signal_delivery_enabled is False" in assertion
    assert "set_env_value TELEGRAM_SIGNAL_DELIVERY_ENABLED true" not in text
    assert "activate_telegram_for_release" not in text
    assert "telegram_signal_delivery_enabled=false" in text


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


def test_host_deploy_orders_backup_migration_runtime_and_host_certification() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    main_sequence = _main_deploy_sequence(text)
    ordered_markers = [
        "flock -n 9",
        '[[ "$(git rev-parse origin/main)" == "$WFH_DEPLOY_SHA" ]]',
        "assert_signal_only_runtime_boundary",
        "load_tested_release_artifacts",
        "assert_telegram_delivery_disabled",
        "backup_database",
        "--preflight",
        "MIGRATION_MAY_HAVE_MUTATED=1",
        "--apply --source-revision",
        "docker compose up -d",
        "/livez",
        "/readyz",
        "wait_for_container_healthy waterfall-frontend",
        "wait_for_container_healthy waterfall-watchdog",
        "org.opencontainers.image.revision",
        "snapshot_host_integration_state",
        "install_systemd_units",
        "install_nginx_site",
        "verify_public_edge",
        "prune_database_backups",
        'cat > "${STATE_DIR}/last-successful-deploy.txt"',
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
    assert 'COMPOSE_PROJECT_NAME="waterfallhunter"' in helper
    assert '${COMPOSE_PROJECT_NAME:-waterfallhunter}' not in text
    assert "com.docker.compose.project" not in helper
    assert "waterfall-backend" not in helper


def test_host_deploy_removes_release_containers_before_activation_and_rollback() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    helper_name = "remove_release_containers_before_compose_handoff"
    assert f"{helper_name}()" in text
    helper = text.split(f"{helper_name}() {{", maxsplit=1)[1].split(
        "}\n", maxsplit=1
    )[0]
    for container in (
        "waterfall-backend",
        "waterfall-frontend",
        "waterfall-watchdog",
        "waterfall-prometheus",
        "waterfall-grafana",
    ):
        assert container in helper
    assert "docker rm -f" in helper
    assert "docker compose config --format json" in helper
    assert 'get("volumes", {}).get("alertmanager_data", {}).get("name", "")' in helper
    assert '--filter "volume=${alertmanager_volume}"' in helper
    assert '[[ "$service" == "alertmanager" ]]' in helper

    rollback = text.split("rollback_previous_revision() {", maxsplit=1)[1].split(
        "terminate_with_cleanup() {", maxsplit=1
    )[0]
    rollback_up = rollback.index("docker compose up -d")
    assert rollback.rfind(helper_name, 0, rollback_up) >= 0

    main_sequence = _main_deploy_sequence(text)
    target_up = main_sequence.index("docker compose up -d")
    assert main_sequence.rfind(helper_name, 0, target_up) >= 0


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


def test_database_backup_runs_as_service_owner_and_promotes_only_after_certification() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    backup = text.split("backup_database() {", maxsplit=1)[1].split(
        "restore_database_backup() {", maxsplit=1
    )[0]
    assert "os.getuid(), os.getgid()" in backup
    assert 'install -d -m 0700 -o "$backend_uid" -g "$backend_gid" "$staging_dir"' in backup
    assert '--user 0:0' not in backup
    assert '-v "${staging_dir}:/backup"' in backup
    assert 'mv -- "${staging_dir}/${backup_name}" "$DB_BACKUP"' in backup
    assert 'sha256sum "${staging_dir}/${backup_name}"' in backup
    assert '"$actual_staged_sha" != "$DB_BACKUP_SHA256"' in backup
    assert backup.index("PRAGMA integrity_check") < backup.index(
        'mv -- "${staging_dir}/${backup_name}" "$DB_BACKUP"'
    )
    assert backup.index('"$actual_staged_sha" != "$DB_BACKUP_SHA256"') < backup.index(
        'mv -- "${staging_dir}/${backup_name}" "$DB_BACKUP"'
    )
    assert "staging_created=0" in backup
    assert backup.count(
        'rm -f -- "${staging_dir}/${backup_name}" "$DB_BACKUP" "${DB_BACKUP}.sha256"'
    ) >= 3


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
    assert 'file:{src}?mode=ro&immutable=1' in restore
    assert "docker compose stop waterfall-backend frontend watchdog" in restore
    assert "PRAGMA integrity_check" in restore


def test_deploy_installs_and_enables_canonical_systemd_units_after_runtime_health() -> None:
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
    assert "host integration snapshot missing before systemd install" in helper
    main_sequence = _main_deploy_sequence(text)
    runtime_index = main_sequence.index("docker compose up -d")
    healthy_index = main_sequence.index("verify_running_signal_only")
    snapshot_index = main_sequence.index("snapshot_host_integration_state")
    install_index = main_sequence.index("install_systemd_units")
    certificate_index = main_sequence.index('cat > "${STATE_DIR}/last-successful-deploy.txt"')
    assert runtime_index < healthy_index < snapshot_index < install_index < certificate_index


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


def test_streamed_remote_deploy_does_not_let_compose_consume_script_tail() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    main_sequence = _main_deploy_sequence(text)
    assert "docker compose up -d --remove-orphans --no-build </dev/null" in main_sequence
    compose_up_lines = [
        line.strip() for line in text.splitlines() if line.strip().startswith("docker compose up ")
    ]
    assert compose_up_lines
    assert all("</dev/null" in line for line in compose_up_lines)


def test_remote_deploy_executes_staged_script_file_not_streamed_stdin() -> None:
    text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    stage_step, deploy_step = text.split(
        "      - name: Stage exact CI-tested release inputs on Production host\n", maxsplit=1
    )[1].split("      - name: Deploy exact CI revision\n", maxsplit=1)
    assert "scripts/deploy_production.sh" in stage_step
    assert "local_script_sha256" in stage_step
    assert "remote_script_sha256" in stage_step
    assert 'test "$remote_script_sha256" = "$local_script_sha256"' in stage_step
    assert 'remote_script="${remote_dir}/deploy_production.sh"' in stage_step
    assert 'remote_script="${remote_dir}/deploy_production.sh"' in deploy_step
    assert "bash -s" not in deploy_step
    assert "< scripts/deploy_production.sh" not in deploy_step
    assert "bash '$remote_script' </dev/null" in deploy_step
    assert 'rm -f -- \\\"$remote_script\\\"' in deploy_step
    assert 'rmdir -- \\\"$remote_dir\\\"' in deploy_step


def test_public_edge_gate_targets_the_dashboard_base_path() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert (
        'local public_url="${WFH_PUBLIC_EDGE_URL:-http://waterfall.booksreadlive.online/dashboard/}"'
        in text
    )



def test_production_reusable_workflow_receives_only_explicit_deploy_secrets() -> None:
    ci_text = CI_WORKFLOW.read_text(encoding="utf-8")
    deploy_text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    deploy_job = ci_text.split("\n  deploy-production:\n", maxsplit=1)[1]
    expected = (
        "WFH_PROD_HOST",
        "WFH_DEPLOY_HOST",
        "WFH_PROD_PORT",
        "WFH_DEPLOY_PORT",
        "WFH_PROD_USER",
        "WFH_DEPLOY_USER",
        "WFH_PROD_SSH_KEY",
        "WFH_DEPLOY_SSH_KEY",
        "WFH_PROD_KNOWN_HOSTS",
        "WFH_DEPLOY_KNOWN_HOSTS",
    )
    assert "secrets: inherit" not in deploy_job
    for secret in expected:
        assert f"      {secret}: ${{{{ secrets.{secret} }}}}" in deploy_job
        assert f"      {secret}:\n        required: false" in deploy_text

def test_deploy_verifies_portable_bundle_config_digest_not_daemon_local_image_id() -> None:
    """Require portable bundle verification instead of daemon-local Docker image IDs."""
    helper = (ROOT / "scripts/deploy_production.sh").read_text(encoding="utf-8")
    assert "verify_ci_image_bundle.py" in helper
    assert '--allowed-root "${STATE_DIR}/incoming/${WFH_DEPLOY_SHA}"' in helper
    assert 'docker image inspect "$image_name" --format \'{{.Id}}\'' not in helper


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


def test_production_compose_wrapper_exports_canonical_env_path() -> None:
    wrapper = (ROOT / "scripts/production_compose.sh").read_text(encoding="utf-8")
    assert 'ENV_FILE="${WFH_ENV_FILE:-/etc/waterfallhunter/waterfallhunter.env}"' in wrapper
    assert 'export WFH_ENV_FILE="$ENV_FILE"' in wrapper


def test_ci_tested_image_bundle_upload_path_is_not_hidden() -> None:
    ci_text = CI_WORKFLOW.read_text(encoding="utf-8")
    container_job = ci_text.split("\n  container-validation:\n", maxsplit=1)[1].split(
        "\n  repository-hygiene:\n", maxsplit=1
    )[0]
    assert "path: ci-artifacts/" in container_job
    assert ".ci-artifacts/" not in container_job


def test_deploy_pins_target_images_to_release_specific_tags_before_compose_activation() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert 'RELEASE_BACKEND_IMAGE="wfh-release-backend:${WFH_DEPLOY_SHA}"' in text
    assert 'RELEASE_FRONTEND_IMAGE="wfh-release-frontend:${WFH_DEPLOY_SHA}"' in text
    assert 'RELEASE_WATCHDOG_IMAGE="wfh-release-watchdog:${WFH_DEPLOY_SHA}"' in text
    helper = text.split("pin_target_release_images() {", maxsplit=1)[1].split("}\n", maxsplit=1)[0]
    assert 'docker tag waterfallhunter-waterfall-backend "$RELEASE_BACKEND_IMAGE"' in helper
    assert 'docker tag waterfallhunter-frontend "$RELEASE_FRONTEND_IMAGE"' in helper
    assert 'docker tag waterfallhunter-watchdog "$RELEASE_WATCHDOG_IMAGE"' in helper
    assert "write_release_image_override" in helper
    main_sequence = _main_deploy_sequence(text)
    assert main_sequence.index("pin_target_release_images") < main_sequence.index("backup_database")
    assert main_sequence.index("activate_target_image_override") < main_sequence.index("backup_database")


def test_deploy_rollback_pins_previous_running_images_before_loading_target_bundle() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    main_sequence = _main_deploy_sequence(text)
    assert "pin_previous_running_images" in main_sequence
    assert main_sequence.index("pin_previous_running_images") < main_sequence.index("load_tested_release_artifacts")
    rollback = text.split("rollback_previous_revision() {", maxsplit=1)[1].split("terminate_with_cleanup() {", maxsplit=1)[0]
    assert "activate_rollback_image_override" in rollback
    assert rollback.index("activate_rollback_image_override") < rollback.index("docker compose up -d")


def test_successful_deploy_promotes_immutable_image_override_for_systemd_restarts() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    main_sequence = _main_deploy_sequence(text)
    assert "promote_target_image_override" in main_sequence
    assert main_sequence.index("verify_running_revision") < main_sequence.index("promote_target_image_override")
    assert main_sequence.index("promote_target_image_override") < main_sequence.index("install_systemd_units")
    wrapper = (ROOT / "scripts/production_compose.sh").read_text(encoding="utf-8")
    assert 'IMAGE_OVERRIDE="${WFH_PRODUCTION_IMAGE_OVERRIDE:-/srv/waterfallhunter/runtime/production-images.override.yml}"' in wrapper
    assert 'if [[ -f "$IMAGE_OVERRIDE" ]]; then' in wrapper
    assert 'compose_args+=(-f "$IMAGE_OVERRIDE")' in wrapper
