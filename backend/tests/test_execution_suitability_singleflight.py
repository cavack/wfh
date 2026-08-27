import asyncio
import threading

import httpx
import pytest
from fastapi import FastAPI

from schema_test_support import migrate_test_database
from waterfallhunter.core.lbank_execution_suitability_report import (
    LBankExecutionSuitabilityReport,
)
from waterfallhunter.routes_execution_suitability import (
    build_execution_suitability_router,
)


def _build_test_app(db_path) -> FastAPI:
    app = FastAPI()
    app.include_router(build_execution_suitability_router(str(db_path)))
    return app


def test_concurrent_execution_suitability_requests_share_one_build(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "registry.db"
    migrate_test_database(db_path)
    app = _build_test_app(db_path)

    original_build_report = LBankExecutionSuitabilityReport.build_report
    started = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def slow_build_report(
        self,
        *,
        symbol_limit=10_000,
        examples_per_status=20,
    ):
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        assert release.wait(timeout=5.0)
        return original_build_report(
            self,
            symbol_limit=symbol_limit,
            examples_per_status=examples_per_status,
        )

    monkeypatch.setattr(
        LBankExecutionSuitabilityReport,
        "build_report",
        slow_build_report,
    )

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            first = asyncio.create_task(
                client.get(
                    "/api/execution-suitability?examples_per_status=0"
                )
            )
            assert await asyncio.to_thread(started.wait, 2.0)
            second = asyncio.create_task(
                client.get(
                    "/api/execution-suitability?examples_per_status=0"
                )
            )
            await asyncio.sleep(0.1)
            release.set()
            return await asyncio.gather(first, second)

    first_response, second_response = asyncio.run(exercise())

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert calls == 1


def test_cancelled_waiter_does_not_cancel_shared_report_build(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "registry.db"
    migrate_test_database(db_path)
    app = _build_test_app(db_path)

    original_build_report = LBankExecutionSuitabilityReport.build_report
    started = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def slow_build_report(
        self,
        *,
        symbol_limit=10_000,
        examples_per_status=20,
    ):
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        assert release.wait(timeout=5.0)
        return original_build_report(
            self,
            symbol_limit=symbol_limit,
            examples_per_status=examples_per_status,
        )

    monkeypatch.setattr(
        LBankExecutionSuitabilityReport,
        "build_report",
        slow_build_report,
    )

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            first = asyncio.create_task(
                client.get(
                    "/api/execution-suitability?examples_per_status=0"
                )
            )
            assert await asyncio.to_thread(started.wait, 2.0)
            second = asyncio.create_task(
                client.get(
                    "/api/execution-suitability?examples_per_status=0"
                )
            )
            await asyncio.sleep(0.1)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            release.set()
            return await second

    second_response = asyncio.run(exercise())

    assert second_response.status_code == 200
    assert calls == 1


def test_failed_report_build_is_not_reused_by_next_request(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "registry.db"
    migrate_test_database(db_path)
    app = _build_test_app(db_path)

    original_build_report = LBankExecutionSuitabilityReport.build_report
    calls = 0

    def flaky_build_report(
        self,
        *,
        symbol_limit=10_000,
        examples_per_status=20,
    ):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic report failure")
        return original_build_report(
            self,
            symbol_limit=symbol_limit,
            examples_per_status=examples_per_status,
        )

    monkeypatch.setattr(
        LBankExecutionSuitabilityReport,
        "build_report",
        flaky_build_report,
    )

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            with pytest.raises(RuntimeError, match="synthetic report failure"):
                await client.get(
                    "/api/execution-suitability?examples_per_status=0"
                )
            await asyncio.sleep(0)
            return await client.get(
                "/api/execution-suitability?examples_per_status=0"
            )

    second_response = asyncio.run(exercise())

    assert second_response.status_code == 200
    assert calls == 2


def test_different_execution_suitability_request_keys_do_not_share_builds(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "registry.db"
    migrate_test_database(db_path)
    app = _build_test_app(db_path)

    original_build_report = LBankExecutionSuitabilityReport.build_report
    started = threading.Event()
    release = threading.Event()
    calls = []
    calls_lock = threading.Lock()

    def slow_build_report(
        self,
        *,
        symbol_limit=10_000,
        examples_per_status=20,
    ):
        with calls_lock:
            calls.append(examples_per_status)
            if len(calls) == 2:
                started.set()
        assert release.wait(timeout=5.0)
        return original_build_report(
            self,
            symbol_limit=symbol_limit,
            examples_per_status=examples_per_status,
        )

    monkeypatch.setattr(
        LBankExecutionSuitabilityReport,
        "build_report",
        slow_build_report,
    )

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            first = asyncio.create_task(
                client.get(
                    "/api/execution-suitability?examples_per_status=0"
                )
            )
            second = asyncio.create_task(
                client.get(
                    "/api/execution-suitability?examples_per_status=1"
                )
            )
            assert await asyncio.to_thread(started.wait, 2.0)
            release.set()
            return await asyncio.gather(first, second)

    first_response, second_response = asyncio.run(exercise())

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert sorted(calls) == [0, 1]
