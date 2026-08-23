"""Versioned dashboard snapshots and bounded SSE replay."""

from __future__ import annotations

import threading
from collections import deque
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from waterfallhunter.core.signal_metadata import canonical_sha256


DASHBOARD_SCHEMA_VERSION = "1.0"
DASHBOARD_SNAPSHOT_CONTRACT = "dashboard_snapshot_v1"
DASHBOARD_EVENT_CONTRACT = "dashboard_stream_event_v1"


class DashboardSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["dashboard_snapshot_v1"]
    schema_version: Literal["1.0"]
    snapshot_version: int = Field(ge=1)
    generated_at: float = Field(ge=0, allow_inf_nan=False)
    state: Literal["READY"]
    total: int = Field(ge=0)
    candidates: dict[str, dict[str, Any]]
    final_ranking: dict[str, Any]
    signal_funnel: dict[str, Any]

    @model_validator(mode="after")
    def _validate_total(self) -> "DashboardSnapshot":
        if self.total != len(self.candidates):
            raise ValueError("dashboard total must equal candidate count")
        return self


class DashboardStreamEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["dashboard_stream_event_v1"]
    event_id: str = Field(pattern=r"^[1-9][0-9]*$")
    event_type: Literal["snapshot", "heartbeat"]
    snapshot_version: int = Field(ge=0)
    schema_version: Literal["1.0"]
    generated_at: float = Field(ge=0, allow_inf_nan=False)
    last_event_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]*$")
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: DashboardSnapshot | None
    replayed: bool
    full_snapshot: bool

    @model_validator(mode="after")
    def _validate_event_shape(self) -> "DashboardStreamEvent":
        if self.event_type == "snapshot" and self.payload is None:
            raise ValueError("snapshot events require a payload")
        if self.event_type == "heartbeat" and self.payload is not None:
            raise ValueError("heartbeat events cannot contain a snapshot")
        if self.payload is not None and self.payload.snapshot_version != self.snapshot_version:
            raise ValueError("event and payload snapshot versions must match")
        return self


def serialize_sse_event(event: DashboardStreamEvent) -> str:
    data = event.model_dump_json(exclude_none=False)
    return f"id: {event.event_id}\nevent: {event.event_type}\ndata: {data}\n\n"


class DashboardEventBuffer:
    """Thread-safe monotonic event sequencer with bounded in-memory replay."""

    def __init__(self, *, replay_limit: int = 100):
        if replay_limit < 1:
            raise ValueError("replay_limit must be positive")
        self._events: deque[DashboardStreamEvent] = deque(maxlen=replay_limit)
        self._event_sequence = 0
        self._snapshot_sequence = 0
        self._last_snapshot_content_hash: str | None = None
        self._lock = threading.Lock()

    def publish_snapshot(
        self,
        payload: dict[str, Any],
        *,
        generated_at: float,
        full_snapshot: bool,
    ) -> DashboardStreamEvent:
        with self._lock:
            return self._publish_snapshot_locked(
                payload,
                generated_at=generated_at,
                full_snapshot=full_snapshot,
            )

    def publish_snapshot_if_changed(
        self,
        payload: dict[str, Any],
        *,
        generated_at: float,
    ) -> DashboardStreamEvent | None:
        """Retain a periodic snapshot only when its business payload changed."""
        content_hash = canonical_sha256(payload)
        with self._lock:
            if content_hash == self._last_snapshot_content_hash:
                return None
            return self._publish_snapshot_locked(
                payload,
                generated_at=generated_at,
                full_snapshot=False,
                content_hash=content_hash,
            )

    def _publish_snapshot_locked(
        self,
        payload: dict[str, Any],
        *,
        generated_at: float,
        full_snapshot: bool,
        content_hash: str | None = None,
    ) -> DashboardStreamEvent:
        next_snapshot_version = self._snapshot_sequence + 1
        snapshot = DashboardSnapshot.model_validate(
            {
                "contract_version": DASHBOARD_SNAPSHOT_CONTRACT,
                "schema_version": DASHBOARD_SCHEMA_VERSION,
                "snapshot_version": next_snapshot_version,
                "generated_at": generated_at,
                "state": "READY",
                **payload,
            }
        )
        self._snapshot_sequence = next_snapshot_version
        self._last_snapshot_content_hash = content_hash or canonical_sha256(payload)
        return self._append(
            event_type="snapshot",
            snapshot_version=snapshot.snapshot_version,
            generated_at=generated_at,
            payload=snapshot,
            payload_hash=canonical_sha256(snapshot.model_dump(mode="json")),
            full_snapshot=full_snapshot,
        )

    def publish_heartbeat(self, *, generated_at: float) -> DashboardStreamEvent:
        with self._lock:
            heartbeat_material = {
                "contract_version": DASHBOARD_EVENT_CONTRACT,
                "event_type": "heartbeat",
                "snapshot_version": self._snapshot_sequence,
                "schema_version": DASHBOARD_SCHEMA_VERSION,
                "generated_at": generated_at,
            }
            return self._append(
                event_type="heartbeat",
                snapshot_version=self._snapshot_sequence,
                generated_at=generated_at,
                payload=None,
                payload_hash=canonical_sha256(heartbeat_material),
                full_snapshot=False,
            )

    def _append(
        self,
        *,
        event_type: Literal["snapshot", "heartbeat"],
        snapshot_version: int,
        generated_at: float,
        payload: DashboardSnapshot | None,
        payload_hash: str,
        full_snapshot: bool,
    ) -> DashboardStreamEvent:
        previous = str(self._event_sequence) if self._event_sequence else None
        self._event_sequence += 1
        event = DashboardStreamEvent(
            contract_version=DASHBOARD_EVENT_CONTRACT,
            event_id=str(self._event_sequence),
            event_type=event_type,
            snapshot_version=snapshot_version,
            schema_version=DASHBOARD_SCHEMA_VERSION,
            generated_at=generated_at,
            last_event_id=previous,
            payload_hash=payload_hash,
            payload=payload,
            replayed=False,
            full_snapshot=full_snapshot,
        )
        self._events.append(event)
        return event

    def replay_after(self, last_event_id: str | None) -> list[DashboardStreamEvent] | None:
        """Return replay events, or None when a full snapshot is required."""

        if last_event_id is None or not last_event_id.isdigit() or int(last_event_id) < 1:
            return None
        requested = int(last_event_id)
        with self._lock:
            if requested == self._event_sequence:
                return []
            event_ids = [int(event.event_id) for event in self._events]
            if requested not in event_ids:
                return None
            return [
                event.model_copy(update={"replayed": True, "full_snapshot": False})
                for event in self._events
                if int(event.event_id) > requested
            ]

    def latest_snapshot(self) -> DashboardSnapshot | None:
        """Return the latest retained snapshot without advancing either sequence."""
        with self._lock:
            for event in reversed(self._events):
                if event.payload is not None:
                    return event.payload
        return None

    def preview_snapshot(
        self,
        payload: dict[str, Any],
        *,
        generated_at: float,
    ) -> DashboardSnapshot:
        """Build a read-only snapshot for initial polling without retaining it."""
        with self._lock:
            snapshot_version = max(1, self._snapshot_sequence)
        return DashboardSnapshot.model_validate(
            {
                "contract_version": DASHBOARD_SNAPSHOT_CONTRACT,
                "schema_version": DASHBOARD_SCHEMA_VERSION,
                "snapshot_version": snapshot_version,
                "generated_at": generated_at,
                "state": "READY",
                **payload,
            }
        )

    @property
    def snapshot_version(self) -> int:
        with self._lock:
            return self._snapshot_sequence
