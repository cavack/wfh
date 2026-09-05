from __future__ import annotations

import asyncio
import time
from typing import Any

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


class _ModeledClient:
    def __init__(self, subscriptions: tuple[str, ...]) -> None:
        self.subscriptions = {key: object() for key in subscriptions}

    async def close(self) -> None:
        self.subscriptions.clear()


class _GenerationExchange(_CapabilityExchange):
    """Model the real CCXT membership-hash fan-out and generation lifecycle."""

    def __init__(
        self,
        *,
        fail_close: bool = False,
        suppress_cancel: bool = False,
        retain_clients_on_close: bool = False,
    ) -> None:
        super().__init__()
        self.clients: dict[str, _ModeledClient] = {}
        self.stream_routes: dict[tuple[str, tuple[str, ...]], int] = {}
        self.markets = {"BTC/USDT:USDT": {"symbol": "BTC/USDT:USDT"}}
        self.market_source: _GenerationExchange | None = None
        self.clients_at_market_handoff: int | None = None
        self.routes_at_market_handoff: int | None = None
        self.closed = False
        self.close_started = asyncio.Event()
        self.close_release = asyncio.Event()
        self.close_release.set()
        self.fail_close = fail_close
        self.suppress_cancel = suppress_cancel
        self.retain_clients_on_close = retain_clients_on_close
        self.cancel_release = asyncio.Event()
        self._watch_keys: set[tuple[str, tuple[str, ...]]] = set()
        self._unwatch_keys: set[tuple[str, tuple[str, ...]]] = set()
        self.watch_memberships: list[tuple[str, tuple[str, ...]]] = []

    def _record_watch(self, kind: str, symbols: tuple[str, ...]) -> None:
        key = (kind, symbols)
        if key in self._watch_keys:
            return
        self._watch_keys.add(key)
        self.stream_routes[key] = len(self.stream_routes)
        self.clients[f"watch:{kind}:{len(self.clients)}"] = _ModeledClient(symbols)
        self.watch_memberships.append(key)

    def _record_unwatch(self, kind: str, symbols: tuple[str, ...]) -> None:
        key = (kind, symbols)
        if key in self._unwatch_keys:
            return
        self._unwatch_keys.add(key)
        # Real Binance can create a separate client for a different unwatch hash.
        self.clients[f"unwatch:{kind}:{len(self.clients)}"] = _ModeledClient(())

    async def _yield_payload(self) -> None:
        try:
            await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            if not self.suppress_cancel:
                raise
            self.suppress_cancel = False
            await self.cancel_release.wait()

    async def watch_order_book_for_symbols(self, symbols, limit=None, params=None):
        del limit, params
        members = tuple(symbols)
        self._record_watch("orderbook", members)
        await self._yield_payload()
        return {
            "symbol": members[0],
            "timestamp": int(time.time() * 1000),
            "bids": [[1.0, 1.0]],
            "asks": [[1.01, 1.0]],
        }

    async def un_watch_order_book_for_symbols(self, symbols, params=None):
        del params
        self._record_unwatch("orderbook", tuple(symbols))
        return {}

    async def watch_trades_for_symbols(self, symbols, since=None, limit=None, params=None):
        del since, limit, params
        members = tuple(symbols)
        self._record_watch("trades", members)
        await self._yield_payload()
        now_ms = int(time.time() * 1000)
        return [
            {
                "id": f"{members[0]}:{now_ms}",
                "symbol": members[0],
                "timestamp": now_ms,
                "side": "sell",
                "price": 1.0,
                "amount": 1.0,
            }
        ]

    async def un_watch_trades_for_symbols(self, symbols, params=None):
        del params
        self._record_unwatch("trades", tuple(symbols))
        return {}

    async def watch_tickers(self, symbols=None, params=None):
        del params
        members = tuple(symbols or ())
        self._record_watch("ticker", members)
        await self._yield_payload()
        return {symbol: {"symbol": symbol, "last": 1.0} for symbol in members}

    async def un_watch_tickers(self, symbols=None, params=None):
        del params
        self._record_unwatch("ticker", tuple(symbols or ()))
        return {}

    def set_markets_from_exchange(self, source: Any) -> None:
        self.market_source = source
        self.clients_at_market_handoff = len(self.clients)
        self.routes_at_market_handoff = len(self.stream_routes)
        self.markets = source.markets

    async def close(self) -> None:
        self.close_started.set()
        await self.close_release.wait()
        if self.fail_close:
            raise RuntimeError("close failed")
        self.closed = True
        if not self.retain_clients_on_close:
            for client in tuple(self.clients.values()):
                await client.close()
            self.clients.clear()


def _client_counts(exchanges: list[_GenerationExchange]) -> tuple[int, int]:
    live = [client for exchange in exchanges if not exchange.closed for client in exchange.clients.values()]
    return len(live), sum(len(client.subscriptions) for client in live)


async def _wait_until(predicate, *, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition did not become true before timeout")
        await asyncio.sleep(0.01)


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
        assert cached is not None and cached["_received_at"] == now
    elif kind == "trades":
        assert [
            row["id"]
            for row in manager.get_realtime_trades("binance", "AAA/USDT:USDT", now=now)
        ] == ["a-1"]
        assert manager.get_realtime_trades("binance", "CCC/USDT:USDT", now=now) == []
    else:
        assert manager.get_realtime_ticker("binance", "AAA/USDT:USDT") == {
            "symbol": "AAA/USDT:USDT",
            "last": 1.0,
        }
        assert manager.get_realtime_ticker("binance", "CCC/USDT:USDT") is None


def test_shared_orderbook_uses_exchange_safe_depth_limit() -> None:
    manager = WebSocketManager()
    observed: list[int | None] = []

    async def watch(symbols, limit=None, params=None):
        del symbols, params
        observed.append(limit)
        return {}

    async def scenario() -> None:
        await manager._watch_shared_evidence_payload(
            watch,
            ex_name="bybit",
            kind="orderbook",
            symbols=("AAA/USDT:USDT",),
        )
        await manager._watch_shared_evidence_payload(
            watch,
            ex_name="binance",
            kind="orderbook",
            symbols=("AAA/USDT:USDT",),
        )

    asyncio.run(scenario())
    assert observed == [50, 20]


def test_shared_subscribers_are_bounded(monkeypatch) -> None:
    manager = WebSocketManager()
    created: list[_GenerationExchange] = []

    def new_exchange(_name: str):
        exchange = _GenerationExchange()
        created.append(exchange)
        return exchange

    monkeypatch.setattr(manager, "_new_exchange", new_exchange)

    async def scenario() -> None:
        for index in range(manager.shared_evidence_symbol_limit + 20):
            manager.subscribe_shared_evidence("binance", f"S{index:03d}/USDT:USDT")
        await _wait_until(lambda: len(created) == 1)
        assert len(manager.shared_evidence_subscribers["binance"]) == manager.shared_evidence_symbol_limit
        await manager.close_all()

    asyncio.run(scenario())


def test_shared_membership_churn_keeps_one_transport_generation(monkeypatch) -> None:
    manager = WebSocketManager()
    created: list[_GenerationExchange] = []

    def new_exchange(_name: str):
        exchange = _GenerationExchange()
        created.append(exchange)
        return exchange

    monkeypatch.setattr(manager, "_new_exchange", new_exchange)

    async def scenario() -> list[tuple[int, int]]:
        symbols = [f"S{i}/USDT:USDT" for i in range(7)]
        for symbol in symbols[:4]:
            assert manager.subscribe_shared_evidence("binance", symbol) is True
        await _wait_until(lambda: len(created) == 1 and _client_counts(created) == (3, 12))
        observed = [_client_counts(created)]

        active = set(symbols[:4])
        for retired, added in zip(symbols[3::-1], symbols[4:7]):
            manager.subscribe_shared_evidence("binance", added)
            manager.unsubscribe_shared_evidence("binance", retired)
            active.discard(retired)
            active.add(added)
            expected_created = len(observed) + 1
            await _wait_until(
                lambda: len(created) >= expected_created
                and _client_counts(created) == (3, 3 * len(active)),
                timeout=1.5,
            )
            observed.append(_client_counts(created))

        await manager.close_all()
        return observed

    observed = asyncio.run(scenario())
    assert observed == [(3, 12), (3, 12), (3, 12), (3, 12)]


def test_replacement_is_created_only_after_prior_exchange_closed(monkeypatch) -> None:
    manager = WebSocketManager()
    created: list[_GenerationExchange] = []
    prior_closed_at_creation: list[bool] = []

    def new_exchange(_name: str):
        if created:
            prior_closed_at_creation.append(created[-1].closed)
        exchange = _GenerationExchange()
        created.append(exchange)
        return exchange

    monkeypatch.setattr(manager, "_new_exchange", new_exchange)

    async def scenario() -> None:
        manager.subscribe_shared_evidence("binance", "A/USDT:USDT")
        manager.subscribe_shared_evidence("binance", "B/USDT:USDT")
        await _wait_until(lambda: len(created) == 1 and _client_counts(created) == (3, 6))
        manager.subscribe_shared_evidence("binance", "C/USDT:USDT")
        manager.unsubscribe_shared_evidence("binance", "A/USDT:USDT")
        await _wait_until(lambda: len(created) == 2 and _client_counts(created) == (3, 6))
        await manager.close_all()

    asyncio.run(scenario())
    assert prior_closed_at_creation == [True]


def test_fresh_generation_copies_only_static_market_metadata(monkeypatch) -> None:
    manager = WebSocketManager()
    created: list[_GenerationExchange] = []

    def new_exchange(_name: str):
        exchange = _GenerationExchange()
        created.append(exchange)
        return exchange

    monkeypatch.setattr(manager, "_new_exchange", new_exchange)

    async def scenario() -> None:
        manager.subscribe_shared_evidence("binance", "A/USDT:USDT")
        manager.subscribe_shared_evidence("binance", "B/USDT:USDT")
        await _wait_until(lambda: len(created) == 1 and _client_counts(created) == (3, 6))
        manager.subscribe_shared_evidence("binance", "C/USDT:USDT")
        manager.unsubscribe_shared_evidence("binance", "A/USDT:USDT")
        await _wait_until(lambda: len(created) == 2 and _client_counts(created) == (3, 6))
        await manager.close_all()

    asyncio.run(scenario())
    assert created[1].market_source is created[0]
    assert created[1].clients_at_market_handoff == 0
    assert created[1].routes_at_market_handoff == 0
    assert created[1].markets is created[0].markets


def test_membership_changes_during_retirement_are_latest_wins(monkeypatch) -> None:
    manager = WebSocketManager()
    created: list[_GenerationExchange] = []

    def new_exchange(_name: str):
        exchange = _GenerationExchange()
        created.append(exchange)
        return exchange

    monkeypatch.setattr(manager, "_new_exchange", new_exchange)

    async def scenario() -> None:
        manager.subscribe_shared_evidence("binance", "A/USDT:USDT")
        manager.subscribe_shared_evidence("binance", "B/USDT:USDT")
        await _wait_until(lambda: len(created) == 1 and _client_counts(created) == (3, 6))
        created[0].close_release.clear()

        manager.subscribe_shared_evidence("binance", "C/USDT:USDT")
        manager.unsubscribe_shared_evidence("binance", "A/USDT:USDT")
        await _wait_until(lambda: created[0].close_started.is_set())
        assert len(created) == 1

        manager.subscribe_shared_evidence("binance", "D/USDT:USDT")
        manager.unsubscribe_shared_evidence("binance", "B/USDT:USDT")
        created[0].close_release.set()

        await _wait_until(lambda: len(created) == 2 and _client_counts(created) == (3, 6))
        final_memberships = {members for _, members in created[1].watch_memberships}
        assert final_memberships == {("C/USDT:USDT", "D/USDT:USDT")}
        await manager.close_all()

    asyncio.run(scenario())


def test_failed_retirement_blocks_replacement(monkeypatch) -> None:
    manager = WebSocketManager()
    created: list[_GenerationExchange] = []

    def new_exchange(_name: str):
        exchange = _GenerationExchange(fail_close=(len(created) == 0))
        created.append(exchange)
        return exchange

    monkeypatch.setattr(manager, "_new_exchange", new_exchange)

    async def scenario() -> None:
        manager.subscribe_shared_evidence("binance", "A/USDT:USDT")
        manager.subscribe_shared_evidence("binance", "B/USDT:USDT")
        await _wait_until(lambda: len(created) == 1 and _client_counts(created) == (3, 6))
        manager.subscribe_shared_evidence("binance", "C/USDT:USDT")
        manager.unsubscribe_shared_evidence("binance", "A/USDT:USDT")
        await _wait_until(lambda: created[0].close_started.is_set())
        await asyncio.sleep(0.05)
        assert len(created) == 1
        assert "binance" in getattr(manager, "shared_evidence_blocked_exchanges", set())
        assert manager.shared_evidence_subscribers["binance"] == {
            "B/USDT:USDT",
            "C/USDT:USDT",
        }
        created[0].fail_close = False
        await manager.close_all()

    asyncio.run(scenario())



def test_close_that_retains_ccxt_clients_blocks_replacement(monkeypatch) -> None:
    manager = WebSocketManager()
    created: list[_GenerationExchange] = []

    def new_exchange(_name: str):
        exchange = _GenerationExchange(retain_clients_on_close=(len(created) == 0))
        created.append(exchange)
        return exchange

    monkeypatch.setattr(manager, "_new_exchange", new_exchange)

    async def scenario() -> None:
        manager.subscribe_shared_evidence("binance", "A/USDT:USDT")
        manager.subscribe_shared_evidence("binance", "B/USDT:USDT")
        await _wait_until(lambda: len(created) == 1 and _client_counts(created) == (3, 6))
        manager.subscribe_shared_evidence("binance", "C/USDT:USDT")
        manager.unsubscribe_shared_evidence("binance", "A/USDT:USDT")
        await _wait_until(lambda: created[0].close_started.is_set())
        await asyncio.sleep(0.05)
        assert len(created) == 1
        assert "binance" in getattr(manager, "shared_evidence_blocked_exchanges", set())
        created[0].retain_clients_on_close = False
        await manager.close_all()

    asyncio.run(scenario())


def test_reconcile_request_is_not_lost_while_singleflight_task_is_finishing(monkeypatch) -> None:
    manager = WebSocketManager()
    calls: list[int] = []
    first_release = asyncio.Event()

    async def fake_reconcile(_ex_name: str) -> None:
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            await first_release.wait()

    monkeypatch.setattr(manager, "_reconcile_shared_evidence_exchange", fake_reconcile)

    async def scenario() -> None:
        manager._schedule_shared_evidence_reconcile("binance")
        await _wait_until(lambda: calls == [1])
        manager._schedule_shared_evidence_reconcile("binance")
        first_release.set()
        await _wait_until(lambda: len(calls) >= 2, timeout=0.5)
        await manager.close_all()

    asyncio.run(scenario())
    assert calls == [1, 2]

def test_pending_consumer_retirement_suppresses_replacement(monkeypatch) -> None:
    manager = WebSocketManager()
    manager.retirement_timeout_seconds = 0.05
    created: list[_GenerationExchange] = []

    def new_exchange(_name: str):
        exchange = _GenerationExchange(suppress_cancel=(len(created) == 0))
        created.append(exchange)
        return exchange

    monkeypatch.setattr(manager, "_new_exchange", new_exchange)

    async def scenario() -> None:
        manager.subscribe_shared_evidence("binance", "A/USDT:USDT")
        manager.subscribe_shared_evidence("binance", "B/USDT:USDT")
        await _wait_until(lambda: len(created) == 1 and _client_counts(created) == (3, 6))
        manager.subscribe_shared_evidence("binance", "C/USDT:USDT")
        manager.unsubscribe_shared_evidence("binance", "A/USDT:USDT")
        await asyncio.sleep(0.12)
        assert len(created) == 1
        assert "binance" in getattr(manager, "shared_evidence_blocked_exchanges", set())
        created[0].cancel_release.set()
        created[0].close_release.set()
        await manager.close_all()

    asyncio.run(scenario())


def test_unsupported_shared_evidence_clears_membership_without_transport_leak(monkeypatch) -> None:
    manager = WebSocketManager()
    created: list[_GenerationExchange] = []

    class _Unsupported(_GenerationExchange):
        def __init__(self) -> None:
            super().__init__()
            self.has["unWatchTradesForSymbols"] = False

    def new_exchange(_name: str):
        exchange = _Unsupported()
        created.append(exchange)
        return exchange

    monkeypatch.setattr(manager, "_new_exchange", new_exchange)

    async def scenario() -> None:
        assert manager.subscribe_shared_evidence("okx", "A/USDT:USDT") is True
        await _wait_until(lambda: "okx" in manager.unsupported_shared_evidence_exchanges)
        assert "okx" not in manager.shared_evidence_subscribers
        assert _client_counts(created) == (0, 0)
        await manager.close_all()

    asyncio.run(scenario())


def test_close_all_closes_direct_shared_and_reconcile_resources(monkeypatch) -> None:
    manager = WebSocketManager()
    created: list[_GenerationExchange] = []

    class _Closable:
        def __init__(self) -> None:
            self.closed = 0

        async def close(self) -> None:
            self.closed += 1

    direct = _Closable()
    manager.exchanges["binance"] = direct

    def new_exchange(_name: str):
        exchange = _GenerationExchange()
        created.append(exchange)
        return exchange

    monkeypatch.setattr(manager, "_new_exchange", new_exchange)

    async def scenario() -> None:
        manager.subscribe_shared_evidence("binance", "A/USDT:USDT")
        await _wait_until(lambda: len(created) == 1 and _client_counts(created) == (3, 3))
        await manager.close_all()
        assert not [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and not task.done()
            and "shared" in repr(task.get_coro()).lower()
        ]

    asyncio.run(scenario())
    assert direct.closed == 1
    assert created[0].closed is True
    assert manager.exchanges == {}
    assert manager.shared_evidence_exchanges == {}
