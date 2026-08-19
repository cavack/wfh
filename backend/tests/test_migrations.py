import hashlib
from importlib import resources

import pytest


def _migrations_module():
    from waterfallhunter.core import migrations

    return migrations


def test_package_migration_discovery_is_contiguous_and_hashes_exact_bytes():
    migrations = _migrations_module()

    discovered = migrations.discover_migrations()

    assert len(discovered) == 1
    migration = discovered[0]
    assert migration.version == 1
    assert migration.name == "db_readiness_probe"
    assert migration.filename == "0001_db_readiness_probe.sql"

    raw = (
        resources.files("waterfallhunter.migrations")
        .joinpath("0001_db_readiness_probe.sql")
        .read_bytes()
    )
    assert migration.sql_bytes == raw
    assert migration.checksum_sha256 == hashlib.sha256(raw).hexdigest()


def test_validate_migrations_rejects_duplicate_versions():
    migrations = _migrations_module()
    first = migrations.Migration.from_bytes(
        version=1,
        name="first",
        filename="0001_first.sql",
        sql_bytes=b"SELECT 1;\n",
    )
    duplicate = migrations.Migration.from_bytes(
        version=1,
        name="duplicate",
        filename="0001_duplicate.sql",
        sql_bytes=b"SELECT 2;\n",
    )

    with pytest.raises(migrations.MigrationDiscoveryError):
        migrations.validate_migrations((first, duplicate))


def test_validate_migrations_rejects_gaps_and_non_one_start():
    migrations = _migrations_module()
    version_two = migrations.Migration.from_bytes(
        version=2,
        name="second",
        filename="0002_second.sql",
        sql_bytes=b"SELECT 2;\n",
    )

    with pytest.raises(migrations.MigrationDiscoveryError):
        migrations.validate_migrations((version_two,))

    version_one = migrations.Migration.from_bytes(
        version=1,
        name="first",
        filename="0001_first.sql",
        sql_bytes=b"SELECT 1;\n",
    )
    version_three = migrations.Migration.from_bytes(
        version=3,
        name="third",
        filename="0003_third.sql",
        sql_bytes=b"SELECT 3;\n",
    )

    with pytest.raises(migrations.MigrationDiscoveryError):
        migrations.validate_migrations((version_one, version_three))


def test_migration_checksum_is_stable_and_content_sensitive():
    migrations = _migrations_module()
    left = migrations.Migration.from_bytes(
        version=1,
        name="probe",
        filename="0001_probe.sql",
        sql_bytes=b"SELECT 1;\n",
    )
    same = migrations.Migration.from_bytes(
        version=1,
        name="probe",
        filename="0001_probe.sql",
        sql_bytes=b"SELECT 1;\n",
    )
    changed = migrations.Migration.from_bytes(
        version=1,
        name="probe",
        filename="0001_probe.sql",
        sql_bytes=b"SELECT 2;\n",
    )

    assert left.checksum_sha256 == same.checksum_sha256
    assert left.checksum_sha256 != changed.checksum_sha256
