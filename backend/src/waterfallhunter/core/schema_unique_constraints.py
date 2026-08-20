from __future__ import annotations

import sqlite3
from dataclasses import dataclass


CANONICAL_UNIQUE_KEYS: dict[str, frozenset[tuple[str, ...]]] = {
    "lbank_signal_outcomes": frozenset({("signal_id",)}),
    "production_evidence_snapshots": frozenset({("bucket_started_at", "symbol")}),
    "production_feature_replay_results_v2": frozenset(
        {("snapshot_id", "replay_version")}
    ),
    "lbank_execution_decision_log": frozenset(
        {("bucket_started_at", "source", "symbol")}
    ),
    "operational_historical_outcome_datasets": frozenset({("report_sha256",)}),
    "operational_historical_signal_outcomes": frozenset({("event_key",)}),
}


@dataclass(frozen=True, slots=True)
class UniqueConstraintIssue:
    table: str
    expected: tuple[tuple[str, ...], ...]
    actual: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class UniqueConstraintVerificationResult:
    valid: bool
    issues: tuple[UniqueConstraintIssue, ...]


def _actual_unique_keys(
    conn: sqlite3.Connection,
    table: str,
) -> frozenset[tuple[str, ...]]:
    """Return non-primary-key UNIQUE keys using SQLite structural metadata."""
    keys: set[tuple[str, ...]] = set()
    rows = conn.execute(f'PRAGMA index_list("{table}")').fetchall()
    for row in rows:
        if len(row) < 3 or int(row[2]) != 1:
            continue
        origin = str(row[3]).casefold() if len(row) >= 4 else ""
        if origin == "pk":
            continue
        index_name = str(row[1])
        columns = tuple(
            str(index_row[2])
            for index_row in conn.execute(
                f'PRAGMA index_info("{index_name}")'
            ).fetchall()
            if index_row[2] is not None
        )
        if columns:
            keys.add(columns)
    return frozenset(keys)


def verify_unique_constraints_connection(
    conn: sqlite3.Connection,
    *,
    tables: frozenset[str] | None = None,
) -> UniqueConstraintVerificationResult:
    """Verify the exact canonical UNIQUE-key set without mutating SQLite."""
    selected = (
        frozenset(CANONICAL_UNIQUE_KEYS)
        if tables is None
        else frozenset(tables) & frozenset(CANONICAL_UNIQUE_KEYS)
    )
    existing = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    issues: list[UniqueConstraintIssue] = []
    for table in sorted(selected):
        if table not in existing:
            # Missing-table handling belongs to the primary schema verifier.
            continue
        expected = CANONICAL_UNIQUE_KEYS[table]
        actual = _actual_unique_keys(conn, table)
        if actual != expected:
            issues.append(
                UniqueConstraintIssue(
                    table=table,
                    expected=tuple(sorted(expected)),
                    actual=tuple(sorted(actual)),
                )
            )
    return UniqueConstraintVerificationResult(
        valid=not issues,
        issues=tuple(issues),
    )
