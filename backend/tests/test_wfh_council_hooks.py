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
    assert _git(repo, "config", "--worktree", "--get", "core.hooksPath") == ".githooks"

    subprocess.run(["bash", str(installer)], cwd=repo, check=True)
    assert _git(repo, "config", "--worktree", "--get", "core.hooksPath") == ".githooks"


def test_hooks_and_installer_are_executable() -> None:
    for path in (INSTALLER, PRE_COMMIT, PRE_PUSH):
        mode = path.stat().st_mode
        assert mode & stat.S_IXUSR, f"{path} must be executable"


def test_hooks_are_validation_only_and_never_deploy() -> None:
    forbidden = ("deploy_production", "LIVE_TRADING_ENABLED=true", "docker compose up", "workflow_dispatch")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (PRE_COMMIT, PRE_PUSH, INSTALLER))
    for marker in forbidden:
        assert marker not in combined


def test_linked_worktree_install_does_not_set_shared_hooks_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "council@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Council Test"], cwd=root, check=True)
    (root / "seed").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "seed"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=root, check=True)

    linked = tmp_path / "linked"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "council-test", str(linked)], cwd=root, check=True)
    (linked / ".githooks").mkdir()
    (linked / "scripts").mkdir()
    for source, dest in (
        (PRE_COMMIT, linked / ".githooks/pre-commit"),
        (PRE_PUSH, linked / ".githooks/pre-push"),
        (INSTALLER, linked / "scripts/install_wfh_council_hooks.sh"),
    ):
        shutil.copy2(source, dest)

    subprocess.run(["bash", str(linked / "scripts/install_wfh_council_hooks.sh")], cwd=linked, check=True)
    assert _git(linked, "config", "--worktree", "--get", "core.hooksPath") == ".githooks"
    shared = subprocess.run(
        ["git", "config", "--local", "--get", "core.hooksPath"], cwd=root, text=True, capture_output=True
    )
    assert shared.returncode == 1
