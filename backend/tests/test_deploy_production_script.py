from __future__ import annotations

from pathlib import Path

import pytest

from scripts.deploy_production import CommandResult, DeploymentError, deploy


TARGET_SHA = "a" * 40
PREVIOUS_SHA = "b" * 40


class FakeRunner:
    def __init__(
        self,
        *,
        target_sha: str = TARGET_SHA,
        previous_sha: str = PREVIOUS_SHA,
        dirty: bool = False,
        preflight_ok: bool = True,
        target_health_ok: bool = True,
    ) -> None:
        self.target_sha = target_sha
        self.previous_sha = previous_sha
        self.dirty = dirty
        self.preflight_ok = preflight_ok
        self.target_health_ok = target_health_ok
        self.calls: list[tuple[str, ...]] = []
        self.cutover_seen = False
        self.rollback_seen = False

    def run(
        self,
        args: tuple[str, ...] | list[str],
        *,
        cwd: Path,
        check: bool = True,
    ) -> CommandResult:
        command = tuple(args)
        self.calls.append(command)

        if command == ("git", "status", "--porcelain"):
            return CommandResult(0, " M tracked.txt\n" if self.dirty else "", "")
        if command == ("git", "fetch", "--prune", "origin", "main"):
            return CommandResult(0, "", "")
        if command == ("git", "rev-parse", "origin/main"):
            return CommandResult(0, self.target_sha + "\n", "")
        if command == ("git", "rev-parse", "HEAD"):
            return CommandResult(0, self.previous_sha + "\n", "")
        if command[:3] == ("git", "show", "-s"):
            return CommandResult(0, "2026-08-27T01:14:31+00:00\n", "")
        if command[:3] == ("git", "checkout", "--detach"):
            if command[-1] == self.previous_sha:
                self.rollback_seen = True
            return CommandResult(0, "", "")

        if command[:3] == ("docker", "image", "inspect"):
            image = command[3]
            image_ids = {
                "waterfallhunter-waterfall-backend": "sha256:" + "1" * 64,
                "waterfallhunter-frontend": "sha256:" + "2" * 64,
                "waterfallhunter-watchdog": "sha256:" + "3" * 64,
            }
            return CommandResult(0, image_ids[image] + "\n", "")

        if command[:3] == ("docker", "image", "tag"):
            self.rollback_seen = True
            return CommandResult(0, "", "")

        if command == ("docker", "compose", "config", "--quiet"):
            return CommandResult(0, "", "")

        if command[:3] == ("docker", "compose", "build"):
            return CommandResult(0, "", "")

        if command[:4] == ("docker", "compose", "run", "--rm"):
            if self.preflight_ok:
                return CommandResult(
                    0,
                    '{"ok":true,"mode":"preflight","state":"MIGRATED_COMPATIBLE"}\n',
                    "",
                )
            if check:
                raise DeploymentError("command failed: migration preflight")
            return CommandResult(3, '{"ok":false}\n', "")

        if command[:4] == ("docker", "compose", "up", "-d"):
            self.cutover_seen = True
            return CommandResult(0, "", "")

        if command[:3] == ("docker", "inspect", "--format"):
            template = command[3]
            container = command[4]
            if template == "{{.State.Health.Status}}":
                if self.target_health_ok or self.rollback_seen:
                    return CommandResult(0, "healthy\n", "")
                return CommandResult(0, "unhealthy\n", "")
            if "org.opencontainers.image.revision" in template:
                return CommandResult(0, self.target_sha + "\n", "")
            raise AssertionError(f"unexpected inspect template for {container}: {template}")

        if command[:2] == ("docker", "exec"):
            return CommandResult(0, "", "")

        raise AssertionError(f"unexpected command: {command}")


def _repo(tmp_path: Path, env_text: str = "LIVE_TRADING_ENABLED=false\n") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text(env_text, encoding="utf-8")
    return repo


def _index(calls: list[tuple[str, ...]], prefix: tuple[str, ...]) -> int:
    for index, command in enumerate(calls):
        if command[: len(prefix)] == prefix:
            return index
    raise AssertionError(f"missing command prefix: {prefix}")


def test_invalid_target_sha_fails_before_any_command(tmp_path: Path) -> None:
    runner = FakeRunner()

    with pytest.raises(DeploymentError, match="target SHA"):
        deploy(target_sha="not-a-sha", repo_dir=_repo(tmp_path), runner=runner)

    assert runner.calls == []


def test_dirty_worktree_fails_before_checkout_or_build(tmp_path: Path) -> None:
    runner = FakeRunner(dirty=True)

    with pytest.raises(DeploymentError, match="worktree"):
        deploy(target_sha=TARGET_SHA, repo_dir=_repo(tmp_path), runner=runner)

    assert not any(call[:3] == ("git", "checkout", "--detach") for call in runner.calls)
    assert not any(call[:3] == ("docker", "compose", "build") for call in runner.calls)


def test_target_must_equal_current_origin_main(tmp_path: Path) -> None:
    runner = FakeRunner(target_sha="c" * 40)

    with pytest.raises(DeploymentError, match="origin/main"):
        deploy(target_sha=TARGET_SHA, repo_dir=_repo(tmp_path), runner=runner)

    assert not any(call[:3] == ("git", "checkout", "--detach") for call in runner.calls)


@pytest.mark.parametrize(
    "env_text",
    [
        "ENVIRONMENT=production\n",
        "LIVE_TRADING_ENABLED=true\n",
        "LIVE_TRADING_ENABLED=$(echo false)\n",
        "LIVE_TRADING_ENABLED=false\nLIVE_TRADING_ENABLED=false\n",
    ],
)
def test_unsafe_or_ambiguous_live_trading_env_fails_closed(
    tmp_path: Path,
    env_text: str,
) -> None:
    runner = FakeRunner()

    with pytest.raises(DeploymentError, match="LIVE_TRADING_ENABLED"):
        deploy(target_sha=TARGET_SHA, repo_dir=_repo(tmp_path, env_text), runner=runner)

    assert not any(call[:3] == ("docker", "compose", "build") for call in runner.calls)


def test_build_and_schema_preflight_happen_before_cutover(tmp_path: Path) -> None:
    runner = FakeRunner()

    deploy(target_sha=TARGET_SHA, repo_dir=_repo(tmp_path), runner=runner)

    build_index = _index(runner.calls, ("docker", "compose", "build"))
    preflight_index = _index(runner.calls, ("docker", "compose", "run", "--rm"))
    cutover_index = _index(runner.calls, ("docker", "compose", "up", "-d"))

    assert build_index < preflight_index < cutover_index
    preflight = runner.calls[preflight_index]
    assert "--preflight" in preflight
    assert "--apply" not in preflight


def test_schema_preflight_failure_restores_tags_and_revision_without_cutover(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(preflight_ok=False)

    with pytest.raises(DeploymentError, match="preflight"):
        deploy(target_sha=TARGET_SHA, repo_dir=_repo(tmp_path), runner=runner)

    assert runner.rollback_seen is True
    assert not any(call[:4] == ("docker", "compose", "up", "-d") for call in runner.calls)
    assert ("git", "checkout", "--detach", PREVIOUS_SHA) in runner.calls


def test_post_cutover_health_failure_restores_previous_application(tmp_path: Path) -> None:
    runner = FakeRunner(target_health_ok=False)

    with pytest.raises(DeploymentError, match="health"):
        deploy(
            target_sha=TARGET_SHA,
            repo_dir=_repo(tmp_path),
            runner=runner,
            health_timeout_seconds=0,
        )

    assert runner.cutover_seen is True
    assert runner.rollback_seen is True
    up_calls = [call for call in runner.calls if call[:4] == ("docker", "compose", "up", "-d")]
    assert len(up_calls) == 2
    assert ("git", "checkout", "--detach", PREVIOUS_SHA) in runner.calls


def test_success_verifies_health_revision_labels_and_smoke_checks(tmp_path: Path) -> None:
    runner = FakeRunner()

    result = deploy(target_sha=TARGET_SHA, repo_dir=_repo(tmp_path), runner=runner)

    assert result.target_sha == TARGET_SHA
    assert result.previous_sha == PREVIOUS_SHA
    assert result.rolled_back is False

    health_checks = [
        call
        for call in runner.calls
        if call[:4] == ("docker", "inspect", "--format", "{{.State.Health.Status}}")
    ]
    assert {call[-1] for call in health_checks} == {
        "waterfall-backend",
        "waterfall-frontend",
        "waterfall-watchdog",
    }

    revision_checks = [
        call
        for call in runner.calls
        if call[:3] == ("docker", "inspect", "--format")
        and "org.opencontainers.image.revision" in call[3]
    ]
    assert {call[-1] for call in revision_checks} == {
        "waterfall-backend",
        "waterfall-frontend",
        "waterfall-watchdog",
    }

    smoke_checks = [call for call in runner.calls if call[:2] == ("docker", "exec")]
    assert {call[2] for call in smoke_checks} == {"waterfall-backend", "waterfall-frontend"}
