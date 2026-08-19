from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from importlib import resources
from typing import Iterable


_MIGRATION_FILENAME = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")


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
        if version < 1:
            raise MigrationDiscoveryError("migration versions must be positive")
        if not name:
            raise MigrationDiscoveryError("migration name must not be empty")
        if not filename:
            raise MigrationDiscoveryError("migration filename must not be empty")
        if not isinstance(sql_bytes, bytes):
            raise MigrationDiscoveryError("migration SQL must be raw bytes")
        return cls(
            version=int(version),
            name=str(name),
            filename=str(filename),
            sql_bytes=sql_bytes,
            checksum_sha256=hashlib.sha256(sql_bytes).hexdigest(),
        )


def validate_migrations(migrations: Iterable[Migration]) -> tuple[Migration, ...]:
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
