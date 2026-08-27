from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-production.yml"


def _workflow_text() -> str:
    assert WORKFLOW.is_file(), "guarded Production deployment workflow is missing"
    return WORKFLOW.read_text(encoding="utf-8")


def test_production_deploy_is_manual_and_explicitly_confirmed() -> None:
    text = _workflow_text()

    assert "workflow_dispatch:" in text
    assert "target_sha:" in text
    assert "confirm:" in text
    assert "DEPLOY_PAPER_ONLY" in text
    assert "push:" not in text
    assert "workflow_run:" not in text


def test_production_deploy_scopes_github_permissions_to_verify_job() -> None:
    text = _workflow_text()
    workflow_prefix, jobs = text.split("\njobs:\n", 1)
    verify_job, deploy_job = jobs.split("\n  deploy:\n", 1)

    assert "\npermissions:\n" not in workflow_prefix
    assert "permissions:\n      contents: read\n      actions: read" in verify_job
    assert "contents: write" not in text
    assert "actions: write" not in text
    assert "permissions: {}" in deploy_job
    assert "contents: read" not in deploy_job
    assert "actions: read" not in deploy_job
    assert "environment: production" in deploy_job
    assert "concurrency:" in workflow_prefix
    assert "cancel-in-progress: false" in workflow_prefix


def test_production_deploy_requires_exact_main_ci_success() -> None:
    text = _workflow_text()

    assert "origin/main" in text
    assert "actions/workflows/ci.yml/runs" in text
    assert "event == \"push\"" in text or "event == 'push'" in text
    assert "status=success" in text


def test_production_deploy_uses_pinned_ssh_host_identity_and_required_secrets() -> None:
    text = _workflow_text()

    for secret_name in (
        "WFH_DEPLOY_HOST",
        "WFH_DEPLOY_USER",
        "WFH_DEPLOY_PORT",
        "WFH_DEPLOY_PATH",
        "WFH_DEPLOY_SSH_KEY",
        "WFH_DEPLOY_KNOWN_HOSTS",
    ):
        assert secret_name in text

    assert "StrictHostKeyChecking=yes" in text
    assert "StrictHostKeyChecking=no" not in text
    assert "known_hosts" in text


def test_production_deploy_never_applies_database_migrations() -> None:
    text = _workflow_text()

    assert "--apply" not in text
    assert "deploy_production.py" in text
    assert "--target-sha" in text
