from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from waterfallhunter.core.migrations import MigrationError, MigrationRunner
from waterfallhunter.core.schema_contract import (
    CURRENT_RUNTIME_SCHEMA_VERSION,
    SchemaContractError,
    managed_runtime_table_names,
    verify_managed_schema_connection,
)
from waterfallhunter.core.schema_unique_constraints import (
    verify_unique_constraints_connection,
)


class PreflightState(str, Enum):
    CLEAN_NEW = "CLEAN_NEW"
    CLEAN_EMPTY = "CLEAN_EMPTY"
    LEGACY_CANONICAL = "LEGACY_CANONICAL"
    MIGRATED_COMPATIBLE = "MIGRATED_COMPATIBLE"
    PARTIAL_OR_INCOMPATIBLE = "PARTIAL_OR_INCOMPATIBLE"


@dataclass(frozen=True, slots=True)
class PreflightResult:
    state: PreflightState
    compatible: bool
    user_version: int | None
    applied_versions: tuple[int, ...]
    reason_codes: tuple[str, ...]
    unknown_user_objects: tuple[str, ...] = ()


class MigrationPreflightError(RuntimeError):
    """Raised when a target is not safe for the explicit migration command."""

    def __init__(self, result: PreflightResult) -> None:
        self.result = result
        reasons = ",".join(result.reason_codes) or result.state.value
        super().__init__(f"database migration preflight failed: {reasons}")


_LEGACY_OPTIONAL_TABLES = frozenset(
    {
        "lbank_execution_observations",
        "lbank_execution_observation_history",
        "provider_states",
    }
)


def _result(
    state: PreflightState,
    *,
    user_version: int | None = None,
    applied_versions: tuple[int, ...] = (),
    reason_codes: tuple[str, ...] = (),
    unknown_user_objects: tuple[str, ...] = (),
) -> PreflightResult:
    return PreflightResult(
        state=state,
        compatible=state is not PreflightState.PARTIAL_OR_INCOMPATIBLE,
        user_version=user_version,
        applied_versions=applied_versions,
        reason_codes=reason_codes,
        unknown_user_objects=unknown_user_objects,
    )


def _incompatible(
    reason_code: str,
    *,
    user_version: int | None = None,
    unknown_user_objects: tuple[str, ...] = (),
) -> PreflightResult:
    return _result(
        PreflightState.PARTIAL_OR_INCOMPATIBLE,
        user_version=user_version,
        reason_codes=(reason_code,),
        unknown_user_objects=unknown_user_objects,
    )


def _open_read_only(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    return sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5.0)


def _user_tables(conn: sqlite3.Connection) -> frozenset[str]:
    return frozenset(
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    )


def _managed_constraints_valid(conn: sqlite3.Connection) -> bool:
    return verify_unique_constraints_connection(
        conn,
        tables=managed_runtime_table_names(),
    ).valid


def _classify_migrated(path: Path, user_version: int) -> PreflightResult:
    try:
        applied = MigrationRunner(db_path=path).verify()
    except MigrationError:
        return _incompatible(
            "MIGRATION_HISTORY_INVALID",
            user_version=user_version,
        )

    if not applied:
        return _incompatible(
            "MIGRATION_HISTORY_INVALID",
            user_version=user_version,
        )

    try:
        with _open_read_only(path) as conn:
            if 1 in applied:
                probe = conn.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type='table' AND name='db_readiness_probe'"
                ).fetchone()
                if probe is None:
                    return _incompatible(
                        "MIGRATION_SCHEMA_MISMATCH",
                        user_version=user_version,
                    )

            unknown: tuple[str, ...] = ()
            if CURRENT_RUNTIME_SCHEMA_VERSION in applied:
                schema = verify_managed_schema_connection(
                    conn,
                    check_user_version=CURRENT_RUNTIME_SCHEMA_VERSION,
                )
                if not schema.valid or not _managed_constraints_valid(conn):
                    return _incompatible(
                        "MIGRATION_SCHEMA_MISMATCH",
                        user_version=user_version,
                        unknown_user_objects=schema.unknown_user_objects,
                    )
                unknown = schema.unknown_user_objects
    except (sqlite3.Error, SchemaContractError):
        return _incompatible(
            "MIGRATION_SCHEMA_MISMATCH",
            user_version=user_version,
        )

    return _result(
        PreflightState.MIGRATED_COMPATIBLE,
        user_version=user_version,
        applied_versions=applied,
        unknown_user_objects=unknown,
    )


def classify_database(db_path: str | Path) -> PreflightResult:
    """Classify one migration target without creating, repairing, or writing it."""
    path = Path(db_path)

    if not path.exists():
        if not path.parent.is_dir():
            return _incompatible("DB_PARENT_MISSING")
        return _result(PreflightState.CLEAN_NEW, user_version=0)

    if not path.is_file():
        return _incompatible("DB_PATH_NOT_FILE")

    # A SQLite connection can create an intentionally empty zero-byte file.
    # Treat it as CLEAN_EMPTY without opening it in a mode that could initialize it.
    if path.stat().st_size == 0:
        return _result(PreflightState.CLEAN_EMPTY, user_version=0)

    try:
        conn = _open_read_only(path)
    except sqlite3.Error:
        return _incompatible("DB_OPEN_FAILED")

    try:
        try:
            row = conn.execute("PRAGMA user_version").fetchone()
            user_version = int(row[0]) if row else 0
            tables = _user_tables(conn)
        except (sqlite3.Error, TypeError, ValueError, IndexError):
            return _incompatible("DB_METADATA_UNREADABLE")

        if not tables:
            if user_version == 0:
                return _result(PreflightState.CLEAN_EMPTY, user_version=0)
            return _incompatible(
                "EMPTY_USER_VERSION_INVALID",
                user_version=user_version,
            )

        if "schema_migrations" in tables:
            # Close this read-only handle before MigrationRunner.verify opens its own.
            pass
        else:
            if user_version != 0:
                return _incompatible(
                    "LEGACY_USER_VERSION_INVALID",
                    user_version=user_version,
                )
            schema = verify_managed_schema_connection(
                conn,
                required_tables=managed_runtime_table_names(),
                allow_missing_tables=_LEGACY_OPTIONAL_TABLES,
                check_user_version=0,
            )
            if not schema.valid or not _managed_constraints_valid(conn):
                return _incompatible(
                    "LEGACY_SCHEMA_MISMATCH",
                    user_version=0,
                    unknown_user_objects=schema.unknown_user_objects,
                )
            return _result(
                PreflightState.LEGACY_CANONICAL,
                user_version=0,
                unknown_user_objects=schema.unknown_user_objects,
            )
    finally:
        conn.close()

    return _classify_migrated(path, user_version)


def require_migration_compatible(db_path: str | Path) -> PreflightResult:
    """Return an allowed preflight result or fail closed with a typed error."""
    result = classify_database(db_path)
    if not result.compatible:
        raise MigrationPreflightError(result)
    return result
