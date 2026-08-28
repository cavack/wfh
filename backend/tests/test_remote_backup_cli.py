from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from scripts import certify_remote_sqlite_backup as cli


def _key_file(path: Path) -> None:
    path.write_text(base64.b64encode(b"k" * 32).decode("ascii") + "\n", encoding="ascii")
    os.chmod(path, 0o600)


def test_key_loader_is_restricted_to_trusted_recovery_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    monkeypatch.setattr(cli, "TRUSTED_KEY_ROOT", trusted)
    inside = trusted / "wfh-dr-aes256.key"
    outside = tmp_path / "outside.key"
    _key_file(inside)
    _key_file(outside)
    original_stat = Path.stat

    def root_owned_stat(path: Path, *, follow_symlinks: bool = True):
        result = original_stat(path, follow_symlinks=follow_symlinks)
        if path == inside:
            values = list(result)
            values[4] = 0
            return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "stat", root_owned_stat)
    assert cli._load_key(inside) == b"k" * 32
    with pytest.raises(cli.RemoteBackupCLIError, match="REMOTE_BACKUP_KEY_FILE_INVALID"):
        cli._load_key(outside)


def test_cleanup_never_unlinks_outside_staging_directory(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    outside = tmp_path / "outside.db"
    outside.write_bytes(b"operator-owned")

    with pytest.raises(cli.RemoteBackupCLIError, match="REMOTE_BACKUP_CLEANUP_PATH_INVALID"):
        cli._safe_unlink_staging_artifact(
            outside,
            staging_dir=staging,
            allowed_names={"restored.db"},
        )

    assert outside.read_bytes() == b"operator-owned"


def test_release_create_failure_attempts_draft_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_gh(*arguments: str, timeout: int = 120) -> str:
        calls.append(tuple(arguments))
        if arguments[:2] == ("release", "create"):
            raise cli.RemoteBackupCLIError("SIMULATED_CREATE_TIMEOUT")
        return ""

    monkeypatch.setattr(cli, "_gh", fake_gh)
    with pytest.raises(cli.RemoteBackupCLIError, match="SIMULATED_CREATE_TIMEOUT"):
        cli._publish_release_assets(
            repository="cavack/wfh-dr",
            tag_name="wfh-dr-timeout-test",
            upload_paths=[Path("/tmp/part.enc")],
        )

    assert any(
        call[:3] == ("release", "delete", "wfh-dr-timeout-test")
        for call in calls
    )


def test_gh_commands_pin_github_dot_com_host(monkeypatch: pytest.MonkeyPatch) -> None:
    observed_env: dict[str, str] = {}

    class Result:
        stdout = "{}"

    def fake_run(_arguments, **kwargs):
        observed_env.update(kwargs.get("env") or {})
        return Result()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    cli._gh("api", "user")
    assert observed_env.get("GH_HOST") == "github.com"


def test_gh_failure_includes_bounded_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_run(arguments, **_kwargs):
        raise cli.subprocess.CalledProcessError(
            1,
            arguments,
            stderr="authentication failed\n" + ("x" * 2000),
        )

    monkeypatch.setattr(cli.subprocess, "run", fail_run)
    with pytest.raises(cli.RemoteBackupCLIError, match="authentication failed") as captured:
        cli._gh("api", "user")
    assert len(str(captured.value)) < 700
