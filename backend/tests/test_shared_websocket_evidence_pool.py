from __future__ import annotations

import asyncio
import time

import pytest

from waterfallhunter.core.ws_streamer import WebSocketManager


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

    monkeypatch.setattr(manager, "_get_exchange", get_exchange)

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

    monkeypatch.setattr(manager, "_get_exchange", get_exchange)

    async def scenario() -> None:
        manager.shared_evidence_subscribers["bybit"] = {symbol}
        manager.active_tasks[task_id] = asyncio.current_task()
        await manager._watch_shared_evidence_stream("bybit", "orderbook")

    asyncio.run(scenario())
    assert observed_limits == [50]
