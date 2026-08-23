from __future__ import annotations

import sqlite3
from pathlib import Path


class ManagedSQLiteError(RuntimeError):
    """Raised before mutation when managed SQLite invariants are unavailable."""


def connect_managed_sqlite(
    database: str | Path,
    *,
    timeout: float = 5.0,
    isolation_level: str | None = "DEFERRED",
    uri: bool = False,
) -> sqlite3.Connection:
    """Open a managed connection with verified foreign-key enforcement."""

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(
            str(database),
            timeout=timeout,
            isolation_level=isolation_level,
            uri=uri,
        )
        conn.execute("PRAGMA foreign_keys=ON")
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        if row != (1,):
            raise ManagedSQLiteError("MANAGED_SQLITE_FOREIGN_KEYS_UNAVAILABLE")
        return conn
    except Exception as exc:
        if conn is not None:
            conn.close()
        if isinstance(exc, ManagedSQLiteError):
            raise
        raise ManagedSQLiteError(
            "MANAGED_SQLITE_FOREIGN_KEYS_UNAVAILABLE"
        ) from exc
