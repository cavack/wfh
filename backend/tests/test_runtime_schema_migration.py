from __future__ import annotations

from pathlib import Path

from waterfallhunter.core.migrations import MigrationRunner, discover_migrations
from waterfallhunter.core.schema_contract import (
    CURRENT_RUNTIME_SCHEMA_VERSION,
    verify_managed_schema,
)


def test_packaged_migrations_include_runtime_baseline():
    migrations = discover_migrations()

    assert [item.version for item in migrations] == [1, 2]
    assert migrations[1].filename == "0002_runtime_schema_baseline.sql"


def test_clean_install_reaches_current_runtime_schema(tmp_path: Path):
    db_path = tmp_path / "registry.db"
    runner = MigrationRunner(db_path=db_path, source_revision="test")

    assert runner.apply() == (1, 2)
    assert runner.verify() == (1, 2)

    result = verify_managed_schema(
        db_path,
        check_user_version=CURRENT_RUNTIME_SCHEMA_VERSION,
    )
    assert result.valid is True, result.issues

    assert runner.apply() == ()
