from __future__ import annotations

import asyncio
import threading

import waterfallhunter.main as main


def _stub_metrics_dependencies(monkeypatch) -> None:
    monkeypatch.setattr(main.db, "get_all_active_candidates", lambda: {})
    monkeypatch.setattr(main, "_update_candidate_state_metrics", lambda _: None)
    monkeypatch.setattr(main, "_update_lbank_shadow_metrics", lambda: None)
    monkeypatch.setattr(main, "_update_signal_settlement_worker_metrics", lambda: None)

    async def notification_noop(*args, **kwargs) -> None:
        del args, kwargs

    monkeypatch.setattr(
        main,
        "_notification_delivery_health_snapshot",
        notification_noop,
    )
    monkeypatch.setattr(main, "generate_latest", lambda: b"metrics-ok")


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


def test_metrics_survives_signal_evidence_refresh_failure(monkeypatch) -> None:
    _stub_metrics_dependencies(monkeypatch)

    async def evidence_failure(*args, **kwargs) -> None:
        del args, kwargs
        raise RuntimeError("evidence report unavailable")

    monkeypatch.setattr(main, "_update_signal_evidence_metrics", evidence_failure)

    response = asyncio.run(main.metrics())

    assert response.status_code == 200
    assert bytes(response.body) == b"metrics-ok"


def test_signal_evidence_refresh_failure_is_throttled(monkeypatch) -> None:
    calls = 0

    def failing_report() -> dict:
        nonlocal calls
        calls += 1
        raise RuntimeError("evidence report unavailable")

    monkeypatch.setattr(main.execution_outcome_report, "build_report", failing_report)
    monkeypatch.setattr(main, "_signal_evidence_metrics_last_refresh", 0.0)

    for _ in range(2):
        try:
            asyncio.run(main._update_signal_evidence_metrics())
        except RuntimeError:
            pass

    assert calls == 1
