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
