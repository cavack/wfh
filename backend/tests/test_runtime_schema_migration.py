from __future__ import annotations

import sqlite3
from pathlib import Path

from schema_test_support import (
    build_legacy_runtime_database,
    business_row_hashes,
)
from waterfallhunter.core.migration_preflight import (
    PreflightState,
    require_migration_compatible,
)
from waterfallhunter.core.migrations import MigrationRunner, discover_migrations
from waterfallhunter.core.schema_contract import (
    CURRENT_RUNTIME_SCHEMA_VERSION,
    verify_managed_schema,
)


_PRESERVED_TABLES = (
    "lbank_catalog",
    "catalog_events",
    "lbank_signal_ledger",
    "lbank_signal_outcomes",
    "lbank_stage_lifecycle",
    "production_evidence_snapshots",
    "production_feature_replay_results_v2",
    "lbank_execution_decision_log",
    "operational_historical_outcome_datasets",
    "operational_historical_signal_outcomes",
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


def test_canonical_legacy_adoption_preserves_business_and_evidence_rows(tmp_path: Path):
    db_path = build_legacy_runtime_database(tmp_path / "legacy.db")
    before_hashes = business_row_hashes(db_path, _PRESERVED_TABLES)

    preflight = require_migration_compatible(db_path)
    assert preflight.state is PreflightState.LEGACY_CANONICAL

    runner = MigrationRunner(
        db_path=db_path,
        source_revision="test-legacy-adoption",
    )
    assert runner.apply() == (1, 2)
    assert runner.verify() == (1, 2)

    after_hashes = business_row_hashes(db_path, _PRESERVED_TABLES)
    assert after_hashes == before_hashes

    schema = verify_managed_schema(
        db_path,
        check_user_version=CURRENT_RUNTIME_SCHEMA_VERSION,
    )
    assert schema.valid is True, schema.issues

    with sqlite3.connect(db_path) as conn:
        history = conn.execute(
            "SELECT version, source_revision FROM schema_migrations ORDER BY version"
        ).fetchall()
        optional_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?,?)",
                (
                    "lbank_execution_observations",
                    "lbank_execution_observation_history",
                    "provider_states",
                ),
            ).fetchall()
        }

    assert history == [
        (1, "test-legacy-adoption"),
        (2, "test-legacy-adoption"),
    ]
    assert optional_tables == {
        "lbank_execution_observations",
        "lbank_execution_observation_history",
        "provider_states",
    }
    assert runner.apply() == ()


def test_legacy_adoption_with_existing_optional_tables_is_idempotent(tmp_path: Path):
    db_path = build_legacy_runtime_database(
        tmp_path / "legacy-optional.db",
        include_optional=True,
    )
    before_hashes = business_row_hashes(db_path, _PRESERVED_TABLES)

    assert require_migration_compatible(db_path).state is PreflightState.LEGACY_CANONICAL
    runner = MigrationRunner(db_path=db_path, source_revision="test")
    assert runner.apply() == (1, 2)
    assert business_row_hashes(db_path, _PRESERVED_TABLES) == before_hashes
    assert runner.apply() == ()
