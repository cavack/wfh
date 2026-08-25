from __future__ import annotations

import asyncio

import waterfallhunter.main as main


def test_shutdown_allows_inflight_hunter_evaluation_to_finish(monkeypatch) -> None:
    original_sleep = asyncio.sleep

    monkeypatch.setattr(main, "_background_tasks", set())
    monkeypatch.setattr(main, "_lbank_execution_shadow_worker", None)
    monkeypatch.setattr(main, "_signal_settlement_worker", None)
    monkeypatch.setattr(main, "_hunter_task", None, raising=False)

    monkeypatch.setattr(main.feature_replay_worker, "stop", lambda: None)
    monkeypatch.setattr(main.scanner, "stop", lambda: None)

    async def noop_close() -> None:
        return None

    monkeypatch.setattr(main.scanner, "close", noop_close)
    monkeypatch.setattr(main.validator, "close_all", noop_close)

    async def refresh_live_references() -> None:
        return None

    monkeypatch.setattr(
        main.scanner,
        "refresh_live_references",
        refresh_live_references,
    )
    monkeypatch.setattr(
        main.db,
        "get_all_active_candidates",
        lambda: {"DRAIN": {}},
    )
    monkeypatch.setattr(
        main.execution_decision_logger,
        "flush_evaluations",
        lambda: None,
    )
    monkeypatch.setattr(
        main.execution_decision_logger,
        "record_universe_snapshot",
        lambda: None,
    )
    monkeypatch.setattr(
        main.validator.ws_manager,
        "prune_stale_cache",
        lambda: None,
    )

    started: asyncio.Event
    release: asyncio.Event
    completed: asyncio.Event
    cancelled = False

    async def scenario() -> None:
        nonlocal started, release, completed, cancelled
        started = asyncio.Event()
        release = asyncio.Event()
        completed = asyncio.Event()

        async def evaluate_candidate(symbol: str, data: dict) -> None:
            nonlocal cancelled
            del symbol, data
            started.set()
            try:
                await release.wait()
                completed.set()
            except asyncio.CancelledError:
                cancelled = True
                raise

        monkeypatch.setattr(main, "evaluate_candidate", evaluate_candidate)

        async def controlled_sleep(seconds: float) -> None:
            if seconds == 5:
                return
            await original_sleep(0)

        monkeypatch.setattr(main.asyncio, "sleep", controlled_sleep)

        hunter_task = main._start_background_task(
            main.hunter_loop(interval_seconds=60)
        )
        main._hunter_task = hunter_task
        await started.wait()

        shutdown_task = asyncio.create_task(main.shutdown_event())
        await original_sleep(0)
        release.set()

        await shutdown_task
        await asyncio.gather(hunter_task, return_exceptions=True)

        assert completed.is_set()
        assert cancelled is False

    asyncio.run(scenario())
