from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from waterfallhunter.core.migrations import MigrationRunner


_FIXTURE = Path(__file__).with_name("fixtures") / "legacy_runtime_schema_v0.fixture"

_OPTIONAL_SCHEMA = """
CREATE TABLE lbank_execution_observations (
    symbol TEXT PRIMARY KEY,
    observation_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    observed_at REAL,
    reason TEXT,
    spread_pct REAL,
    cost_25_pct REAL,
    cost_50_pct REAL,
    cost_100_pct REAL,
    depth_10bps_min_usdt REAL,
    depth_25bps_min_usdt REAL,
    depth_50bps_min_usdt REAL,
    depth_100bps_min_usdt REAL,
    failures INTEGER NOT NULL DEFAULT 0,
    next_check_at REAL NOT NULL DEFAULT 0,
    payload TEXT NOT NULL DEFAULT '{}',
    updated_at REAL NOT NULL
);
CREATE INDEX idx_lbank_execution_queue
ON lbank_execution_observations (next_check_at, observed_at);
CREATE INDEX idx_lbank_execution_status
ON lbank_execution_observations (observation_status);

CREATE TABLE lbank_execution_observation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    observation_status TEXT NOT NULL,
    observed_at REAL NOT NULL,
    reason TEXT,
    spread_pct REAL,
    cost_25_pct REAL,
    cost_50_pct REAL,
    cost_100_pct REAL,
    depth_10bps_min_usdt REAL,
    depth_25bps_min_usdt REAL,
    depth_50bps_min_usdt REAL,
    depth_100bps_min_usdt REAL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX idx_lbank_execution_history_symbol_time
ON lbank_execution_observation_history (symbol, observed_at);
CREATE INDEX idx_lbank_execution_history_status_time
ON lbank_execution_observation_history (observation_status, observed_at);
CREATE INDEX idx_lbank_execution_history_observed_at
ON lbank_execution_observation_history (observed_at);

CREATE TABLE provider_states (
    provider_id TEXT PRIMARY KEY,
    upstream_identity TEXT NOT NULL,
    status TEXT NOT NULL,
    failure_class TEXT NOT NULL,
    consecutive_failures INTEGER NOT NULL,
    circuit_open_until REAL NOT NULL,
    replacement_generation INTEGER NOT NULL,
    last_success_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""


def migrate_test_database(path: Path) -> Path:
    """Create/upgrade one disposable DB through the first-party migration runner."""
    MigrationRunner(db_path=path, source_revision="test").apply()
    return path


def build_legacy_runtime_database(path: Path, *, include_optional: bool = False) -> Path:
    """Create one disposable canonical pre-migration runtime database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sql = _FIXTURE.read_text(encoding="utf-8")
    if include_optional:
        sql += "\n" + _OPTIONAL_SCHEMA
    with sqlite3.connect(path) as conn:
        conn.executescript(sql)
    return path


def user_table_names(path: Path) -> list[str]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    return [str(row[0]) for row in rows]


def business_row_hashes(path: Path, tables: tuple[str, ...]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            rows = conn.execute(f"SELECT * FROM {quoted} ORDER BY rowid").fetchall()
            payload = [dict(row) for row in rows]
            canonical = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
            ).encode("utf-8")
            hashes[table] = hashlib.sha256(canonical).hexdigest()
    return hashes
