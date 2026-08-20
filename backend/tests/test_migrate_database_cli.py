from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from schema_test_support import build_legacy_runtime_database


def _main():
    from waterfallhunter import migrate_database

    return migrate_database.main


def _json_output(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert set(payload) <= {
        "ok",
        "mode",
        "state",
        "reason_codes",
        "applied_versions",
        "user_version",
        "journal_mode",
    }
    return payload


def test_cli_requires_explicit_mode_and_does_not_create_database(tmp_path: Path, capsys):
    db_path = tmp_path / "registry.db"

    exit_code = _main()(["--db-path", str(db_path)])

    assert exit_code == 2
    assert db_path.exists() is False
    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["reason_codes"] == ["MODE_REQUIRED"]


def test_cli_rejects_conflicting_modes_without_writing(tmp_path: Path, capsys):
    db_path = tmp_path / "registry.db"

    exit_code = _main()(
        ["--db-path", str(db_path), "--preflight", "--apply", "--source-revision", "test"]
    )

    assert exit_code == 2
    assert db_path.exists() is False
    payload = _json_output(capsys)
    assert payload["reason_codes"] == ["MODE_CONFLICT"]


def test_cli_apply_requires_nonempty_source_revision(tmp_path: Path, capsys):
    db_path = tmp_path / "registry.db"

    exit_code = _main()(["--db-path", str(db_path), "--apply"])

    assert exit_code == 2
    assert db_path.exists() is False
    payload = _json_output(capsys)
    assert payload["reason_codes"] == ["SOURCE_REVISION_REQUIRED"]


@pytest.mark.parametrize(
    "unsafe_db_path",
    (
        "registry.db",
        ":memory:",
        "file:registry.db?mode=memory&cache=shared",
    ),
)
def test_cli_rejects_non_absolute_or_sqlite_pseudo_targets(unsafe_db_path: str, capsys):
    exit_code = _main()(["--db-path", unsafe_db_path, "--preflight"])

    assert exit_code == 2
    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["reason_codes"] == ["DB_PATH_INVALID"]


def test_cli_rejects_symlink_database_target_without_writing(tmp_path: Path, capsys):
    target = build_legacy_runtime_database(tmp_path / "legacy.db")
    before = target.read_bytes()
    alias = tmp_path / "registry.db"
    alias.symlink_to(target)

    exit_code = _main()(["--db-path", str(alias), "--preflight"])

    assert exit_code == 2
    assert target.read_bytes() == before
    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["reason_codes"] == ["DB_PATH_INVALID"]


def test_cli_preflight_is_read_only_for_legacy_database(tmp_path: Path, capsys):
    db_path = build_legacy_runtime_database(tmp_path / "legacy.db")
    before = db_path.read_bytes()

    exit_code = _main()(["--db-path", str(db_path), "--preflight"])

    assert exit_code == 0
    assert db_path.read_bytes() == before
    payload = _json_output(capsys)
    assert payload == {
        "ok": True,
        "mode": "preflight",
        "state": "LEGACY_CANONICAL",
        "reason_codes": [],
        "applied_versions": [],
        "user_version": 0,
    }


def test_cli_apply_clean_install_sets_wal_and_verifies_schema_v2(tmp_path: Path, capsys):
    db_path = tmp_path / "registry.db"

    exit_code = _main()(
        [
            "--db-path",
            str(db_path),
            "--apply",
            "--source-revision",
            "verified-test-revision",
        ]
    )

    assert exit_code == 0
    payload = _json_output(capsys)
    assert payload["ok"] is True
    assert payload["mode"] == "apply"
    assert payload["state"] == "MIGRATED_COMPATIBLE"
    assert payload["applied_versions"] == [1, 2]
    assert payload["user_version"] == 2
    assert payload["journal_mode"] == "wal"

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_cli_apply_rejects_incompatible_legacy_before_migration_write(tmp_path: Path, capsys):
    db_path = build_legacy_runtime_database(tmp_path / "partial.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE catalog_events")
    before = db_path.read_bytes()

    exit_code = _main()(
        ["--db-path", str(db_path), "--apply", "--source-revision", "test"]
    )

    assert exit_code == 3
    assert db_path.read_bytes() == before
    payload = _json_output(capsys)
    assert payload["ok"] is False
    assert payload["state"] == "PARTIAL_OR_INCOMPATIBLE"
    assert "LEGACY_SCHEMA_MISMATCH" in payload["reason_codes"]


def test_cli_never_emits_environment_secret_values(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "super-secret-token-value")
    db_path = tmp_path / "registry.db"

    assert _main()(["--db-path", str(db_path), "--preflight"]) == 0

    captured = capsys.readouterr()
    assert "super-secret-token-value" not in captured.out
    assert "super-secret-token-value" not in captured.err
