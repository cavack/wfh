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


class StaleCandidateLifecycleError(RuntimeError):
    """Raised when an in-flight candidate no longer owns the catalogue lifecycle."""


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

    @staticmethod
    def _material_projection(packet: dict[str, Any]) -> dict[str, Any]:
        advisory = packet.get("leverage_advisory")
        leverage_advisory = advisory if isinstance(advisory, dict) else None
        execution_input = (
            leverage_advisory.get("execution_suitability_input")
            if leverage_advisory is not None
            and isinstance(leverage_advisory.get("execution_suitability_input"), dict)
            else {}
        )
        material_execution_input = {
            "available": execution_input.get("available"),
            "status": execution_input.get("status"),
            "maximum_leverage": execution_input.get("maximum_leverage"),
        }
        plan = packet.get("trade_plan")
        plan_leverage = plan.get("leverage") if isinstance(plan, dict) else None
        return {
            "decision": packet.get("decision"),
            "lifecycle_id": packet.get("lifecycle_id"),
            "lifecycle_state": packet.get("lifecycle_state"),
            "late_origin": packet.get("late_origin"),
            "block_reasons": sorted(
                str(reason) for reason in (packet.get("block_reasons") or [])
            ),
            "policy_version": packet.get("policy_version"),
            "leverage_advisory": None if leverage_advisory is None else {
                "status": leverage_advisory.get("status"),
                "leverage": leverage_advisory.get("leverage"),
                "policy_version": leverage_advisory.get("policy_version"),
                "reason": leverage_advisory.get("reason"),
                "execution_suitability_input": material_execution_input,
                "causal_input": (
                    leverage_advisory.get("causal_input")
                    if isinstance(leverage_advisory.get("causal_input"), dict)
                    else None
                ),
            },
            "trade_plan_leverage": plan_leverage,
        }

    def append_if_changed(
        self,
        symbol: str,
        packet: dict[str, Any],
        *,
        expected_lifecycle_id: int | None = None,
    ) -> int | None:
        symbol = str(symbol or "").strip()
        if not symbol:
            raise ValueError("symbol missing")
        if expected_lifecycle_id is not None and (
            isinstance(expected_lifecycle_id, bool)
            or not isinstance(expected_lifecycle_id, int)
            or expected_lifecycle_id < 1
        ):
            raise ValueError("expected_lifecycle_id must be a positive integer")
        decision, event_at, readiness, coverage, policy_version = self._validate_packet(packet)
        payload, payload_hash = self._encode(packet)
        lifecycle_state = str(packet.get("lifecycle_state") or "WATCH")
        created_at = int(time.time())
        with connect_managed_sqlite(self.db_path, timeout=10.0) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if expected_lifecycle_id is not None:
                catalog = conn.execute(
                    "SELECT lifecycle_id,scan_eligible,status FROM lbank_catalog WHERE symbol=?",
                    (symbol,),
                ).fetchone()
                if (
                    catalog is None
                    or int(catalog[0] or 0) != expected_lifecycle_id
                    or not bool(catalog[1])
                    or str(catalog[2] or "") == "REMOVED"
                ):
                    raise StaleCandidateLifecycleError(
                        "candidate lifecycle is no longer current"
                    )
            row = conn.execute(
                "SELECT decision,packet_json,packet_hash FROM entry_decision_events "
                "WHERE symbol=? ORDER BY id DESC LIMIT 1",
                (symbol,),
            ).fetchone()
            previous_packet: dict[str, Any] | None = None
            if row is not None:
                previous_packet = self._verified_record(
                    row[1], row[2], label="previous entry decision packet"
                )
                if (
                    str(row[0]) == decision
                    and canonical_sha256(self._material_projection(previous_packet))
                    == canonical_sha256(self._material_projection(packet))
                ):
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
            previous_decision = str(previous_packet.get("decision") or "") if previous_packet else ""
            previous_lifecycle_id = previous_packet.get("lifecycle_id") if previous_packet else None
            current_lifecycle_id = packet.get("lifecycle_id")
            entry_ready_transition = bool(
                decision == "ENTRY_READY"
                and (
                    previous_decision != "ENTRY_READY"
                    or previous_lifecycle_id != current_lifecycle_id
                )
            )
            if entry_ready_transition:
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
    def _verified_record(raw_json: Any, expected_hash: Any, *, label: str) -> dict[str, Any]:
        try:
            decoded = json.loads(str(raw_json))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"{label} JSON invalid") from exc
        if not isinstance(decoded, dict):
            raise ValueError(f"{label} must be a JSON object")
        if canonical_sha256(decoded) != str(expected_hash or ""):
            raise ValueError(f"{label} hash mismatch")
        return decoded

    @classmethod
    def _row_packet(cls, row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
        if len(row) < 8:
            raise ValueError("entry decision row missing packet hash")
        packet = cls._verified_record(row[6], row[7], label="packet")
        packet["event_id"] = int(row[0])
        packet["symbol"] = str(row[1])
        packet["event_at"] = int(row[2])
        packet["decision"] = str(row[3])
        packet["entry_readiness"] = float(row[4])
        packet["evidence_coverage_pct"] = float(row[5])
        if len(row) > 8 and row[8] is not None:
            if len(row) < 10:
                raise ValueError("entry decision advisory row missing advisory hash")
            advisory = cls._verified_record(row[8], row[9], label="advisory")
            packet["ai_advisory"] = advisory
        if len(row) > 10:
            packet["previous_decision"] = None if row[10] is None else str(row[10])
        return packet

    def append_advisory(
        self,
        decision_event_id: int,
        advisory: dict[str, Any],
        *,
        advisory_at: int,
    ) -> int:
        if (
            isinstance(decision_event_id, bool)
            or not isinstance(decision_event_id, int)
            or decision_event_id <= 0
        ):
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

    def ensure_unavailable_advisory(
        self,
        decision_event_id: int,
        *,
        advisory_at: int,
        reason: str,
    ) -> int:
        if (
            isinstance(decision_event_id, bool)
            or not isinstance(decision_event_id, int)
            or decision_event_id <= 0
        ):
            raise ValueError("decision event id invalid")
        if (
            isinstance(advisory_at, bool)
            or not isinstance(advisory_at, int)
            or advisory_at < 0
        ):
            raise ValueError("advisory timestamp invalid")
        normalized_reason = str(reason or "").strip()
        if not normalized_reason:
            raise ValueError("advisory fallback reason missing")
        advisory = {
            "observational_only": True,
            "decision_mutated": False,
            "ai_advice": "UNAVAILABLE",
            "ai_confidence": 0,
            "ai_reasoning": normalized_reason,
            "ai_provider": "none",
            "ai_model": "none",
            "ai_status": "UNAVAILABLE",
            "advisory_at": advisory_at,
        }
        payload, payload_hash = self._encode(advisory)
        created_at = int(time.time())
        with connect_managed_sqlite(self.db_path, timeout=10.0) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT id FROM entry_decision_advisories "
                "WHERE decision_event_id=? ORDER BY id DESC LIMIT 1",
                (decision_event_id,),
            ).fetchone()
            if existing is not None:
                return int(existing[0])
            decision = conn.execute(
                "SELECT id FROM entry_decision_events WHERE id=?",
                (decision_event_id,),
            ).fetchone()
            if decision is None:
                raise ValueError("decision event missing")
            cursor = conn.execute(
                "INSERT INTO entry_decision_advisories ("
                "decision_event_id,advisory_at,provider,model,status,"
                "advisory_json,advisory_hash,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    decision_event_id,
                    advisory_at,
                    "none",
                    "none",
                    "UNAVAILABLE",
                    payload,
                    payload_hash,
                    created_at,
                ),
            )
            return int(cursor.lastrowid)

    def append_outcome_capture(
        self,
        decision_event_id: int,
        capture: dict[str, Any],
        *,
        captured_at: int,
    ) -> int:
        """Persist one observational outcome capture for a canonical decision."""
        if isinstance(decision_event_id, bool) or not isinstance(decision_event_id, int) or decision_event_id <= 0:
            raise ValueError("decision event id invalid")
        if (
            isinstance(captured_at, bool)
            or not isinstance(captured_at, int)
            or captured_at < 0
        ):
            raise ValueError("capture timestamp invalid")
        if not isinstance(capture, dict):
            raise ValueError("capture must be an object")
        if (
            capture.get("observational_only") is not True
            or capture.get("decision_mutated") is not False
        ):
            raise ValueError("capture must be observational only")
        outcome_status = str(capture.get("outcome_status") or "UNOBSERVED")
        if outcome_status not in {"UNOBSERVED", "OBSERVED"}:
            raise ValueError("outcome status invalid")
        persisted = {
            **capture,
            "capture_version": "decision_outcome_capture_v1",
            "captured_at": captured_at,
            "outcome_status": outcome_status,
        }
        payload, payload_hash = self._encode(persisted)
        created_at = int(time.time())
        with connect_managed_sqlite(self.db_path, timeout=10.0) as conn:
            decision = conn.execute(
                "SELECT id FROM entry_decision_events WHERE id=?",
                (decision_event_id,),
            ).fetchone()
            if decision is None:
                raise ValueError("decision event missing")
            try:
                cursor = conn.execute(
                    "INSERT INTO decision_outcome_capture ("
                    "decision_event_id,capture_version,captured_at,outcome_status,"
                    "capture_json,capture_hash,created_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        decision_event_id,
                        "decision_outcome_capture_v1",
                        captured_at,
                        outcome_status,
                        payload,
                        payload_hash,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("decision outcome capture already exists") from exc
            return int(cursor.lastrowid)

    def pending_outcome_captures(
        self, *, mature_before: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return immutable initial captures whose horizon has matured."""
        if isinstance(mature_before, bool) or not isinstance(mature_before, int):
            raise ValueError("maturity timestamp invalid")
        with connect_managed_sqlite(self.db_path, timeout=10.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT c.id, c.decision_event_id, c.captured_at, c.capture_json
                FROM decision_outcome_capture c
                LEFT JOIN decision_outcome_resolution r
                  ON r.decision_event_id = c.decision_event_id
                WHERE r.id IS NULL AND c.captured_at <= ?
                ORDER BY c.captured_at, c.id LIMIT ?
                """,
                (mature_before, max(1, min(int(limit), 1000))),
            ).fetchall()
        return [dict(row) for row in rows]

    matured_outcome_captures = pending_outcome_captures

    def resolve_outcome_capture(
        self,
        decision_event_id: int,
        resolution: dict[str, Any],
        *,
        resolved_at: int,
    ) -> int:
        """Append the final observation without mutating the initial capture."""
        if isinstance(decision_event_id, bool) or not isinstance(decision_event_id, int) or decision_event_id <= 0:
            raise ValueError("decision event id invalid")
        if isinstance(resolved_at, bool) or not isinstance(resolved_at, int) or resolved_at < 0:
            raise ValueError("resolution timestamp invalid")
        if not isinstance(resolution, dict):
            raise ValueError("resolution must be an object")
        status = str(resolution.get("outcome_status") or "")
        if status not in {"OBSERVED", "UNOBSERVABLE", "UNAVAILABLE"}:
            raise ValueError("outcome status invalid")
        # Explicitly preserve unavailable cost/provenance rather than inventing values.
        persisted = {
            **resolution,
            "resolution_version": "decision_outcome_resolution_v1",
            "resolved_at": resolved_at,
            "outcome_status": status,
            "cost": resolution.get("cost"),
            "provenance": resolution.get("provenance"),
        }
        payload, payload_hash = self._encode(persisted)
        with connect_managed_sqlite(self.db_path, timeout=10.0) as conn:
            if conn.execute(
                "SELECT 1 FROM decision_outcome_capture WHERE decision_event_id=?",
                (decision_event_id,),
            ).fetchone() is None:
                raise ValueError("initial outcome capture missing")
            try:
                cursor = conn.execute(
                    """INSERT INTO decision_outcome_resolution
                    (decision_event_id,resolution_version,resolved_at,outcome_status,
                     resolution_json,resolution_hash,created_at)
                    VALUES (?,?,?,?,?,?,?)""",
                    (decision_event_id, "decision_outcome_resolution_v1", resolved_at,
                     status, payload, payload_hash, int(time.time())),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("decision outcome resolution already exists") from exc
        return int(cursor.lastrowid)

    def resolve_matured_outcomes(
        self, resolver: Any, *, mature_before: int, limit: int = 100
    ) -> int:
        """Resolve research outcomes; failures are isolated per capture."""
        resolved = 0
        for capture in self.pending_outcome_captures(mature_before=mature_before, limit=limit):
            try:
                result = resolver(capture)
                if result is not None:
                    self.resolve_outcome_capture(
                        int(capture["decision_event_id"]), result,
                        resolved_at=int(time.time()),
                    )
                    resolved += 1
            except Exception:
                continue
        return resolved

    @staticmethod
    def _history_select(where: str = "") -> str:
        return (
            "SELECT e.id,e.symbol,e.event_at,e.decision,e.entry_readiness,"
            "e.evidence_coverage_pct,e.packet_json,e.packet_hash,"
            "(SELECT a.advisory_json FROM entry_decision_advisories a "
            " WHERE a.decision_event_id=e.id ORDER BY a.id DESC LIMIT 1),"
            "(SELECT a.advisory_hash FROM entry_decision_advisories a "
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
               e.evidence_coverage_pct,e.packet_json,e.packet_hash
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
