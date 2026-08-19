from __future__ import annotations

import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DatabaseReadinessResult:
    ready: bool
    schema_version: int | None
    expected_schema_version: int
    read_ok: bool
    write_rollback_ok: bool
    integrity_ok: bool | None
    foreign_keys_ok: bool | None
    residue_count: int | None
    reason_codes: tuple[str, ...]
    checked_at: int


class DatabaseNotReadyError(RuntimeError):
    """Raised when a caller requires a ready database but the probe failed."""

    def __init__(self, result: DatabaseReadinessResult) -> None:
        self.result = result
        reasons = ",".join(result.reason_codes) or "UNKNOWN"
        super().__init__(f"database is not ready: {reasons}")


def require_ready(result: DatabaseReadinessResult) -> DatabaseReadinessResult:
    if not result.ready:
        raise DatabaseNotReadyError(result)
    return result


def _result(
    *,
    expected_schema_version: int,
    schema_version: int | None,
    read_ok: bool,
    write_rollback_ok: bool,
    integrity_ok: bool | None,
    foreign_keys_ok: bool | None,
    residue_count: int | None,
    reason_codes: list[str],
    checked_at: int,
) -> DatabaseReadinessResult:
    unique_reasons = tuple(dict.fromkeys(reason_codes))
    ready = (
        not unique_reasons
        and read_ok
        and write_rollback_ok
        and residue_count == 0
        and integrity_ok is not False
        and foreign_keys_ok is not False
        and schema_version == expected_schema_version
    )
    return DatabaseReadinessResult(
        ready=ready,
        schema_version=schema_version,
        expected_schema_version=expected_schema_version,
        read_ok=read_ok,
        write_rollback_ok=write_rollback_ok,
        integrity_ok=integrity_ok,
        foreign_keys_ok=foreign_keys_ok,
        residue_count=residue_count,
        reason_codes=unique_reasons,
        checked_at=checked_at,
    )


def _required_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name IN ('schema_migrations', 'db_readiness_probe')"
    ).fetchall()
    return {str(row[0]) for row in rows}


def probe_database(
    *,
    db_path: str | Path,
    expected_schema_version: int,
    busy_timeout_ms: int = 1_000,
    check_integrity: bool = False,
    check_foreign_keys: bool = False,
) -> DatabaseReadinessResult:
    """Perform a bounded, rollback-only deep readiness probe.

    This primitive intentionally does not create the database, repair data, or
    mutate business tables. The only write targets the dedicated
    ``db_readiness_probe`` table and is rolled back before returning.
    """

    checked_at = int(time.time())
    path = Path(db_path)
    reasons: list[str] = []
    schema_version: int | None = None
    read_ok = False
    write_rollback_ok = False
    integrity_ok: bool | None = None
    foreign_keys_ok: bool | None = None
    residue_count: int | None = None

    if expected_schema_version < 0:
        reasons.append("SCHEMA_VERSION_MISMATCH")
        return _result(
            expected_schema_version=expected_schema_version,
            schema_version=None,
            read_ok=False,
            write_rollback_ok=False,
            integrity_ok=None,
            foreign_keys_ok=None,
            residue_count=None,
            reason_codes=reasons,
            checked_at=checked_at,
        )

    if busy_timeout_ms < 0:
        raise ValueError("busy_timeout_ms must be non-negative")

    if not path.is_file():
        reasons.append("DB_PATH_MISSING")
        return _result(
            expected_schema_version=expected_schema_version,
            schema_version=None,
            read_ok=False,
            write_rollback_ok=False,
            integrity_ok=None,
            foreign_keys_ok=None,
            residue_count=None,
            reason_codes=reasons,
            checked_at=checked_at,
        )

    timeout_seconds = max(busy_timeout_ms / 1_000.0, 0.001)
    uri = f"file:{path.resolve().as_posix()}?mode=rw"

    try:
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=timeout_seconds,
            isolation_level=None,
        )
    except sqlite3.Error:
        reasons.append("OPEN_FAILED")
        return _result(
            expected_schema_version=expected_schema_version,
            schema_version=None,
            read_ok=False,
            write_rollback_ok=False,
            integrity_ok=None,
            foreign_keys_ok=None,
            residue_count=None,
            reason_codes=reasons,
            checked_at=checked_at,
        )

    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")

        try:
            schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        except (sqlite3.Error, TypeError, ValueError, IndexError):
            reasons.append("READ_FAILED")
            return _result(
                expected_schema_version=expected_schema_version,
                schema_version=None,
                read_ok=False,
                write_rollback_ok=False,
                integrity_ok=None,
                foreign_keys_ok=None,
                residue_count=None,
                reason_codes=reasons,
                checked_at=checked_at,
            )

        if schema_version != expected_schema_version:
            reasons.append("SCHEMA_VERSION_MISMATCH")
            return _result(
                expected_schema_version=expected_schema_version,
                schema_version=schema_version,
                read_ok=False,
                write_rollback_ok=False,
                integrity_ok=None,
                foreign_keys_ok=None,
                residue_count=None,
                reason_codes=reasons,
                checked_at=checked_at,
            )

        try:
            tables = _required_tables(conn)
        except sqlite3.Error:
            reasons.append("READ_FAILED")
            return _result(
                expected_schema_version=expected_schema_version,
                schema_version=schema_version,
                read_ok=False,
                write_rollback_ok=False,
                integrity_ok=None,
                foreign_keys_ok=None,
                residue_count=None,
                reason_codes=reasons,
                checked_at=checked_at,
            )

        if tables != {"schema_migrations", "db_readiness_probe"}:
            reasons.append("REQUIRED_TABLE_MISSING")
            return _result(
                expected_schema_version=expected_schema_version,
                schema_version=schema_version,
                read_ok=False,
                write_rollback_ok=False,
                integrity_ok=None,
                foreign_keys_ok=None,
                residue_count=None,
                reason_codes=reasons,
                checked_at=checked_at,
            )

        try:
            conn.execute("SELECT version FROM schema_migrations ORDER BY version LIMIT 1").fetchone()
            conn.execute("SELECT COUNT(*) FROM db_readiness_probe").fetchone()
            read_ok = True
        except sqlite3.Error:
            reasons.append("READ_FAILED")

        if not read_ok:
            return _result(
                expected_schema_version=expected_schema_version,
                schema_version=schema_version,
                read_ok=False,
                write_rollback_ok=False,
                integrity_ok=None,
                foreign_keys_ok=None,
                residue_count=None,
                reason_codes=reasons,
                checked_at=checked_at,
            )

        if check_integrity:
            try:
                rows = conn.execute("PRAGMA integrity_check").fetchall()
                integrity_ok = len(rows) == 1 and str(rows[0][0]).lower() == "ok"
            except sqlite3.Error:
                integrity_ok = False
            if not integrity_ok:
                reasons.append("INTEGRITY_CHECK_FAILED")

        if check_foreign_keys:
            try:
                foreign_keys_ok = len(conn.execute("PRAGMA foreign_key_check").fetchall()) == 0
            except sqlite3.Error:
                foreign_keys_ok = False
            if not foreign_keys_ok:
                reasons.append("FOREIGN_KEY_CHECK_FAILED")

        if reasons:
            return _result(
                expected_schema_version=expected_schema_version,
                schema_version=schema_version,
                read_ok=read_ok,
                write_rollback_ok=False,
                integrity_ok=integrity_ok,
                foreign_keys_ok=foreign_keys_ok,
                residue_count=None,
                reason_codes=reasons,
                checked_at=checked_at,
            )

        probe_id = secrets.token_hex(16)
        transaction_started = False
        try:
            conn.execute("BEGIN DEFERRED")
            transaction_started = True
            conn.execute(
                "INSERT INTO db_readiness_probe (probe_id, touched_at) VALUES (?, ?)",
                (probe_id, checked_at),
            )
            row = conn.execute(
                "SELECT probe_id, touched_at FROM db_readiness_probe WHERE probe_id=?",
                (probe_id,),
            ).fetchone()
            if row != (probe_id, checked_at):
                raise sqlite3.DatabaseError("readiness probe read-back mismatch")
            conn.execute("ROLLBACK")
            transaction_started = False
            write_rollback_ok = True
        except sqlite3.Error:
            reasons.append("WRITE_ROLLBACK_FAILED")
        finally:
            if transaction_started and conn.in_transaction:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    if "WRITE_ROLLBACK_FAILED" not in reasons:
                        reasons.append("WRITE_ROLLBACK_FAILED")

        try:
            residue_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM db_readiness_probe WHERE probe_id=?",
                    (probe_id,),
                ).fetchone()[0]
            )
        except (sqlite3.Error, TypeError, ValueError, IndexError):
            residue_count = None
            if "WRITE_ROLLBACK_FAILED" not in reasons:
                reasons.append("WRITE_ROLLBACK_FAILED")

        if residue_count not in (0, None):
            reasons.append("ROLLBACK_RESIDUE")
            write_rollback_ok = False

        return _result(
            expected_schema_version=expected_schema_version,
            schema_version=schema_version,
            read_ok=read_ok,
            write_rollback_ok=write_rollback_ok,
            integrity_ok=integrity_ok,
            foreign_keys_ok=foreign_keys_ok,
            residue_count=residue_count,
            reason_codes=reasons,
            checked_at=checked_at,
        )
    finally:
        conn.close()
