from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Iterable


_MIGRATION_FILENAME = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")
_SCHEMA_MIGRATIONS_TABLE = "schema_migrations"


class MigrationError(RuntimeError):
    """Base class for migration-system failures."""


class MigrationDiscoveryError(MigrationError):
    """Raised when packaged migration definitions are ambiguous or invalid."""


class MigrationChecksumMismatch(MigrationError):
    """Raised when applied migration bytes no longer match immutable history."""


class MigrationStateError(MigrationError):
    """Raised when SQLite schema-version state is internally inconsistent."""


@dataclass(frozen=True, slots=True)
class Migration:
    """Immutable migration identity, exact SQL bytes, and content checksum."""

    version: int
    name: str
    filename: str
    sql_bytes: bytes
    checksum_sha256: str

    @classmethod
    def from_bytes(
        cls,
        *,
        version: int,
        name: str,
        filename: str,
        sql_bytes: bytes,
    ) -> "Migration":
        """Build a migration after enforcing canonical filename identity."""
        if version < 1:
            raise MigrationDiscoveryError("migration versions must be positive")
        if not name:
            raise MigrationDiscoveryError("migration name must not be empty")
        if not filename:
            raise MigrationDiscoveryError("migration filename must not be empty")
        if not isinstance(sql_bytes, bytes):
            raise MigrationDiscoveryError("migration SQL must be raw bytes")

        match = _MIGRATION_FILENAME.fullmatch(filename)
        if match is None:
            raise MigrationDiscoveryError("migration filename is not canonical")
        if int(match.group("version")) != int(version) or match.group("name") != str(name):
            raise MigrationDiscoveryError(
                "migration filename does not match declared version/name"
            )

        return cls(
            version=int(version),
            name=str(name),
            filename=str(filename),
            sql_bytes=sql_bytes,
            checksum_sha256=hashlib.sha256(sql_bytes).hexdigest(),
        )


def validate_migrations(migrations: Iterable[Migration]) -> tuple[Migration, ...]:
    """Return a canonical contiguous migration sequence or fail closed."""
    ordered = tuple(sorted(tuple(migrations), key=lambda item: item.version))
    if not ordered:
        return ()

    versions = [item.version for item in ordered]
    if len(set(versions)) != len(versions):
        raise MigrationDiscoveryError("duplicate migration version")

    expected = list(range(1, len(ordered) + 1))
    if versions != expected:
        raise MigrationDiscoveryError(
            "migration versions must be contiguous and start at version 1"
        )

    filenames = [item.filename for item in ordered]
    if len(set(filenames)) != len(filenames):
        raise MigrationDiscoveryError("duplicate migration filename")

    return ordered


def discover_migrations(
    package: str = "waterfallhunter.migrations",
) -> tuple[Migration, ...]:
    """Discover and validate packaged SQL migrations using exact file bytes."""
    discovered: list[Migration] = []

    try:
        root = resources.files(package)
    except (ModuleNotFoundError, TypeError) as exc:
        raise MigrationDiscoveryError(
            f"migration package is unavailable: {package}"
        ) from exc

    for entry in root.iterdir():
        if not entry.name.endswith(".sql"):
            continue

        match = _MIGRATION_FILENAME.fullmatch(entry.name)
        if match is None:
            raise MigrationDiscoveryError(
                f"invalid migration filename: {entry.name}"
            )

        sql_bytes = entry.read_bytes()
        discovered.append(
            Migration.from_bytes(
                version=int(match.group("version")),
                name=match.group("name"),
                filename=entry.name,
                sql_bytes=sql_bytes,
            )
        )

    return validate_migrations(discovered)


def _split_sql_statements(sql_bytes: bytes) -> tuple[str, ...]:
    """Split UTF-8 SQL only at SQLite-complete statement boundaries."""
    try:
        sql = sql_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MigrationError("migration SQL must be valid UTF-8") from exc

    statements: list[str] = []
    buffer: list[str] = []
    for character in sql:
        buffer.append(character)
        if character != ";":
            continue
        candidate = "".join(buffer)
        if sqlite3.complete_statement(candidate):
            statements.append(candidate.strip())
            buffer.clear()

    remainder = "".join(buffer).strip()
    if remainder:
        if sqlite3.complete_statement(remainder):
            statements.append(remainder)
        else:
            raise MigrationError("migration SQL contains an incomplete statement")

    return tuple(statement for statement in statements if statement)


class MigrationRunner:
    """Apply immutable, checksum-verified SQLite migrations."""

    def __init__(
        self,
        *,
        db_path: str | Path,
        migrations: Iterable[Migration] | None = None,
        busy_timeout_ms: int = 5_000,
        source_revision: str | None = None,
    ) -> None:
        """Configure a runner without opening or mutating the target database."""
        if busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must be non-negative")
        self._db_path = Path(db_path)
        self._migrations = validate_migrations(
            discover_migrations() if migrations is None else migrations
        )
        self._busy_timeout_ms = int(busy_timeout_ms)
        self._source_revision = source_revision

    def apply(self) -> tuple[int, ...]:
        """Apply pending migrations and return their versions in applied order."""
        if not self._db_path.parent.is_dir():
            raise MigrationError("database parent directory does not exist")

        timeout_seconds = max(self._busy_timeout_ms / 1_000.0, 0.001)

        try:
            conn = sqlite3.connect(
                self._db_path,
                timeout=timeout_seconds,
                isolation_level=None,
            )
        except sqlite3.Error as exc:
            raise MigrationError("database open failed") from exc

        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
            self._bootstrap_history(conn)
            applied_versions = self._verify_state(conn)

            newly_applied: list[int] = []
            for migration in self._migrations:
                if migration.version in applied_versions:
                    continue
                self._apply_one(conn, migration)
                newly_applied.append(migration.version)
                applied_versions = self._verify_state(conn)

            return tuple(newly_applied)
        finally:
            conn.close()

    @staticmethod
    def _bootstrap_history(conn: sqlite3.Connection) -> None:
        """Create immutable migration-history infrastructure atomically."""
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    checksum_sha256 TEXT NOT NULL,
                    applied_at INTEGER NOT NULL,
                    source_revision TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS schema_migrations_no_update
                BEFORE UPDATE ON schema_migrations
                BEGIN
                    SELECT RAISE(ABORT, 'schema_migrations is immutable');
                END
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS schema_migrations_no_delete
                BEFORE DELETE ON schema_migrations
                BEGIN
                    SELECT RAISE(ABORT, 'schema_migrations is immutable');
                END
                """
            )
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            if conn.in_transaction:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise MigrationError("migration history bootstrap failed") from exc

    def _verify_state(self, conn: sqlite3.Connection) -> set[int]:
        """Validate history shape, checksums, and ``user_version`` consistency."""
        try:
            rows = conn.execute(
                "SELECT version, name, checksum_sha256 "
                "FROM schema_migrations ORDER BY version"
            ).fetchall()
            user_version_row = conn.execute("PRAGMA user_version").fetchone()
            user_version = int(user_version_row[0])
            history_versions = [int(row[0]) for row in rows]
        except (sqlite3.Error, TypeError, ValueError, IndexError) as exc:
            raise MigrationStateError("migration history state is malformed") from exc

        expected_history = list(range(1, len(history_versions) + 1))
        if history_versions != expected_history:
            raise MigrationStateError("migration history is not contiguous")

        expected_user_version = history_versions[-1] if history_versions else 0
        if user_version != expected_user_version:
            raise MigrationStateError(
                "PRAGMA user_version disagrees with migration history"
            )

        migrations_by_version = {
            migration.version: migration for migration in self._migrations
        }
        for version, name, checksum in rows:
            migration = migrations_by_version.get(int(version))
            if migration is None:
                raise MigrationStateError(
                    "applied migration version is missing from the migration set"
                )
            if str(name) != migration.name:
                raise MigrationStateError("applied migration name has changed")
            if str(checksum) != migration.checksum_sha256:
                raise MigrationChecksumMismatch(
                    "applied migration checksum does not match migration bytes"
                )

        return set(history_versions)

    def _apply_one(self, conn: sqlite3.Connection, migration: Migration) -> None:
        """Apply one migration and advance history/version in one transaction."""
        statements = _split_sql_statements(migration.sql_bytes)
        if not statements:
            raise MigrationError("migration SQL must contain at least one statement")

        try:
            conn.execute("BEGIN IMMEDIATE")
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                """
                INSERT INTO schema_migrations (
                    version,
                    name,
                    checksum_sha256,
                    applied_at,
                    source_revision
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    migration.version,
                    migration.name,
                    migration.checksum_sha256,
                    int(time.time()),
                    self._source_revision,
                ),
            )
            conn.execute(f"PRAGMA user_version={migration.version}")
            conn.execute("COMMIT")
        except Exception as exc:
            if conn.in_transaction:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            if isinstance(exc, MigrationError):
                raise
            raise MigrationError(
                f"migration version {migration.version} failed"
            ) from exc
