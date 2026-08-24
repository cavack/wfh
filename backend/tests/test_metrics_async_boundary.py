from __future__ import annotations

import asyncio
import threading

import waterfallhunter.main as main


def test_metrics_reads_active_candidates_off_event_loop(monkeypatch) -> None:
    caller_thread = threading.get_ident()
    observed_thread: int | None = None

    def get_all_active_candidates() -> dict:
        nonlocal observed_thread
        observed_thread = threading.get_ident()
        return {}

    async def noop_async(*args, **kwargs) -> None:
        del args, kwargs

    monkeypatch.setattr(main.db, "get_all_active_candidates", get_all_active_candidates)
    monkeypatch.setattr(main, "_update_candidate_state_metrics", lambda _: None)
    monkeypatch.setattr(main, "_update_lbank_shadow_metrics", lambda: None)
    monkeypatch.setattr(main, "_update_signal_settlement_worker_metrics", lambda: None)
    monkeypatch.setattr(main, "_update_signal_evidence_metrics", noop_async)
    monkeypatch.setattr(main, "_notification_delivery_health_snapshot", noop_async)
    monkeypatch.setattr(main, "generate_latest", lambda: b"")

    asyncio.run(main.metrics())

    assert observed_thread is not None
    assert observed_thread != caller_thread
