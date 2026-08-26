from __future__ import annotations

import asyncio
import threading

import waterfallhunter.main as main


def test_periodic_flush_does_not_hold_evaluation_semaphore(
    monkeypatch,
) -> None:
    original_sleep = asyncio.sleep
    candidates = {
        f"T{index:02d}": {}
        for index in range(36)
    }

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
        lambda: candidates,
    )
    def stop_after_cycle() -> None:
        main._hunter_running = False
        main._hunter_stop_event.set()

    monkeypatch.setattr(
        main.execution_decision_logger,
        "record_universe_snapshot",
        stop_after_cycle,
    )
    monkeypatch.setattr(main, "_HUNTER_STARTUP_DELAY_SECONDS", 0.0)
    main._hunter_stop_event.clear()
    monkeypatch.setattr(
        main.validator.ws_manager,
        "prune_stale_cache",
        lambda: None,
    )

    flush_started = threading.Event()
    six_waiters_started = threading.Event()
    release_flush = threading.Event()
    flush_observed_full_capacity: list[bool] = []
    flush_calls = 0
    waiters: set[str] = set()

    def flush_evaluations() -> None:
        nonlocal flush_calls
        flush_calls += 1
        if flush_calls != 1:
            return

        flush_started.set()
        flush_observed_full_capacity.append(
            six_waiters_started.wait(timeout=1.0)
        )
        release_flush.set()

    monkeypatch.setattr(
        main.execution_decision_logger,
        "flush_evaluations",
        flush_evaluations,
    )

    async def evaluate_candidate(symbol: str, data: dict) -> None:
        del data
        if int(symbol[1:]) < 30:
            return

        while not flush_started.is_set():
            await original_sleep(0)

        if not release_flush.is_set():
            waiters.add(symbol)
            if len(waiters) == 6:
                six_waiters_started.set()

            while not release_flush.is_set():
                await original_sleep(0)

    monkeypatch.setattr(
        main,
        "evaluate_candidate",
        evaluate_candidate,
    )

    sleep_calls = 0

    async def controlled_sleep(_: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            main._hunter_running = False

    monkeypatch.setattr(
        main.asyncio,
        "sleep",
        controlled_sleep,
    )

    asyncio.run(
        main.hunter_loop(interval_seconds=0)
    )

    assert flush_observed_full_capacity == [True]
    assert waiters == {
        "T30",
        "T31",
        "T32",
        "T33",
        "T34",
        "T35",
    }
