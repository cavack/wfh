import asyncio
import time


class _FakeSettlementWorker:
    def run_forever(
        self,
        *,
        interval_seconds,
    ):
        return (
            "settlement",
            interval_seconds,
        )


def test_shadow_builder_does_nothing_when_feature_is_disabled(
    monkeypatch,
):
    import waterfallhunter.main as main

    monkeypatch.setattr(
        main.settings,
        "lbank_execution_shadow_enabled",
        False,
    )

    class ForbiddenStore:
        def __init__(
            self,
            *args,
            **kwargs,
        ):
            raise AssertionError(
                "Store must not be constructed "
                "when shadow is disabled"
            )

    monkeypatch.setattr(
        main,
        "LBankExecutionStore",
        ForbiddenStore,
    )

    worker = (
        main
        ._build_lbank_execution_shadow_worker()
    )

    assert worker is None


def test_shadow_builder_uses_configured_bounded_runtime_values(
    monkeypatch,
):
    import waterfallhunter.main as main

    captured = {}

    class FakeStore:
        def __init__(
            self,
            db_path,
        ):
            captured[
                "db_path"
            ] = db_path

    class FakeWorker:
        def __init__(
            self,
            store,
            *,
            batch_size,
            success_recheck_seconds,
            failure_recheck_seconds,
        ):
            captured[
                "store"
            ] = store

            captured[
                "batch_size"
            ] = batch_size

            captured[
                "success_recheck_seconds"
            ] = (
                success_recheck_seconds
            )

            captured[
                "failure_recheck_seconds"
            ] = (
                failure_recheck_seconds
            )

    monkeypatch.setattr(
        main.settings,
        "lbank_execution_shadow_enabled",
        True,
    )

    monkeypatch.setattr(
        main.settings,
        "lbank_execution_shadow_batch_size",
        4,
    )

    monkeypatch.setattr(
        main.settings,
        (
            "lbank_execution_shadow_"
            "success_recheck_seconds"
        ),
        900.0,
    )

    monkeypatch.setattr(
        main.settings,
        (
            "lbank_execution_shadow_"
            "failure_recheck_seconds"
        ),
        300.0,
    )

    monkeypatch.setattr(
        main.db,
        "db_path",
        "/tmp/runtime-test.db",
        raising=False,
    )

    monkeypatch.setattr(
        main,
        "LBankExecutionStore",
        FakeStore,
    )

    monkeypatch.setattr(
        main,
        "LBankExecutionShadowWorker",
        FakeWorker,
    )

    worker = (
        main
        ._build_lbank_execution_shadow_worker()
    )

    assert isinstance(
        worker,
        FakeWorker,
    )

    assert (
        captured["db_path"]
        == "/tmp/runtime-test.db"
    )

    assert (
        captured["batch_size"]
        == 4
    )

    assert (
        captured[
            "success_recheck_seconds"
        ]
        == 900.0
    )

    assert (
        captured[
            "failure_recheck_seconds"
        ]
        == 300.0
    )


def test_startup_with_shadow_disabled_schedules_no_shadow_task(
    monkeypatch,
):
    import waterfallhunter.main as main

    scheduled = []

    monkeypatch.setattr(
        main.settings,
        "live_trading_enabled",
        False,
    )

    monkeypatch.setattr(
        main.settings,
        "lbank_execution_shadow_enabled",
        False,
    )

    monkeypatch.setattr(
        main,
        "_lbank_execution_shadow_worker",
        None,
    )

    fake_settlement = _FakeSettlementWorker()
    monkeypatch.setattr(
        main,
        "_build_signal_settlement_worker",
        lambda: fake_settlement,
    )
    class FakeOutcomeWorker:
        def run_forever(self):
            return ("entry_outcome_resolution", 900.0)

        def stop(self):
            pass

    fake_outcome_worker = FakeOutcomeWorker()
    monkeypatch.setattr(
        main,
        "_build_entry_outcome_resolution_worker",
        lambda: fake_outcome_worker,
    )
    monkeypatch.setattr(
        main.feature_replay_worker,
        "run_forever",
        lambda interval_seconds: (
            "feature_replay",
            interval_seconds,
        ),
    )

    monkeypatch.setattr(
        main.scanner,
        "start_background_scanner",
        lambda interval: (
            "catalog",
            interval,
        ),
    )

    monkeypatch.setattr(
        main,
        "live_reference_loop",
        lambda: "live_reference",
    )

    monkeypatch.setattr(
        main,
        "hunter_loop",
        lambda interval_seconds=60: (
            "hunter",
            interval_seconds,
        ),
    )

    monkeypatch.setattr(
        main,
        "sse_broadcaster",
        lambda: "sse",
    )

    monkeypatch.setattr(
        main.notifier,
        "start_interactive_bot",
        lambda: "telegram_bot",
    )

    monkeypatch.setattr(
        main,
        "_start_background_task",
        lambda task: (
            scheduled.append(task)
            or task
        ),
    )

    asyncio.run(
        main.startup_event()
    )

    assert (
        main
        ._lbank_execution_shadow_worker
        is None
    )

    assert len(scheduled) == 8
    assert main._entry_outcome_resolution_worker is fake_outcome_worker

    assert (
        "feature_replay",
        60.0,
    ) in scheduled

    assert (
        "settlement",
        900.0,
    ) in scheduled
    assert ("entry_outcome_resolution", 900.0) in scheduled

    assert not any(
        (
            isinstance(
                item,
                tuple,
            )
            and item
            and item[0]
            == "shadow"
        )
        for item in scheduled
    )


def test_startup_with_shadow_enabled_schedules_shadow_worker(
    monkeypatch,
):
    import waterfallhunter.main as main

    scheduled = []

    class FakeShadowWorker:
        batch_size = 3

        def run_forever(
            self,
            *,
            interval_seconds,
        ):
            return (
                "shadow",
                interval_seconds,
            )

    fake_worker = (
        FakeShadowWorker()
    )

    monkeypatch.setattr(
        main.settings,
        "live_trading_enabled",
        False,
    )

    monkeypatch.setattr(
        main.settings,
        "lbank_execution_shadow_enabled",
        True,
    )

    monkeypatch.setattr(
        main.settings,
        (
            "lbank_execution_shadow_"
            "interval_seconds"
        ),
        120.0,
    )

    monkeypatch.setattr(
        main,
        "_lbank_execution_shadow_worker",
        None,
    )

    fake_settlement = _FakeSettlementWorker()
    monkeypatch.setattr(
        main,
        "_build_signal_settlement_worker",
        lambda: fake_settlement,
    )
    class FakeOutcomeWorker:
        def run_forever(self):
            return ("entry_outcome_resolution", 900.0)

        def stop(self):
            pass

    fake_outcome_worker = FakeOutcomeWorker()
    monkeypatch.setattr(
        main,
        "_build_entry_outcome_resolution_worker",
        lambda: fake_outcome_worker,
    )
    monkeypatch.setattr(
        main.feature_replay_worker,
        "run_forever",
        lambda interval_seconds: (
            "feature_replay",
            interval_seconds,
        ),
    )

    monkeypatch.setattr(
        main.scanner,
        "start_background_scanner",
        lambda interval: (
            "catalog",
            interval,
        ),
    )

    monkeypatch.setattr(
        main,
        "live_reference_loop",
        lambda: "live_reference",
    )

    monkeypatch.setattr(
        main,
        "hunter_loop",
        lambda interval_seconds=60: (
            "hunter",
            interval_seconds,
        ),
    )

    monkeypatch.setattr(
        main,
        "sse_broadcaster",
        lambda: "sse",
    )

    monkeypatch.setattr(
        main.notifier,
        "start_interactive_bot",
        lambda: "telegram_bot",
    )

    monkeypatch.setattr(
        main,
        (
            "_build_lbank_execution_"
            "shadow_worker"
        ),
        lambda: fake_worker,
    )

    monkeypatch.setattr(
        main,
        "_start_background_task",
        lambda task: (
            scheduled.append(task)
            or task
        ),
    )

    asyncio.run(
        main.startup_event()
    )

    assert (
        main
        ._lbank_execution_shadow_worker
        is fake_worker
    )

    assert (
        (
            "shadow",
            120.0,
        )
        in scheduled
    )

    assert len(scheduled) == 9
    assert main._entry_outcome_resolution_worker is fake_outcome_worker

    assert (
        "feature_replay",
        60.0,
    ) in scheduled

    assert (
        "settlement",
        900.0,
    ) in scheduled
    assert ("entry_outcome_resolution", 900.0) in scheduled


def test_shadow_health_is_observational_and_does_not_gate_main_health(
    monkeypatch,
):
    import waterfallhunter.main as main

    now = time.time()

    class FakeShadowWorker:
        def health_snapshot(
            self,
        ):
            return {
                "running": False,
                "batch_size": 8,
                "last_started_at": (
                    now - 100
                ),
                "last_progress_at": (
                    now - 100
                ),
                "last_completed_at": (
                    now - 100
                ),
                "total_attempted": 8,
                "total_observed": 0,
                "total_unavailable": 8,
            }

    monkeypatch.setattr(
        main.scanner,
        "last_successful_refresh_at",
        now,
    )

    monkeypatch.setattr(
        main,
        "_hunter_last_progress_at",
        now,
    )

    monkeypatch.setattr(
        main,
        "_lbank_execution_shadow_worker",
        FakeShadowWorker(),
    )

    result = asyncio.run(
        main.health_check()
    )

    assert (
        result["status"]
        == "healthy"
    )

    shadow = result[
        "lbank_execution_shadow"
    ]

    assert (
        shadow["enabled"]
        is True
    )

    assert (
        shadow["running"]
        is False
    )

    assert (
        shadow[
            "total_unavailable"
        ]
        == 8
    )


def test_live_reference_loop_propagates_task_cancellation(monkeypatch):
    import waterfallhunter.main as main

    async def cancelled_refresh():
        raise asyncio.CancelledError

    monkeypatch.setattr(
        main.scanner,
        "refresh_live_references",
        cancelled_refresh,
    )

    async def scenario():
        task = asyncio.create_task(main.live_reference_loop(interval_seconds=0))
        try:
            await task
        except asyncio.CancelledError:
            return True
        return False

    assert asyncio.run(scenario()) is True
