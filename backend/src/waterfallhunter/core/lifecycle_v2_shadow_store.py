"""Append-only persistence and reporting for Lifecycle V2 shadow events."""

from __future__ import annotations

import json
import sqlite3
import statistics
from pathlib import Path
from typing import Any

from waterfallhunter.core.canonical_json import canonical_json_bytes
from waterfallhunter.core.lifecycle_v2_shadow import (
    LifecycleV2State,
    LifecycleV2Transition,
)
from waterfallhunter.core.managed_sqlite import connect_managed_sqlite
from waterfallhunter.core.schema_contract import require_managed_schema


class LifecycleV2ShadowStoreError(RuntimeError):
    """Raised when a shadow event cannot be persisted without ambiguity."""


class LifecycleV2ShadowStore:
    def __init__(self, db_path: str | Path, *, verify_schema: bool = True):
        self.db_path = str(db_path)
        if verify_schema:
            require_managed_schema(
                self.db_path,
                required_tables=frozenset({"lifecycle_v2_shadow_events"}),
            )

    def append_comparison(
        self,
        *,
        symbol: str,
        v1_state: str,
        transition: LifecycleV2Transition,
        comparison: dict[str, Any],
        created_at: int,
    ) -> bool:
        if comparison.get("v2_transition_hash") != transition.transition_hash:
            raise LifecycleV2ShadowStoreError("SHADOW_COMPARISON_TRANSITION_MISMATCH")
        comparison_hash = str(comparison.get("comparison_hash") or "")
        if len(comparison_hash) != 64:
            raise LifecycleV2ShadowStoreError("SHADOW_COMPARISON_HASH_INVALID")
        reason_codes_json = canonical_json_bytes(
            list(transition.reason_codes)
        ).decode("utf-8")
        evidence_refs_json = canonical_json_bytes(
            list(transition.evidence_refs)
        ).decode("utf-8")
        event_id = f"lifecycle-v2:{transition.transition_hash}"
        material = (
            event_id,
            transition.episode_id,
            str(symbol),
            str(v1_state),
            transition.from_state.value,
            transition.to_state.value,
            reason_codes_json,
            evidence_refs_json,
            transition.observed_at,
            transition.policy_version,
            transition.policy_hash,
            transition.feature_registry_hash,
            transition.strategy_profile,
            transition.transition_hash,
            comparison_hash,
            1,
            0,
            int(created_at),
        )
        try:
            with connect_managed_sqlite(self.db_path, timeout=10.0) as conn:
                result = conn.execute(
                    """
                    INSERT INTO lifecycle_v2_shadow_events (
                        event_id, episode_id, symbol, v1_state,
                        v2_from_state, v2_to_state, reason_codes_json,
                        evidence_refs_json, observed_at, policy_version,
                        policy_hash, feature_registry_hash, strategy_profile,
                        transition_hash, comparison_hash, shadow_only,
                        promotion_allowed, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(transition_hash) DO NOTHING
                    """,
                    material,
                )
                if result.rowcount == 1:
                    return True
                existing = conn.execute(
                    """
                    SELECT
                        event_id, episode_id, symbol, v1_state,
                        v2_from_state, v2_to_state, reason_codes_json,
                        evidence_refs_json, observed_at, policy_version,
                        policy_hash, feature_registry_hash, strategy_profile,
                        transition_hash, comparison_hash, shadow_only,
                        promotion_allowed, created_at
                    FROM lifecycle_v2_shadow_events
                    WHERE transition_hash = ?
                    """,
                    (transition.transition_hash,),
                ).fetchone()
                if existing is None or tuple(existing) != material:
                    raise LifecycleV2ShadowStoreError(
                        "SHADOW_TRANSITION_IDEMPOTENCY_CONFLICT"
                    )
                return False
        except sqlite3.Error as exc:
            raise LifecycleV2ShadowStoreError("SHADOW_EVENT_PERSISTENCE_FAILED") from exc

    def latest_state(self, *, symbol: str, episode_id: str) -> LifecycleV2State:
        path = Path(self.db_path)
        try:
            with sqlite3.connect(
                f"{path.resolve().as_uri()}?mode=ro",
                uri=True,
                timeout=5.0,
            ) as conn:
                row = conn.execute(
                    """
                    SELECT v2_to_state
                    FROM lifecycle_v2_shadow_events
                    WHERE symbol = ? AND episode_id = ?
                    ORDER BY observed_at DESC, created_at DESC, event_id DESC
                    LIMIT 1
                    """,
                    (str(symbol), str(episode_id)),
                ).fetchone()
        except sqlite3.Error as exc:
            raise LifecycleV2ShadowStoreError("SHADOW_STATE_QUERY_FAILED") from exc
        return LifecycleV2State.WATCH if row is None else LifecycleV2State(str(row[0]))

    def report(self, *, limit: int = 500) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit), 5_000))
        path = Path(self.db_path)
        try:
            with sqlite3.connect(
                f"{path.resolve().as_uri()}?mode=ro",
                uri=True,
                timeout=5.0,
            ) as conn:
                conn.row_factory = sqlite3.Row
                totals = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS event_count,
                        COALESCE(SUM(CASE WHEN v1_state != v2_to_state THEN 1 ELSE 0 END), 0)
                            AS divergence_count
                    FROM lifecycle_v2_shadow_events
                    """
                ).fetchone()
                rows = conn.execute(
                    """
                    SELECT
                        event_id, episode_id, symbol, v1_state,
                        v2_from_state, v2_to_state, reason_codes_json,
                        observed_at, policy_version, policy_hash,
                        feature_registry_hash, strategy_profile, transition_hash,
                        comparison_hash
                    FROM lifecycle_v2_shadow_events
                    ORDER BY observed_at DESC, event_id DESC
                    LIMIT ?
                    """,
                    (bounded_limit,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise LifecycleV2ShadowStoreError("SHADOW_REPORT_QUERY_FAILED") from exc
        events = []
        reason_code_counts: dict[str, int] = {}
        profile_counts: dict[str, int] = {}
        state_counts: dict[str, int] = {}
        episode_windows: dict[str, list[tuple[int, str]]] = {}
        for raw in rows:
            packet = dict(raw)
            packet["reason_codes"] = json.loads(packet.pop("reason_codes_json"))
            packet["diverged"] = packet["v1_state"] != packet["v2_to_state"]
            for reason in packet["reason_codes"]:
                reason_code_counts[str(reason)] = reason_code_counts.get(str(reason), 0) + 1
            profile = str(packet["strategy_profile"])
            profile_counts[profile] = profile_counts.get(profile, 0) + 1
            state = str(packet["v2_to_state"])
            state_counts[state] = state_counts.get(state, 0) + 1
            episode_windows.setdefault(str(packet["episode_id"]), []).append(
                (int(packet["observed_at"]), state)
            )
            events.append(packet)
        lead_times = []
        for episode in episode_windows.values():
            first_observed = min(item[0] for item in episode)
            triggered = [item[0] for item in episode if item[1] == "TRIGGERED"]
            if triggered:
                lead_times.append(min(triggered) - first_observed)
        anti_chase_reasons = {
            reason: count
            for reason, count in reason_code_counts.items()
            if reason in {"LATE_EXTENSION", "ANTI_CHASE_HARD_BLOCK", "TRIGGER_DISTANCE_TOO_LARGE"}
        }
        return {
            "contract_version": "lifecycle_v2_shadow_report_v1",
            "shadow_only": True,
            "promotion_allowed": False,
            "event_count": int(totals["event_count"] if totals else 0),
            "divergence_count": int(totals["divergence_count"] if totals else 0),
            "returned_event_count": len(events),
            "event_order": "LATEST_FIRST",
            "analysis": {
                "reason_code_counts": dict(sorted(reason_code_counts.items())),
                "profile_counts": dict(sorted(profile_counts.items())),
                "state_counts": dict(sorted(state_counts.items())),
                "anti_chase_reason_counts": dict(sorted(anti_chase_reasons.items())),
                "episode_count_in_returned_window": len(episode_windows),
                "triggered_episode_count_in_returned_window": len(lead_times),
                "lead_time_seconds": {
                    "available": bool(lead_times),
                    "minimum": min(lead_times) if lead_times else None,
                    "median": statistics.median(lead_times) if lead_times else None,
                    "maximum": max(lead_times) if lead_times else None,
                },
                "outcome_association": {
                    "available": False,
                    "reason": "CANONICAL_V2_EPISODE_OUTCOME_LINK_NOT_ESTABLISHED",
                },
                "promotion_decision": "DO_NOT_PROMOTE",
            },
            "events": events,
        }
