from __future__ import annotations

import subprocess
from pathlib import Path

from waterfallhunter.core.contracts import ExecutionMode, SignalDecisionPacket


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-production.yml"
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy_production.sh"


def _tracked_text_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [
        ROOT / raw.decode("utf-8")
        for raw in result.stdout.split(b"\0")
        if raw
    ]


def test_execution_mode_is_signal_only() -> None:
    deprecated_mode = "PAPER" + "_ONLY"
    assert ExecutionMode.SIGNAL_ONLY.value == "SIGNAL_ONLY"
    assert deprecated_mode not in {member.value for member in ExecutionMode}


def test_signal_decision_defaults_to_signal_only() -> None:
    field = SignalDecisionPacket.model_fields["execution_mode"]
    assert field.default is ExecutionMode.SIGNAL_ONLY


def test_tracked_repository_text_does_not_use_deprecated_product_boundary_terms() -> None:
    forbidden = (
        "PAPER" + "_ONLY",
        "paper" + "-only",
        "Paper" + "-only",
        "paper" + " trading",
        "Paper" + " trading",
        "paper" + "-trading",
        "Paper" + "-trading",
    )
    offenders: list[str] = []
    for path in _tracked_text_files():
        if path.suffix in {".pyc", ".map", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(term in text for term in forbidden):
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_production_deploy_workflow_is_automatic_after_successful_main_ci() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_run:" in text
    assert "workflows: [CI]" in text or 'workflows: ["CI"]' in text
    assert "branches: [main]" in text
    assert "types: [completed]" in text
    assert "workflow_dispatch" not in text
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert "github.event.workflow_run.head_sha" in text
    assert "environment: production" in text


def test_production_deploy_workflow_pins_ssh_host_identity() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "WFH_PROD_KNOWN_HOSTS" in text
    assert "StrictHostKeyChecking=yes" in text
    assert "ssh-keyscan" not in text
    assert "StrictHostKeyChecking=no" not in text


def test_host_deploy_orders_backup_migration_telegram_and_runtime_certification() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    ordered_markers = [
        "flock",
        "git merge-base --is-ancestor",
        "LIVE_TRADING_ENABLED",
        "docker compose build",
        "backup",
        "migrate_database --preflight",
        "migrate_database --apply",
        "TELEGRAM_SIGNAL_DELIVERY_ENABLED",
        "TELEGRAM_SIGNAL_DELIVERY_CUTOVER_AT",
        "docker compose up -d",
        "/api/livez",
        "/api/readyz",
        "org.opencontainers.image.revision",
    ]
    positions = [text.index(marker) for marker in ordered_markers]
    assert positions == sorted(positions)


def test_host_deploy_never_enables_live_trading_or_destroys_persistent_volumes() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "LIVE_TRADING_ENABLED=true" not in text
    assert "docker compose down -v" not in text
    assert "StrictHostKeyChecking=no" not in text
