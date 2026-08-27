"""Append-only persistence for canonical entry-decision transitions."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from waterfallhunter.core.managed_sqlite import connect_managed_sqlite
from waterfallhunter.core.schema_contract import require_managed_schema
from waterfallhunter.core.signal_metadata import canonical_sha256


_ALLOWED = {
    "NO_TRADE",
    "FORMING",
    "ENTRY_READY",
    "ACTIVE",
    "LATE",
    "INVALIDATED",
    "EXPIRED",
}


class EntryDecisionStore:
    def __init__(self, db_path: str | Path, *, verify_schema: bool = True):
        self.db_path = str(db_path)
        if verify_schema:
            require_managed_schema(
                self.db_path,
                required_tables=frozenset({"entry_decision_events"}),
            )

    @staticmethod
    def _validate_packet(packet: dict[str, Any]) -> tuple[str, int, float, float, str]:
        if packet.get("contract_version") != "entry_decision_v1":
            raise ValueError("entry decision contract version unsupported")
        decision = str(packet.get("decision") or "")
        if decision not in _ALLOWED:
            raise ValueError("entry decision state unsupported")
        event_at = packet.get("evaluated_at")
        readiness = packet.get("entry_readiness")
        coverage = packet.get("evidence_coverage_pct")
        policy_version = str(packet.get("policy_version") or "")
        if isinstance(event_at, bool) or not isinstance(event_at, int) or event_at < 0:
            raise ValueError("entry decision evaluated_at invalid")
        for name, value in (("entry_readiness", readiness), ("evidence_coverage_pct", coverage)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} invalid")
            if not 0 <= float(value) <= 100:
                raise ValueError(f"{name} outside 0..100")
        if not policy_version:
            raise ValueError("entry decision policy_version missing")
        return decision, event_at, float(readiness), float(coverage), policy_version

    @staticmethod
    def _encode(packet: dict[str, Any]) -> tuple[str, str]:
        payload = json.dumps(
            packet,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return payload, canonical_sha256(packet)

    def append_if_changed(self, symbol: str, packet: dict[str, Any]) -> int | None:
        symbol = str(symbol or "").strip()
        if not symbol:
            raise ValueError("symbol missing")
        decision, event_at, readiness, coverage, policy_version = self._validate_packet(packet)
        payload, payload_hash = self._encode(packet)
        lifecycle_state = str(packet.get("lifecycle_state") or "WATCH")
        created_at = int(time.time())
        with connect_managed_sqlite(self.db_path, timeout=10.0) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT decision FROM entry_decision_events "
                "WHERE symbol=? ORDER BY id DESC LIMIT 1",
                (symbol,),
            ).fetchone()
            if row is not None and str(row[0]) == decision:
                return None
            cursor = conn.execute(
                "INSERT INTO entry_decision_events ("
                "symbol,event_at,decision,lifecycle_state,entry_readiness,"
                "evidence_coverage_pct,policy_version,packet_json,packet_hash,created_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    symbol,
                    event_at,
                    decision,
                    lifecycle_state,
                    readiness,
                    coverage,
                    policy_version,
                    payload,
                    payload_hash,
                    created_at,
                ),
            )
            decision_event_id = int(cursor.lastrowid)
            if decision == "ENTRY_READY":
                event_id = f"entry:{decision_event_id}:ready"
                event_payload = {
                    "contract_version": "entry_ready_notification_v1",
                    "event_id": event_id,
                    "event_type": "ENTRY_READY",
                    "decision_event_id": decision_event_id,
                    "symbol": symbol,
                    "decision_packet": packet,
                }
                notification_json, notification_hash = self._encode(event_payload)
                conn.execute(
                    "INSERT INTO entry_notification_outbox ("
                    "event_id,decision_event_id,event_key,event_type,"
                    "payload_contract_version,payload_json,payload_hash,status,"
                    "attempt_count,available_at,lease_owner,lease_expires_at,"
                    "last_error_code,created_at,updated_at"
                    ") VALUES (?,?,?,'ENTRY_READY','entry_ready_notification_v1',"
                    "?,?,'PENDING',0,?,NULL,NULL,NULL,?,?)",
                    (
                        event_id,
                        decision_event_id,
                        event_id,
                        notification_json,
                        notification_hash,
                        event_at,
                        created_at,
                        created_at,
                    ),
                )
            return decision_event_id

    @staticmethod
    def _row_packet(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
        packet = json.loads(str(row[6]))
        packet["event_id"] = int(row[0])
        packet["symbol"] = str(row[1])
        packet["event_at"] = int(row[2])
        packet["decision"] = str(row[3])
        packet["entry_readiness"] = float(row[4])
        packet["evidence_coverage_pct"] = float(row[5])
        if len(row) > 7 and row[7] is not None:
            advisory = json.loads(str(row[7]))
            if isinstance(advisory, dict):
                packet["ai_advisory"] = advisory
        if len(row) > 8:
            packet["previous_decision"] = None if row[8] is None else str(row[8])
        return packet

    def append_advisory(
        self,
        decision_event_id: int,
        advisory: dict[str, Any],
        *,
        advisory_at: int,
    ) -> int:
        if isinstance(decision_event_id, bool) or not isinstance(decision_event_id, int) or decision_event_id <= 0:
            raise ValueError("decision event id invalid")
        if isinstance(advisory_at, bool) or not isinstance(advisory_at, int) or advisory_at < 0:
            raise ValueError("advisory timestamp invalid")
        if advisory.get("observational_only") is not True or advisory.get("decision_mutated") is not False:
            raise ValueError("advisory must be observational only")
        provider = str(advisory.get("ai_provider") or "none")
        model = str(advisory.get("ai_model") or "none")
        status = str(advisory.get("ai_status") or "UNAVAILABLE")
        if status not in {"AVAILABLE", "UNAVAILABLE"}:
            raise ValueError("advisory status invalid")
        persisted = {**advisory, "advisory_at": advisory_at}
        payload, payload_hash = self._encode(persisted)
        created_at = int(time.time())
        with connect_managed_sqlite(self.db_path, timeout=10.0) as conn:
            cursor = conn.execute(
                "INSERT INTO entry_decision_advisories ("
                "decision_event_id,advisory_at,provider,model,status,"
                "advisory_json,advisory_hash,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (decision_event_id, advisory_at, provider, model, status, payload, payload_hash, created_at),
            )
            return int(cursor.lastrowid)

    @staticmethod
    def _history_select(where: str = "") -> str:
        return (
            "SELECT e.id,e.symbol,e.event_at,e.decision,e.entry_readiness,"
            "e.evidence_coverage_pct,e.packet_json,"
            "(SELECT a.advisory_json FROM entry_decision_advisories a "
            " WHERE a.decision_event_id=e.id ORDER BY a.id DESC LIMIT 1),"
            "(SELECT p.decision FROM entry_decision_events p "
            " WHERE p.symbol=e.symbol AND p.id<e.id ORDER BY p.id DESC LIMIT 1) "
            "FROM entry_decision_events e " + where
        )

    def latest_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        with connect_managed_sqlite(self.db_path, timeout=10.0) as conn:
            row = conn.execute(
                self._history_select("WHERE e.symbol=? ORDER BY e.id DESC LIMIT 1"),
                (str(symbol),),
            ).fetchone()
        return None if row is None else self._row_packet(row)

    def history_for_symbol(self, symbol: str, *, limit: int = 20) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 200))
        with connect_managed_sqlite(self.db_path, timeout=10.0) as conn:
            rows = conn.execute(
                self._history_select("WHERE e.symbol=? ORDER BY e.id DESC LIMIT ?"),
                (str(symbol), bounded),
            ).fetchall()
        return [self._row_packet(row) for row in rows]

    def latest_map(self) -> dict[str, dict[str, Any]]:
        query = """
        SELECT e.id,e.symbol,e.event_at,e.decision,e.entry_readiness,
               e.evidence_coverage_pct,e.packet_json
        FROM entry_decision_events e
        INNER JOIN (
            SELECT symbol, MAX(id) AS max_id
            FROM entry_decision_events
            GROUP BY symbol
        ) latest ON latest.max_id = e.id
        """
        with connect_managed_sqlite(self.db_path, timeout=10.0) as conn:
            rows = conn.execute(query).fetchall()
        return {str(row[1]): self._row_packet(row) for row in rows}

    def recent_changes(self, *, limit: int = 20) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 200))
        with connect_managed_sqlite(self.db_path, timeout=10.0) as conn:
            rows = conn.execute(
                self._history_select("ORDER BY e.id DESC LIMIT ?"),
                (bounded,),
            ).fetchall()
        return [self._row_packet(row) for row in rows]
