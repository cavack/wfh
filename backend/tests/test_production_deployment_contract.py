from __future__ import annotations

from pathlib import Path

from waterfallhunter.core.contracts import ExecutionMode, SignalDecisionPacket


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-production.yml"
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy_production.sh"


def test_execution_mode_is_signal_only() -> None:
    assert ExecutionMode.SIGNAL_ONLY.value == "SIGNAL_ONLY"
    assert "PAPER_ONLY" not in {member.value for member in ExecutionMode}


def test_signal_decision_defaults_to_signal_only() -> None:
    field = SignalDecisionPacket.model_fields["execution_mode"]
    assert field.default is ExecutionMode.SIGNAL_ONLY


def test_current_product_surfaces_do_not_use_deprecated_paper_boundary_terms() -> None:
    roots = [
        ROOT / "backend" / "src",
        ROOT / "frontend",
        ROOT / "docs" / "operations",
    ]
    files = [
        ROOT / ".env.example",
        ROOT / "docker-compose.yml",
        ROOT / "README.md",
        ROOT / "SECURITY.md",
        ROOT / "CONTRIBUTING.md",
    ]
    for root in roots:
        if root.exists():
            files.extend(path for path in root.rglob("*") if path.is_file())

    forbidden = ("PAPER_ONLY", "paper-only", "paper trading", "paper-trading")
    offenders: list[str] = []
    for path in files:
        if path.suffix in {".pyc", ".map"}:
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
