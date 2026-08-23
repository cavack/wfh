from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from schema_test_support import migrate_test_database
from waterfallhunter.core.managed_sqlite import (
    ManagedSQLiteError,
    connect_managed_sqlite,
)


WRITER_MODULES = (
    "db.py",
    "db_readiness.py",
    "feature_replay.py",
    "historical_outcome_store.py",
    "lbank_execution_decision.py",
    "lbank_execution_stats.py",
    "lbank_execution_store.py",
    "lbank_signal_ledger.py",
    "lbank_signal_outcome.py",
    "production_evidence.py",
    "provider_registry.py",
    "stage_lifecycle.py",
)


def test_managed_connection_enables_and_verifies_foreign_keys(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "managed.db"

    with connect_managed_sqlite(db_path) as conn:
        enabled = conn.execute("PRAGMA foreign_keys").fetchone()

    assert enabled == (1,)


def test_managed_connection_rejects_orphan_signal_metadata(tmp_path: Path) -> None:
    db_path = migrate_test_database(tmp_path / "orphan.db")

    with connect_managed_sqlite(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO signal_metadata (
                    signal_id,
                    signal_class,
                    strategy_profile,
                    score_version,
                    model_generation,
                    decision_contract_hash,
                    analysis_observed_at,
                    reference_observed_at,
                    metadata_contract_version,
                    classification_method,
                    classification_evidence_hash,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    999,
                    "STRICT",
                    "strict_score_v2",
                    "score_v2",
                    "waterfall_signal_model_v1",
                    "a" * 64,
                    1_700_000_000,
                    None,
                    "signal_metadata_v1",
                    "FUTURE_PIPELINE_EXPLICIT",
                    None,
                    1_700_000_001,
                ),
            )


def test_all_managed_writer_modules_use_the_common_factory() -> None:
    core_dir = Path(__file__).parents[1] / "src" / "waterfallhunter" / "core"

    violations = []
    for module_name in WRITER_MODULES:
        source = (core_dir / module_name).read_text(encoding="utf-8")
        if "sqlite3.connect" in source:
            violations.append(module_name)
        if "connect_managed_sqlite" not in source:
            violations.append(f"{module_name}:factory-missing")

    assert violations == []


def test_factory_closes_when_foreign_keys_cannot_be_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConnection:
        closed = False

        def execute(self, sql: str):
            if sql == "PRAGMA foreign_keys=ON":
                return self
            if sql == "PRAGMA foreign_keys":
                return self
            raise AssertionError(f"unexpected SQL before verification: {sql}")

        def fetchone(self):
            return (0,)

        def close(self) -> None:
            self.closed = True

    fake = FakeConnection()
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: fake)

    with pytest.raises(ManagedSQLiteError, match="FOREIGN_KEYS_UNAVAILABLE"):
        connect_managed_sqlite("ignored.db")

    assert fake.closed is True


def test_factory_wraps_connection_creation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_connect(*args, **kwargs):
        raise sqlite3.OperationalError("injected open failure")

    monkeypatch.setattr(sqlite3, "connect", fail_connect)

    with pytest.raises(ManagedSQLiteError, match="FOREIGN_KEYS_UNAVAILABLE"):
        connect_managed_sqlite("unopenable.db")
