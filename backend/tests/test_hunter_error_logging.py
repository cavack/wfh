from __future__ import annotations

import asyncio
import logging

import waterfallhunter.main as main


def test_failed_candidate_evaluation_logs_traceback(
    monkeypatch,
    caplog,
) -> None:
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
        lambda: {"TRACE": {}},
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

    async def failing_evaluation(symbol: str, data: dict) -> None:
        del symbol, data
        raise RuntimeError("traceback sentinel")

    monkeypatch.setattr(
        main,
        "evaluate_candidate",
        failing_evaluation,
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

    caplog.set_level(
        logging.WARNING,
        logger="WaterfallHunter",
    )

    asyncio.run(
        main.hunter_loop(interval_seconds=0)
    )

    records = [
        record
        for record in caplog.records
        if record.name == "WaterfallHunter"
        and "Candidate evaluation failed" in record.getMessage()
    ]

    assert records
    record = records[-1]
    assert record.exc_info is not None

    exc_type, exc_value, exc_traceback = record.exc_info
    assert exc_type is RuntimeError
    assert str(exc_value) == "traceback sentinel"
    assert exc_traceback is not None
