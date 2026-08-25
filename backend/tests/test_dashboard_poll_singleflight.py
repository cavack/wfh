from __future__ import annotations

import asyncio

from fastapi import Response

from waterfallhunter import main
from waterfallhunter.core.dashboard_stream import DashboardEventBuffer


def test_bootstrap_candidate_poll_builds_preview_once_for_concurrent_clients(
    monkeypatch,
) -> None:
    """Concurrent bootstrap polls must share one expensive preview build."""

    buffer = DashboardEventBuffer(replay_limit=100)
    monkeypatch.setattr(
        main,
        "_dashboard_event_buffer",
        buffer,
    )

    build_calls = 0

    def build_candidates(*, evaluation_time=None):
        nonlocal build_calls
        build_calls += 1
        return {
            "total": 0,
            "candidates": {},
            "final_ranking": {},
            "signal_funnel": {},
        }

    monkeypatch.setattr(
        main,
        "get_formatted_candidates",
        build_candidates,
    )

    async def scenario() -> None:
        snapshots = await asyncio.gather(
            *(
                main.get_candidates(Response())
                for _ in range(8)
            )
        )

        assert len(snapshots) == 8
        assert all(snapshot.snapshot_version == 1 for snapshot in snapshots)
        assert all(snapshot.state == "READY" for snapshot in snapshots)
        assert len({snapshot.generated_at for snapshot in snapshots}) == 1

    asyncio.run(scenario())

    assert build_calls == 1
    # Poll bootstrap stays a read-only preview. It must not advance the SSE
    # event/snapshot sequence or become a retained replay snapshot.
    assert buffer.snapshot_version == 0
    assert buffer.latest_snapshot() is None
