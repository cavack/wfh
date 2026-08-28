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
