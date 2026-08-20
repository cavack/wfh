from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from schema_test_support import build_legacy_runtime_database, migrate_test_database
from waterfallhunter.core.migration_preflight import (
    MigrationPreflightError,
    PreflightState,
    classify_database,
    require_migration_compatible,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_preflight_classifies_missing_path_without_creating_database(tmp_path: Path):
    db_path = tmp_path / "new.db"

    result = classify_database(db_path)

    assert result.state is PreflightState.CLEAN_NEW
    assert result.compatible is True
    assert result.reason_codes == ()
    assert db_path.exists() is False


def test_preflight_classifies_existing_empty_sqlite_without_mutation(tmp_path: Path):
    db_path = tmp_path / "empty.db"
    with sqlite3.connect(db_path):
        pass
    before = _sha256(db_path)

    result = classify_database(db_path)

    assert result.state is PreflightState.CLEAN_EMPTY
    assert result.compatible is True
    assert _sha256(db_path) == before


def test_preflight_accepts_canonical_legacy_schema_without_mutation(tmp_path: Path):
    db_path = build_legacy_runtime_database(tmp_path / "legacy.db")
    before = _sha256(db_path)

    result = classify_database(db_path)

    assert result.state is PreflightState.LEGACY_CANONICAL
    assert result.compatible is True
    assert result.user_version == 0
    assert result.reason_codes == ()
    assert _sha256(db_path) == before


def test_preflight_accepts_legacy_schema_with_canonical_optional_tables(tmp_path: Path):
    db_path = build_legacy_runtime_database(
        tmp_path / "legacy-optional.db",
        include_optional=True,
    )

    result = classify_database(db_path)

    assert result.state is PreflightState.LEGACY_CANONICAL
    assert result.compatible is True


def test_preflight_accepts_migrated_schema_read_only(tmp_path: Path):
    db_path = migrate_test_database(tmp_path / "migrated.db")
    before = _sha256(db_path)

    result = classify_database(db_path)

    assert result.state is PreflightState.MIGRATED_COMPATIBLE
    assert result.compatible is True
    assert result.applied_versions == (1, 2)
    assert result.user_version == 2
    assert _sha256(db_path) == before


def test_preflight_rejects_missing_required_legacy_table_before_write(tmp_path: Path):
    db_path = build_legacy_runtime_database(tmp_path / "partial.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE catalog_events")
    before = _sha256(db_path)

    result = classify_database(db_path)

    assert result.state is PreflightState.PARTIAL_OR_INCOMPATIBLE
    assert result.compatible is False
    assert "LEGACY_SCHEMA_MISMATCH" in result.reason_codes
    assert _sha256(db_path) == before

    with pytest.raises(MigrationPreflightError):
        require_migration_compatible(db_path)
    assert _sha256(db_path) == before


def test_preflight_rejects_nonzero_legacy_user_version_before_write(tmp_path: Path):
    db_path = build_legacy_runtime_database(tmp_path / "bad-version.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA user_version=7")
    before = _sha256(db_path)

    result = classify_database(db_path)

    assert result.state is PreflightState.PARTIAL_OR_INCOMPATIBLE
    assert "LEGACY_USER_VERSION_INVALID" in result.reason_codes
    assert _sha256(db_path) == before


def test_preflight_rejects_partial_migration_metadata_without_repair(tmp_path: Path):
    db_path = tmp_path / "partial-history.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)")
        conn.execute("PRAGMA user_version=1")
    before = _sha256(db_path)

    result = classify_database(db_path)

    assert result.state is PreflightState.PARTIAL_OR_INCOMPATIBLE
    assert "MIGRATION_HISTORY_INVALID" in result.reason_codes
    assert _sha256(db_path) == before
