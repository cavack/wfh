from __future__ import annotations

import asyncio
import time

import pytest

from waterfallhunter.core.ws_streamer import CircuitBreaker, WebSocketManager


REQUIRED_HAS = {
    "watchOrderBookForSymbols": True,
    "unWatchOrderBookForSymbols": True,
    "watchTradesForSymbols": True,
    "unWatchTradesForSymbols": True,
    "watchTickers": True,
    "unWatchTickers": True,
}


class _CapabilityExchange:
    def __init__(self, **overrides: object) -> None:
        self.has = {**REQUIRED_HAS, **overrides}

    async def watch_order_book_for_symbols(self, symbols, limit=None, params=None):
        raise AssertionError("not used")

    async def un_watch_order_book_for_symbols(self, symbols, params=None):
        raise AssertionError("not used")

    async def watch_trades_for_symbols(self, symbols, since=None, limit=None, params=None):
        raise AssertionError("not used")

    async def un_watch_trades_for_symbols(self, symbols, params=None):
        raise AssertionError("not used")

    async def watch_tickers(self, symbols=None, params=None):
        raise AssertionError("not used")

    async def un_watch_tickers(self, symbols=None, params=None):
        raise AssertionError("not used")


def test_shared_evidence_capability_requires_explicit_watch_and_unwatch_support() -> None:
    manager = WebSocketManager()

    assert manager._shared_evidence_capable(_CapabilityExchange()) is True
    assert manager._shared_evidence_capable(
        _CapabilityExchange(unWatchTradesForSymbols=False)
    ) is False
    assert manager._shared_evidence_capable(
        _CapabilityExchange(watchOrderBookForSymbols="emulated")
    ) is False


@pytest.mark.parametrize("kind", ["orderbook", "trades", "ticker"])
def test_shared_evidence_update_reuses_existing_causal_caches(kind: str) -> None:
    manager = WebSocketManager()
    allowed = {"AAA/USDT:USDT", "BBB/USDT:USDT"}
    now = time.time()

    if kind == "orderbook":
        payload = {
            "symbol": "AAA/USDT:USDT",
            "timestamp": int(now * 1000),
            "bids": [[1.0, 10.0]],
            "asks": [[1.01, 10.0]],
        }
    elif kind == "trades":
        payload = [
            {
                "id": "a-1",
                "symbol": "AAA/USDT:USDT",
                "timestamp": int(now * 1000) - 100,
                "side": "sell",
                "price": 1.0,
                "amount": 2.0,
            },
            {
                "id": "c-1",
                "symbol": "CCC/USDT:USDT",
                "timestamp": int(now * 1000) - 100,
                "side": "buy",
                "price": 2.0,
                "amount": 1.0,
            },
        ]
    else:
        payload = {
            "AAA/USDT:USDT": {"symbol": "AAA/USDT:USDT", "last": 1.0},
            "CCC/USDT:USDT": {"symbol": "CCC/USDT:USDT", "last": 2.0},
        }

    manager._ingest_shared_evidence_update(
        "binance", kind, payload, allowed_symbols=allowed, received_at=now
    )

    if kind == "orderbook":
        cached = manager.get_realtime_orderbook("binance", "AAA/USDT:USDT")
        assert cached is not None
        assert cached["_received_at"] == now
    elif kind == "trades":
        assert [row["id"] for row in manager.get_realtime_trades(
            "binance", "AAA/USDT:USDT", now=now
        )] == ["a-1"]
        assert manager.get_realtime_trades("binance", "CCC/USDT:USDT", now=now) == []
    else:
        assert manager.get_realtime_ticker("binance", "AAA/USDT:USDT") == {
            "symbol": "AAA/USDT:USDT",
            "last": 1.0,
        }
        assert manager.get_realtime_ticker("binance", "CCC/USDT:USDT") is None


def test_shared_evidence_subscribers_are_bounded_and_tasks_are_singleflight(monkeypatch) -> None:
    manager = WebSocketManager()
    started: list[tuple[str, str]] = []
    release = asyncio.Event()

    async def fake_consumer(exchange: str, kind: str) -> None:
        started.append((exchange, kind))
        await release.wait()

    monkeypatch.setattr(manager, "_watch_shared_evidence_stream", fake_consumer)

    async def scenario() -> None:
        for index in range(manager.shared_evidence_symbol_limit + 20):
            manager.subscribe_shared_evidence("binance", f"S{index:03d}/USDT:USDT")
        await asyncio.sleep(0)
        # Re-subscribing an existing symbol must not create another task family.
        manager.subscribe_shared_evidence("binance", "S000/USDT:USDT")
        await asyncio.sleep(0)

        subscribers = manager.shared_evidence_subscribers["binance"]
        assert len(subscribers) == manager.shared_evidence_symbol_limit
        assert set(started) == {
            ("binance", "orderbook"),
            ("binance", "trades"),
            ("binance", "ticker"),
        }
        assert sum(
            1 for task_id in manager.active_tasks if task_id.startswith("shared-evidence:binance:")
        ) == 3

        release.set()
        await manager.close_all()

    asyncio.run(scenario())


def test_shared_orderbook_consumer_unwatches_and_ingests_only_current_members(monkeypatch) -> None:
    manager = WebSocketManager()
    symbol = "AAA/USDT:USDT"
    stale_symbol = "STALE/USDT:USDT"
    task_id = "shared-evidence:binance:orderbook"
    unwatched: list[tuple[str, ...]] = []

    class _Exchange(_CapabilityExchange):
        async def watch_order_book_for_symbols(self, symbols, limit=None, params=None):
            # End the consumer after this update so the test also exercises final unwatch.
            manager.active_tasks.pop(task_id, None)
            return {
                "symbol": symbol,
                "timestamp": 100_000,
                "bids": [[1.0, 10.0]],
                "asks": [[1.01, 10.0]],
            }

        async def un_watch_order_book_for_symbols(self, symbols, params=None):
            unwatched.append(tuple(symbols))
            return {}

    exchange = _Exchange()

    async def get_exchange(_name: str):
        return exchange

    monkeypatch.setattr(manager, "_get_shared_evidence_exchange", get_exchange)

    async def scenario() -> None:
        manager.shared_evidence_subscribers["binance"] = {symbol}
        manager.active_tasks[task_id] = asyncio.current_task()
        await manager._watch_shared_evidence_stream("binance", "orderbook")

    asyncio.run(scenario())

    assert manager.get_realtime_orderbook("binance", symbol) is not None
    assert manager.get_realtime_orderbook("binance", stale_symbol) is None
    assert unwatched == [(symbol,)]


def test_shared_orderbook_uses_exchange_safe_depth_limit(monkeypatch) -> None:
    manager = WebSocketManager()
    symbol = "AAA/USDT:USDT"
    task_id = "shared-evidence:bybit:orderbook"
    observed_limits: list[int | None] = []

    class _Exchange(_CapabilityExchange):
        async def watch_order_book_for_symbols(self, symbols, limit=None, params=None):
            observed_limits.append(limit)
            manager.active_tasks.pop(task_id, None)
            return {
                "symbol": symbol,
                "timestamp": int(time.time() * 1000),
                "bids": [[1.0, 10.0]],
                "asks": [[1.01, 10.0]],
            }

        async def un_watch_order_book_for_symbols(self, symbols, params=None):
            return {}

    exchange = _Exchange()

    async def get_exchange(_name: str):
        return exchange

    monkeypatch.setattr(manager, "_get_shared_evidence_exchange", get_exchange)

    async def scenario() -> None:
        manager.shared_evidence_subscribers["bybit"] = {symbol}
        manager.active_tasks[task_id] = asyncio.current_task()
        await manager._watch_shared_evidence_stream("bybit", "orderbook")

    asyncio.run(scenario())
    assert observed_limits == [50]


def test_shared_evidence_stream_uses_dedicated_exchange_instance(monkeypatch) -> None:
    manager = WebSocketManager()
    symbol = "AAA/USDT:USDT"
    task_id = "shared-evidence:binance:ticker"
    exchange = _CapabilityExchange()

    async def direct_getter(_name: str):
        raise AssertionError("shared pool reused the direct-stream exchange instance")

    async def shared_getter(_name: str):
        return exchange

    async def watch_tickers(symbols=None, params=None):
        manager.active_tasks.pop(task_id, None)
        return {symbol: {"symbol": symbol, "last": 1.0}}

    async def unwatch_tickers(symbols=None, params=None):
        return {}

    exchange.watch_tickers = watch_tickers
    exchange.un_watch_tickers = unwatch_tickers
    monkeypatch.setattr(manager, "_get_exchange", direct_getter)
    monkeypatch.setattr(
        manager, "_get_shared_evidence_exchange", shared_getter, raising=False
    )

    async def scenario() -> None:
        manager.shared_evidence_subscribers["binance"] = {symbol}
        manager.active_tasks[task_id] = asyncio.current_task()
        await manager._watch_shared_evidence_stream("binance", "ticker")

    asyncio.run(scenario())
    assert manager.get_realtime_ticker("binance", symbol) == {
        "symbol": symbol,
        "last": 1.0,
    }


def test_close_all_closes_and_releases_direct_and_shared_exchange_clients() -> None:
    manager = WebSocketManager()

    class _Closable:
        def __init__(self) -> None:
            self.closed = 0

        async def close(self) -> None:
            self.closed += 1

    direct = _Closable()
    shared = _Closable()
    manager.exchanges["binance"] = direct
    manager.shared_evidence_exchanges["binance"] = shared

    asyncio.run(manager.close_all())

    assert direct.closed == 1
    assert shared.closed == 1
    assert manager.exchanges == {}
    assert manager.shared_evidence_exchanges == {}

def test_unsupported_shared_evidence_clears_pending_membership(monkeypatch) -> None:
    manager = WebSocketManager()
    symbol = "AAA/USDT:USDT"
    task_id = "shared-evidence:okx:ticker"
    exchange = _CapabilityExchange(unWatchTradesForSymbols=False)

    async def shared_getter(_name: str):
        return exchange

    monkeypatch.setattr(manager, "_get_shared_evidence_exchange", shared_getter)

    async def scenario() -> None:
        manager.shared_evidence_subscribers["okx"] = {symbol}
        manager.active_tasks[task_id] = asyncio.current_task()
        await manager._watch_shared_evidence_stream("okx", "ticker")

    asyncio.run(scenario())
    assert "okx" in manager.unsupported_shared_evidence_exchanges
    assert "okx" not in manager.shared_evidence_subscribers


def test_shared_membership_change_unwatches_only_retired_symbols() -> None:
    manager = WebSocketManager()
    keep = "KEEP/USDT:USDT"
    retired = "OLD/USDT:USDT"
    added = "NEW/USDT:USDT"
    manager.shared_evidence_subscribers["bybit"] = {keep, added}
    unwatch_calls: list[tuple[str, ...]] = []
    watch_calls: list[tuple[str, ...]] = []

    async def unwatch(symbols, params=None):
        unwatch_calls.append(tuple(symbols))
        return {}

    async def watch(symbols=None, params=None):
        watch_calls.append(tuple(symbols or ()))
        return {keep: {"symbol": keep, "last": 1.0}}

    async def scenario() -> None:
        active, _ = await manager._shared_evidence_iteration(
            ex_name="bybit", kind="ticker", task_id="shared-evidence:bybit:ticker",
            watch=watch, unwatch=unwatch, breaker=CircuitBreaker(),
            active_symbols=(keep, retired), delay=1.0,
        )
        assert active == tuple(sorted((keep, added)))

    asyncio.run(scenario())
    assert unwatch_calls == [(retired,)]
    assert watch_calls == [tuple(sorted((keep, added)))]


def test_failed_shared_unwatch_retries_before_advancing_active_membership() -> None:
    manager = WebSocketManager()
    old_symbol = "OLD/USDT:USDT"
    new_symbol = "NEW/USDT:USDT"
    manager.shared_evidence_subscribers["binance"] = {new_symbol}
    unwatch_calls: list[tuple[str, ...]] = []
    watch_calls: list[tuple[str, ...]] = []
    unwatch_attempt = 0

    async def unwatch(symbols, params=None):
        nonlocal unwatch_attempt
        unwatch_attempt += 1
        unwatch_calls.append(tuple(symbols))
        if unwatch_attempt == 1:
            raise RuntimeError("transient unwatch failure")
        return {}

    async def watch(symbols=None, params=None):
        watch_calls.append(tuple(symbols or ()))
        return {new_symbol: {"symbol": new_symbol, "last": 1.0}}

    breaker = CircuitBreaker()

    async def scenario() -> None:
        active = (old_symbol,)
        active, delay = await manager._shared_evidence_iteration(
            ex_name="binance",
            kind="ticker",
            task_id="shared-evidence:binance:ticker",
            watch=watch,
            unwatch=unwatch,
            breaker=breaker,
            active_symbols=active,
            delay=1.0,
        )
        assert active == (old_symbol,)
        assert watch_calls == []

        active, _ = await manager._shared_evidence_iteration(
            ex_name="binance",
            kind="ticker",
            task_id="shared-evidence:binance:ticker",
            watch=watch,
            unwatch=unwatch,
            breaker=breaker,
            active_symbols=active,
            delay=delay,
        )
        assert active == (new_symbol,)

    asyncio.run(scenario())
    assert unwatch_calls == [(old_symbol,), (old_symbol,)]
    assert watch_calls == [(new_symbol,)]


def test_shared_unwatch_purges_retired_symbol_from_ccxt_caches() -> None:
    manager = WebSocketManager()
    symbol = "OLD/USDT:USDT"

    class _Exchange:
        def __init__(self) -> None:
            self.orderbooks = {symbol: {"bids": []}}
            self.trades = {symbol: [1]}
            self.tickers = {symbol: {"last": 1.0}}

    exchange = _Exchange()

    async def unwatch(symbols, params=None):
        return {}

    async def scenario() -> None:
        ok = await manager._unwatch_shared_evidence_symbols(
            unwatch,
            (symbol,),
            ex_name="binance",
            kind="ticker",
            exchange=exchange,
        )
        assert ok is True

    asyncio.run(scenario())
    assert symbol not in exchange.orderbooks
    assert symbol not in exchange.trades
    assert symbol not in exchange.tickers


def test_shared_membership_churn_schedules_bounded_client_recycle(monkeypatch) -> None:
    manager = WebSocketManager()
    manager.shared_evidence_client_generation_limit = 2
    # Model post-connect churn; initial population is intentionally not counted.
    manager.shared_evidence_exchanges["binance"] = object()
    recycled: list[str] = []

    async def fake_recycle(ex_name: str) -> None:
        recycled.append(ex_name)

    async def fake_consumer(ex_name: str, kind: str) -> None:
        await asyncio.sleep(3600)

    monkeypatch.setattr(manager, "_recycle_shared_evidence_exchange", fake_recycle)
    monkeypatch.setattr(manager, "_watch_shared_evidence_stream", fake_consumer)

    async def scenario() -> None:
        manager.subscribe_shared_evidence("binance", "A/USDT:USDT")
        manager.subscribe_shared_evidence("binance", "B/USDT:USDT")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        for task in list(manager.active_tasks.values()):
            task.cancel()
        await asyncio.gather(*manager.active_tasks.values(), return_exceptions=True)

    asyncio.run(scenario())
    assert recycled == ["binance"]
