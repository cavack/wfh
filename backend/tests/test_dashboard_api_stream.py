from __future__ import annotations

import asyncio
import json

from fastapi import Response

import waterfallhunter.main as main
from waterfallhunter.core.dashboard_stream import DashboardEventBuffer


PAYLOAD = {
    "total": 1,
    "candidates": {"TEST": {"status": "WATCH"}},
    "decision_terminal": {"contract_version": "decision_terminal_v1", "counts": {}},
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
