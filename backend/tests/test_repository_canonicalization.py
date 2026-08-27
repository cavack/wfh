from __future__ import annotations

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]

CANONICAL_DOCS = {
    "docs/ARCHITECTURE.md",
    "docs/MODEL.md",
    "docs/DECISION_ENGINE.md",
    "docs/DASHBOARD.md",
    "docs/DATA_AND_DATABASE.md",
    "docs/OPERATIONS.md",
    "docs/DEPLOYMENT.md",
    "docs/BACKUP_RESTORE.md",
    "docs/TELEGRAM.md",
    "docs/AI_ADVISORY.md",
    "docs/TROUBLESHOOTING.md",
    "docs/DEVELOPER_ONBOARDING.md",
    "docs/PROJECT_HANDOFF.md",
}


def _tracked_files() -> set[str]:
    output = subprocess.check_output(
        ["git", "ls-files"], cwd=ROOT, text=True
    )
    return {line.strip() for line in output.splitlines() if line.strip()}


def test_canonical_handoff_docs_exist() -> None:
    assert CANONICAL_DOCS <= _tracked_files()


def test_tracked_tree_has_no_generated_runtime_debris() -> None:
    tracked = _tracked_files()
    forbidden_parts = {
        ".venv", "venv", "node_modules", ".next", ".pytest_cache",
        "__pycache__", ".work", "backup", "backups",
    }
    offenders = [
        path for path in tracked
        if forbidden_parts.intersection(Path(path).parts)
        or path.endswith((".pyc", ".log", ".db", ".sqlite", ".sqlite3", ".tsbuildinfo"))
    ]
    assert offenders == []


def test_only_maintained_first_party_workflows_are_tracked() -> None:
    workflows = {
        Path(path).name
        for path in _tracked_files()
        if path.startswith(".github/workflows/")
    }
    assert workflows == {"ci.yml", "deploy-production.yml"}


def test_required_cold_start_files_are_present() -> None:
    tracked = _tracked_files()
    assert {"README.md", "CHANGELOG.md", "Makefile", ".env.example"} <= tracked


def test_ci_runs_canonical_repository_hygiene_verifier() -> None:
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "python scripts/verify_repository_hygiene.py --root ." in ci


def test_pull_request_template_guards_canonical_decision_contract() -> None:
    template = (ROOT / ".github/pull_request_template.md").read_text(encoding="utf-8")
    assert "Only canonical `ENTRY_READY`" in template
    assert "PROJECT_HANDOFF.md" in template


def test_active_production_tree_has_no_ollama_runtime_dependency() -> None:
    tracked = _tracked_files()
    active = [
        path for path in tracked
        if path in {"docker-compose.yml", ".env.example", "README.md"}
        or path.startswith("backend/src/")
        or path.startswith("frontend/")
        or path.startswith("watchdog/")
        or path.startswith("deploy/")
    ]
    offenders: list[str] = []
    for rel in active:
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8").lower()
        except (UnicodeDecodeError, OSError):
            continue
        if "ollama" in text:
            offenders.append(rel)
    assert offenders == []
