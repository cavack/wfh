from __future__ import annotations

import asyncio

import waterfallhunter.core.ws_streamer as ws_module
from waterfallhunter.core.ws_streamer import WebSocketManager


def test_liquidation_cache_normalizes_long_short_notional_and_burst_ratio() -> None:
    manager = WebSocketManager()
    symbol = "TEST/USDT:USDT"
    manager._ingest_liquidations(
        "binance",
        symbol,
        [
            {"timestamp": 40_000, "side": "buy", "contracts": 2.0, "contractSize": 1.0, "price": 100.0},
            {"timestamp": 70_000, "side": "sell", "contracts": 3.0, "contractSize": 1.0, "price": 100.0},
            {"timestamp": 95_000, "side": "sell", "contracts": 4.0, "contractSize": 1.0, "price": 100.0},
            {"timestamp": 99_000, "side": "buy", "contracts": 1.0, "contractSize": 1.0, "price": 100.0},
        ],
        received_at=100.0,
    )

    flow = manager.get_realtime_liquidation_flow("binance", symbol, now=100.0)

    assert flow is not None
    assert flow["available"] is True
    assert flow["long_liquidation_notional_1m"] == 700.0
    assert flow["short_liquidation_notional_1m"] == 100.0
    assert flow["liquidation_velocity_usd_per_min"] == 800.0
    assert flow["burst_ratio"] == 4.0
    assert flow["observed_at"] == 99.0


def test_subscription_starts_and_unsubscribe_stops_liquidation_stream(monkeypatch) -> None:
    manager = WebSocketManager()
    symbol = "TEST/USDT:USDT"
    monkeypatch.setattr(ws_module, "ccxt_pro", object())

    async def idle(*args, **kwargs):
        await asyncio.Future()

    monkeypatch.setattr(manager, "watch_orderbook_stream", idle)
    monkeypatch.setattr(manager, "_watch_stream", idle)
    monkeypatch.setattr(manager, "_watch_liquidations_stream", idle)

    async def scenario() -> None:
        manager.subscribe("binance", symbol)
        await asyncio.sleep(0)
        assert f"binance:{symbol}:liquidations" in manager.active_tasks
        manager.unsubscribe("binance", symbol)
        await asyncio.sleep(0)
        assert f"binance:{symbol}:liquidations" not in manager.active_tasks

    asyncio.run(scenario())


def test_liquidation_only_subscription_upgrades_to_full_without_duplicate(monkeypatch) -> None:
    manager = WebSocketManager()
    symbol = "PRE/USDT:USDT"
    monkeypatch.setattr(ws_module, "ccxt_pro", object())

    async def idle(*args, **kwargs):
        await asyncio.Future()

    monkeypatch.setattr(manager, "watch_orderbook_stream", idle)
    monkeypatch.setattr(manager, "_watch_stream", idle)
    monkeypatch.setattr(manager, "_watch_liquidations_stream", idle)

    async def scenario() -> None:
        manager.subscribe_liquidations("binance", symbol)
        await asyncio.sleep(0)
        liquidation_id = f"binance:{symbol}:liquidations"
        assert set(manager.active_tasks) == {liquidation_id}
        liquidation_task = manager.active_tasks[liquidation_id]

        manager.subscribe("binance", symbol)
        await asyncio.sleep(0)
        assert set(manager.active_tasks) == {
            f"binance:{symbol}",
            f"binance:{symbol}:ticker",
            f"binance:{symbol}:trades",
            liquidation_id,
        }
        assert manager.active_tasks[liquidation_id] is liquidation_task

        manager.unsubscribe("binance", symbol)
        await asyncio.sleep(0)
        assert not manager.active_tasks

    asyncio.run(scenario())


def test_full_subscription_can_downgrade_to_liquidation_only_without_restarting_liquidations(monkeypatch) -> None:
    manager = WebSocketManager()
    symbol = "DOWNGRADE/USDT:USDT"
    monkeypatch.setattr(ws_module, "ccxt_pro", object())

    async def idle(*args, **kwargs):
        await asyncio.Future()

    monkeypatch.setattr(manager, "watch_orderbook_stream", idle)
    monkeypatch.setattr(manager, "_watch_stream", idle)
    monkeypatch.setattr(manager, "_watch_liquidations_stream", idle)

    async def scenario() -> None:
        manager.subscribe("binance", symbol)
        await asyncio.sleep(0)
        stream_id = f"binance:{symbol}"
        liquidation_id = f"{stream_id}:liquidations"
        liquidation_task = manager.active_tasks[liquidation_id]
        manager.live_orderbooks[stream_id] = {"updated_at": 1.0, "data": {"bids": [], "asks": []}}
        manager.live_tickers[stream_id] = {"updated_at": 1.0, "data": {"last": 1.0}}
        manager.live_trades[stream_id] = {"updated_at": 1.0, "data": []}
        manager.live_liquidations[stream_id] = {"updated_at": 1.0, "events": []}
        manager.circuit_breakers[stream_id] = object()
        manager.circuit_breakers[liquidation_id] = object()
        manager.message_counters[stream_id] = 4
        manager.message_counters[liquidation_id] = 2

        manager.retain_liquidations_only("binance", symbol)
        await asyncio.sleep(0)

        assert set(manager.active_tasks) == {liquidation_id}
        assert manager.active_tasks[liquidation_id] is liquidation_task
        assert stream_id not in manager.live_orderbooks
        assert stream_id not in manager.live_tickers
        assert stream_id not in manager.live_trades
        assert stream_id in manager.live_liquidations
        assert stream_id not in manager.circuit_breakers
        assert liquidation_id in manager.circuit_breakers
        assert stream_id not in manager.message_counters
        assert manager.message_counters[liquidation_id] == 2

        manager.unsubscribe("binance", symbol)
        await asyncio.sleep(0)

    asyncio.run(scenario())


def test_liquidation_stream_skips_provider_without_declared_support(monkeypatch) -> None:
    manager = WebSocketManager()
    symbol = "NOSUPPORT/USDT:USDT"
    called = False

    class Exchange:
        has = {"watchLiquidations": None}

        async def watch_liquidations(self, *args, **kwargs):
            nonlocal called
            called = True
            await asyncio.sleep(1.0)
            return []

    async def get_exchange(_name):
        return Exchange()

    monkeypatch.setattr(manager, "_get_exchange", get_exchange)

    async def scenario() -> None:
        task_id = f"bingx:{symbol}:liquidations"
        manager.active_tasks[task_id] = asyncio.current_task()
        await asyncio.wait_for(
            manager._watch_liquidations_stream("bingx", symbol), timeout=0.05
        )
        assert task_id not in manager.active_tasks

    asyncio.run(scenario())
    assert called is False


def test_pretrigger_scale_uses_one_liquidation_task_per_symbol(monkeypatch) -> None:
    manager = WebSocketManager()
    monkeypatch.setattr(ws_module, "ccxt_pro", object())

    async def idle(*args, **kwargs):
        await asyncio.Future()

    monkeypatch.setattr(manager, "_watch_liquidations_stream", idle)
    symbols = [f"PRE{i}/USDT:USDT" for i in range(44)]

    async def scenario() -> None:
        for symbol in symbols:
            manager.subscribe_liquidations("binance", symbol)
        await asyncio.sleep(0)
        assert len(manager.active_tasks) == 44
        assert all(task_id.endswith(":liquidations") for task_id in manager.active_tasks)
        for symbol in symbols:
            manager.unsubscribe("binance", symbol)
        await asyncio.sleep(0)
        assert manager.active_tasks == {}

    asyncio.run(scenario())


def test_unsupported_liquidation_capability_is_cached_between_subscriptions(monkeypatch) -> None:
    manager = WebSocketManager()
    symbol = "NOSUPPORTCACHE/USDT:USDT"
    monkeypatch.setattr(ws_module, "ccxt_pro", object())
    lookups = 0

    class Exchange:
        has = {"watchLiquidations": None}

    async def get_exchange(_name):
        nonlocal lookups
        lookups += 1
        return Exchange()

    monkeypatch.setattr(manager, "_get_exchange", get_exchange)

    async def scenario() -> None:
        manager.subscribe_liquidations("bingx", symbol)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert f"bingx:{symbol}:liquidations" not in manager.active_tasks
        manager.subscribe_liquidations("bingx", symbol)
        await asyncio.sleep(0)
        assert f"bingx:{symbol}:liquidations" not in manager.active_tasks

    asyncio.run(scenario())
    assert lookups == 1


def test_gateio_exchange_id_is_mapped_at_websocket_boundary(monkeypatch) -> None:
    manager = WebSocketManager()
    created = []

    class Exchange:
        pass

    class FakeCCXTPro:
        @staticmethod
        def gate(config):
            created.append(config)
            return Exchange()

    monkeypatch.setattr(ws_module, "ccxt_pro", FakeCCXTPro())

    async def scenario() -> None:
        exchange = await manager._get_exchange("gateio")
        assert isinstance(exchange, Exchange)
        assert await manager._get_exchange("gateio") is exchange

    asyncio.run(scenario())
    assert len(created) == 1
