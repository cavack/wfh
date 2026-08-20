from __future__ import annotations

import sqlite3

import pytest

from waterfallhunter.core.schema_contract import (
    RUNTIME_SCHEMA,
    SchemaContractError,
    managed_runtime_table_names,
    verify_runtime_schema,
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
    }
)

IMMUTABLE_TABLES = {
    "lbank_signal_ledger",
    "lbank_signal_outcomes",
    "production_evidence_snapshots",
    "production_feature_replay_results_v2",
    "operational_historical_outcome_datasets",
    "operational_historical_signal_outcomes",
}


def test_runtime_schema_manifest_covers_exact_managed_tables():
    assert managed_runtime_table_names() == EXPECTED_RUNTIME_TABLES
    assert frozenset(RUNTIME_SCHEMA) == EXPECTED_RUNTIME_TABLES


def test_runtime_schema_manifest_marks_immutable_tables_with_update_delete_guards():
    for table_name in IMMUTABLE_TABLES:
        trigger_events = {
            trigger.event for trigger in RUNTIME_SCHEMA[table_name].triggers
        }
        assert {"UPDATE", "DELETE"} <= trigger_events


def _create_example_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE example_parent (
            id INTEGER PRIMARY KEY
        );
        CREATE TABLE example (
            id INTEGER PRIMARY KEY,
            parent_id INTEGER NOT NULL,
            value TEXT NOT NULL DEFAULT 'x',
            state TEXT NOT NULL CHECK (state IN ('A', 'B')),
            UNIQUE(parent_id, value),
            FOREIGN KEY(parent_id) REFERENCES example_parent(id)
        );
        CREATE INDEX example_state_idx ON example(state, value);
        CREATE TRIGGER example_no_update
        BEFORE UPDATE ON example
        BEGIN
            SELECT RAISE(ABORT, 'example is immutable');
        END;
        """
    )


def test_verifier_tolerates_unknown_tables_outside_requested_subset():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    verify_runtime_schema(conn, tables=set())


def test_verifier_rejects_unknown_extra_column_on_managed_table(monkeypatch):
    conn = sqlite3.connect(":memory:")
    _create_example_schema(conn)
    conn.execute("ALTER TABLE example ADD COLUMN unexpected TEXT")

    example_spec = RUNTIME_SCHEMA["lbank_catalog"]
    monkeypatch.setitem(RUNTIME_SCHEMA, "lbank_catalog", example_spec)

    with pytest.raises(SchemaContractError):
        verify_runtime_schema(conn, tables={"lbank_catalog"})


def test_verifier_rejects_missing_managed_table():
    conn = sqlite3.connect(":memory:")
    with pytest.raises(SchemaContractError):
        verify_runtime_schema(conn, tables={"lbank_catalog"})


def test_verifier_rejects_unknown_requested_table_name():
    conn = sqlite3.connect(":memory:")
    with pytest.raises(SchemaContractError):
        verify_runtime_schema(conn, tables={"not_managed"})
