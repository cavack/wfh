from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
INSTALLER = REPO / "scripts/install_wfh_council_hooks.sh"
PRE_COMMIT = REPO / ".githooks/pre-commit"
PRE_PUSH = REPO / ".githooks/pre-push"


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / ".githooks").mkdir()
    (repo / "scripts").mkdir()
    shutil.copy2(PRE_COMMIT, repo / ".githooks/pre-commit")
    shutil.copy2(PRE_PUSH, repo / ".githooks/pre-push")
    shutil.copy2(INSTALLER, repo / "scripts/install_wfh_council_hooks.sh")
    return repo


def test_installer_sets_repo_local_hooks_path_and_is_idempotent(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    installer = repo / "scripts/install_wfh_council_hooks.sh"

    subprocess.run(["bash", str(installer)], cwd=repo, check=True)
    assert _git(repo, "config", "--local", "--get", "core.hooksPath") == ".githooks"

    subprocess.run(["bash", str(installer)], cwd=repo, check=True)
    assert _git(repo, "config", "--local", "--get", "core.hooksPath") == ".githooks"


def test_hooks_and_installer_are_executable() -> None:
    for path in (INSTALLER, PRE_COMMIT, PRE_PUSH):
        mode = path.stat().st_mode
        assert mode & stat.S_IXUSR, f"{path} must be executable"


def test_hooks_are_validation_only_and_never_deploy() -> None:
    forbidden = ("deploy_production", "LIVE_TRADING_ENABLED=true", "docker compose up", "workflow_dispatch")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (PRE_COMMIT, PRE_PUSH, INSTALLER))
    for marker in forbidden:
        assert marker not in combined
