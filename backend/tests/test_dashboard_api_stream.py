from __future__ import annotations

import asyncio
import json

from fastapi import Response

import waterfallhunter.main as main
from waterfallhunter.core.dashboard_stream import DashboardEventBuffer


PAYLOAD = {
    "total": 1,
    "candidates": {"TEST": {"status": "WATCH"}},
    "final_ranking": {"version": "test"},
    "signal_funnel": {"version": "test"},
}


def test_polling_endpoint_returns_a_valid_versioned_no_store_snapshot(monkeypatch) -> None:
    buffer = DashboardEventBuffer()
    monkeypatch.setattr(main, "_dashboard_event_buffer", buffer)
    monkeypatch.setattr(main, "get_formatted_candidates", lambda **_: PAYLOAD)
    response = Response()

    snapshot = asyncio.run(main.get_candidates(response))

    assert snapshot is not None
    assert snapshot.contract_version == "dashboard_snapshot_v1"
    assert snapshot.schema_version == "1.0"
    assert snapshot.state == "READY"
    assert snapshot.total == 1
    assert response.headers["Cache-Control"] == "no-store"
    assert buffer.snapshot_version == 0
    assert buffer.replay_after("1") is None


def test_stream_replays_after_last_event_id_and_sets_proxy_safe_headers(monkeypatch) -> None:
    buffer = DashboardEventBuffer()
    monkeypatch.setattr(main, "_dashboard_event_buffer", buffer)
    monkeypatch.setattr(main, "get_formatted_candidates", lambda **_: PAYLOAD)
    first = buffer.publish_snapshot(PAYLOAD, generated_at=10.0, full_snapshot=True)
    second = buffer.publish_snapshot(PAYLOAD, generated_at=11.0, full_snapshot=False)

    async def first_chunk() -> tuple[object, str]:
        response = await main.stream_candidates(last_event_id=first.event_id)
        iterator = response.body_iterator
        try:
            chunk = await anext(iterator)
        finally:
            await iterator.aclose()
        return response, chunk

    response, chunk = asyncio.run(first_chunk())
    assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"
    assert response.headers["x-accel-buffering"] == "no"
    assert chunk.startswith(f"id: {second.event_id}\nevent: snapshot\n")
    event = json.loads(chunk.split("data: ", 1)[1])
    assert event["replayed"] is True
    assert event["full_snapshot"] is False


def test_stream_falls_back_to_full_snapshot_when_replay_is_unavailable(monkeypatch) -> None:
    buffer = DashboardEventBuffer(replay_limit=1)
    monkeypatch.setattr(main, "_dashboard_event_buffer", buffer)
    monkeypatch.setattr(main, "get_formatted_candidates", lambda **_: PAYLOAD)
    old = buffer.publish_snapshot(PAYLOAD, generated_at=10.0, full_snapshot=True)
    buffer.publish_heartbeat(generated_at=11.0)

    async def first_chunk() -> str:
        response = await main.stream_candidates(last_event_id=old.event_id)
        iterator = response.body_iterator
        try:
            return await anext(iterator)
        finally:
            await iterator.aclose()

    chunk = asyncio.run(first_chunk())
    event = json.loads(chunk.split("data: ", 1)[1])
    assert event["event_type"] == "snapshot"
    assert event["full_snapshot"] is True
    assert event["payload"]["state"] == "READY"


def test_broadcast_tolerates_client_set_mutation_during_delivery(monkeypatch) -> None:
    buffer = DashboardEventBuffer()
    event = buffer.publish_heartbeat(generated_at=10.0)
    clients: set[object] = set()

    class SelfRemovingQueue:
        def put_nowait(self, delivered_event) -> None:
            assert delivered_event is event
            clients.discard(self)

    queue = SelfRemovingQueue()
    clients.add(queue)
    monkeypatch.setattr(main, "_sse_clients", clients)

    main._broadcast_dashboard_event(event)

    assert clients == set()


def test_dashboard_snapshot_normalizes_non_finite_numbers_to_unavailable(monkeypatch) -> None:
    buffer = DashboardEventBuffer()
    unsafe_payload = {
        "total": 1,
        "candidates": {
            "TEST": {
                "status": "WATCH",
                "metrics": {"spread_pct": float("nan")},
            }
        },
        "final_ranking": {"version": "test"},
        "signal_funnel": {"version": "test"},
    }
    monkeypatch.setattr(main, "_dashboard_event_buffer", buffer)
    monkeypatch.setattr(main, "get_formatted_candidates", lambda **_: unsafe_payload)

    event = main._publish_dashboard_snapshot(
        full_snapshot=False,
        only_if_changed=True,
    )

    assert event is not None
    assert event.payload is not None
    assert event.payload.candidates["TEST"]["metrics"]["spread_pct"] is None


def test_polling_snapshot_normalizes_non_finite_numbers_to_unavailable(monkeypatch) -> None:
    buffer = DashboardEventBuffer()
    unsafe_payload = {
        "total": 1,
        "candidates": {
            "TEST": {
                "status": "WATCH",
                "metrics": {"spread_pct": float("inf")},
            }
        },
        "final_ranking": {"version": "test"},
        "signal_funnel": {"version": "test"},
    }
    monkeypatch.setattr(main, "_dashboard_event_buffer", buffer)
    monkeypatch.setattr(main, "get_formatted_candidates", lambda **_: unsafe_payload)
    response = Response()

    snapshot = asyncio.run(main.get_candidates(response))

    assert snapshot.candidates["TEST"]["metrics"]["spread_pct"] is None


def test_production_dashboard_replay_window_is_memory_bounded() -> None:
    assert getattr(main, "_DASHBOARD_REPLAY_EVENT_LIMIT", None) == 8
    assert main._dashboard_event_buffer._events.maxlen == 8


def test_periodic_dashboard_broadcast_ignores_derived_age_only_changes(monkeypatch) -> None:
    """Derived display ages must not make an unchanged business snapshot look new."""
    buffer = DashboardEventBuffer()
    monkeypatch.setattr(main, "_dashboard_event_buffer", buffer)
    payloads = [
        {
            "total": 1,
            "candidates": {
                "TEST": {
                    "status": "WATCH",
                    "age_seconds": 1.0,
                    "analysis_age_seconds": 1.0,
                    "reference_age_seconds": 2.0,
                }
            },
            "final_ranking": {"version": "test"},
            "signal_funnel": {"version": "test"},
        },
        {
            "total": 1,
            "candidates": {
                "TEST": {
                    "status": "WATCH",
                    "age_seconds": 2.0,
                    "analysis_age_seconds": 2.0,
                    "reference_age_seconds": 3.0,
                }
            },
            "final_ranking": {"version": "test"},
            "signal_funnel": {"version": "test"},
        },
    ]
    monkeypatch.setattr(main, "get_formatted_candidates", lambda **_: payloads.pop(0))

    first = main._publish_dashboard_snapshot(full_snapshot=False, only_if_changed=True)
    second = main._publish_dashboard_snapshot(full_snapshot=False, only_if_changed=True)

    assert first is not None
    assert second is None
    assert buffer.snapshot_version == 1


def test_sse_client_queue_is_bounded_and_latest_event_wins(monkeypatch) -> None:
    """A slow SSE client must retain only a tiny rolling set of full snapshots."""
    queue = main._new_dashboard_client_queue()
    assert queue.maxsize == 2

    buffer = DashboardEventBuffer()
    first = buffer.publish_heartbeat(generated_at=10.0)
    second = buffer.publish_heartbeat(generated_at=11.0)
    latest = buffer.publish_heartbeat(generated_at=12.0)
    queue.put_nowait(first)
    queue.put_nowait(second)
    monkeypatch.setattr(main, "_sse_clients", {queue})

    main._broadcast_dashboard_event(latest)

    assert queue.get_nowait() is second
    assert queue.get_nowait() is latest
    assert queue.empty()
