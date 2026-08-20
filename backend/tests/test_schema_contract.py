from __future__ import annotations

import sqlite3

import pytest

from waterfallhunter.core.schema_contract import (
    CURRENT_RUNTIME_SCHEMA_VERSION,
    SchemaContractError,
    managed_runtime_table_names,
    require_managed_schema_connection,
    verify_managed_schema_connection,
)


EXPECTED_RUNTIME_TABLES = frozenset(
    {
        "lbank_catalog",
        "catalog_events",
        "lbank_signal_ledger",
        "lbank_signal_outcomes",
        "lbank_stage_lifecycle",
        "production_evidence_snapshots",
        "production_feature_replay_results_v2",
        "lbank_execution_observations",
        "lbank_execution_observation_history",
        "lbank_execution_decision_log",
        "operational_historical_outcome_datasets",
        "operational_historical_signal_outcomes",
        "provider_states",
        "signal_metadata",
    }
)


def _codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


def test_manifest_covers_exact_runtime_tables_and_version():
    assert CURRENT_RUNTIME_SCHEMA_VERSION == 3
    assert managed_runtime_table_names() == EXPECTED_RUNTIME_TABLES


def test_schema_verifier_rejects_missing_managed_table():
    conn = sqlite3.connect(":memory:")
    result = verify_managed_schema_connection(
        conn,
        required_tables=frozenset({"provider_states"}),
    )
    assert result.valid is False
    assert _codes(result) == {"TABLE_MISSING"}


def test_schema_verifier_rejects_extra_managed_column():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE provider_states (
            provider_id TEXT PRIMARY KEY,
            upstream_identity TEXT NOT NULL,
            status TEXT NOT NULL,
            failure_class TEXT NOT NULL,
            consecutive_failures INTEGER NOT NULL,
            circuit_open_until REAL NOT NULL,
            replacement_generation INTEGER NOT NULL,
            last_success_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            unexpected TEXT
        )
        """
    )
    result = verify_managed_schema_connection(
        conn,
        required_tables=frozenset({"provider_states"}),
    )
    assert "COLUMN_SET_MISMATCH" in _codes(result)


def test_schema_verifier_rejects_wrong_primary_key():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE provider_states (
            provider_id TEXT NOT NULL,
            upstream_identity TEXT NOT NULL,
            status TEXT NOT NULL,
            failure_class TEXT NOT NULL,
            consecutive_failures INTEGER NOT NULL,
            circuit_open_until REAL NOT NULL,
            replacement_generation INTEGER NOT NULL,
            last_success_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    result = verify_managed_schema_connection(
        conn,
        required_tables=frozenset({"provider_states"}),
    )
    assert "COLUMN_CONSTRAINT_MISMATCH" in _codes(result)


def test_schema_verifier_rejects_wrong_named_index_columns():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE lbank_stage_lifecycle (
            symbol TEXT NOT NULL,
            lifecycle_id INTEGER NOT NULL,
            hype_seen_at INTEGER,
            damage_seen_at INTEGER,
            setup_seen_at INTEGER,
            setup_type TEXT,
            trigger_seen_at INTEGER,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (symbol, lifecycle_id)
        );
        CREATE INDEX idx_lbank_stage_lifecycle_updated
        ON lbank_stage_lifecycle(symbol);
        """
    )
    result = verify_managed_schema_connection(
        conn,
        required_tables=frozenset({"lbank_stage_lifecycle"}),
    )
    assert "INDEX_MISMATCH" in _codes(result)


def _create_signal_ledger_parent(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE lbank_signal_ledger (id INTEGER PRIMARY KEY)")


def _create_outcomes(
    conn: sqlite3.Connection,
    *,
    fk_target: str = "lbank_signal_ledger",
    observational_check: str = "observational_only = 1",
    immutable_update: bool = True,
) -> None:
    update_raise = (
        "SELECT RAISE(ABORT, 'lbank_signal_outcomes is immutable');"
        if immutable_update
        else "SELECT RAISE(IGNORE);"
    )
    conn.executescript(
        f"""
        CREATE TABLE lbank_signal_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER NOT NULL UNIQUE,
            symbol TEXT NOT NULL,
            outcome_status TEXT NOT NULL,
            signal_triggered_at INTEGER NOT NULL,
            observation_started_at INTEGER,
            observation_ended_at INTEGER,
            horizon_seconds INTEGER NOT NULL,
            price_source TEXT NOT NULL,
            source_exchange TEXT,
            source_mapped_symbol TEXT,
            first_tp1_at INTEGER,
            first_tp2_at INTEGER,
            first_stop_at INTEGER,
            min_price REAL,
            max_price REAL,
            mfe_pct REAL,
            mae_pct REAL,
            observed_candles INTEGER NOT NULL,
            expected_candles INTEGER NOT NULL,
            details_json TEXT NOT NULL,
            observational_only INTEGER NOT NULL DEFAULT 1 CHECK ({observational_check}),
            trade_eligible INTEGER CHECK (trade_eligible IS NULL),
            resolved_at INTEGER NOT NULL,
            FOREIGN KEY(signal_id) REFERENCES {fk_target}(id)
        );
        CREATE INDEX idx_lbank_signal_outcomes_status
        ON lbank_signal_outcomes(outcome_status, resolved_at);
        CREATE TRIGGER lbank_signal_outcomes_no_update
        BEFORE UPDATE ON lbank_signal_outcomes
        BEGIN
            {update_raise}
        END;
        CREATE TRIGGER lbank_signal_outcomes_no_delete
        BEFORE DELETE ON lbank_signal_outcomes
        BEGIN
            SELECT RAISE(ABORT, 'lbank_signal_outcomes is immutable');
        END;
        """
    )


def test_schema_verifier_rejects_wrong_foreign_key_target():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE wrong_parent (id INTEGER PRIMARY KEY)")
    _create_outcomes(conn, fk_target="wrong_parent")
    result = verify_managed_schema_connection(
        conn,
        required_tables=frozenset({"lbank_signal_outcomes"}),
    )
    assert "FOREIGN_KEY_MISMATCH" in _codes(result)


def test_schema_verifier_rejects_missing_critical_check():
    conn = sqlite3.connect(":memory:")
    _create_signal_ledger_parent(conn)
    _create_outcomes(conn, observational_check="observational_only IN (0, 1)")
    result = verify_managed_schema_connection(
        conn,
        required_tables=frozenset({"lbank_signal_outcomes"}),
    )
    assert "CHECK_MISSING" in _codes(result)


def test_schema_verifier_rejects_non_aborting_immutable_trigger():
    conn = sqlite3.connect(":memory:")
    _create_signal_ledger_parent(conn)
    _create_outcomes(conn, immutable_update=False)
    result = verify_managed_schema_connection(
        conn,
        required_tables=frozenset({"lbank_signal_outcomes"}),
    )
    assert "TRIGGER_MISMATCH" in _codes(result)


def test_schema_verifier_reports_but_preserves_unknown_table():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE user_extension (id INTEGER PRIMARY KEY)")
    before = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='user_extension'"
    ).fetchone()[0]

    result = verify_managed_schema_connection(
        conn,
        required_tables=frozenset(),
    )

    after = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='user_extension'"
    ).fetchone()[0]
    assert result.valid is True
    assert result.unknown_user_objects == ("user_extension",)
    assert before == after


def test_schema_verifier_can_allow_absent_optional_legacy_tables():
    conn = sqlite3.connect(":memory:")
    result = verify_managed_schema_connection(
        conn,
        required_tables=frozenset({"provider_states"}),
        allow_missing_tables=frozenset({"provider_states"}),
    )
    assert result.valid is True
    assert result.issues == ()


def test_schema_verifier_rejects_user_version_mismatch():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA user_version=1")
    result = verify_managed_schema_connection(
        conn,
        required_tables=frozenset(),
        check_user_version=2,
    )
    assert result.valid is False
    assert _codes(result) == {"USER_VERSION_MISMATCH"}


def test_require_managed_schema_connection_raises_typed_error():
    conn = sqlite3.connect(":memory:")
    with pytest.raises(SchemaContractError):
        require_managed_schema_connection(
            conn,
            required_tables=frozenset({"provider_states"}),
        )
