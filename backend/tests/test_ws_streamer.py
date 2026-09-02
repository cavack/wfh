from __future__ import annotations

from waterfallhunter.core.ws_streamer import WebSocketManager


def _book(price: float, *, timestamp_ms: int) -> dict:
    return {
        "symbol": "TEST/USDT:USDT",
        "timestamp": timestamp_ms,
        "bids": [[price, 10.0]],
        "asks": [[price + 0.01, 10.0]],
    }


def _trade(index: int, *, timestamp_ms: int) -> dict:
    return {
        "id": f"t-{index}",
        "symbol": "TEST/USDT:USDT",
        "timestamp": timestamp_ms,
        "side": "sell" if index % 2 else "buy",
        "price": 1.0,
        "amount": 1.0,
    }


def test_orderbook_history_is_deep_copied_bounded_and_temporally_valid() -> None:
    manager = WebSocketManager()
    symbol = "TEST/USDT:USDT"
    first = _book(1.0, timestamp_ms=10_000)
    manager._ingest_orderbook("binance", symbol, first, received_at=10.0)
    first["bids"][0][0] = 99.0
    manager._ingest_orderbook(
        "binance", symbol, _book(1.1, timestamp_ms=10_300), received_at=10.3
    )
    manager._ingest_orderbook(
        "binance", symbol, _book(1.2, timestamp_ms=10_600), received_at=10.6
    )

    samples = manager.get_realtime_orderbook_samples(
        "binance", symbol, count=3, min_span_seconds=0.5, now=10.7
    )

    assert [row["bids"][0][0] for row in samples] == [1.0, 1.1, 1.2]
    assert [row["_received_at"] for row in samples] == [10.0, 10.3, 10.6]

    for index in range(12):
        received_at = 11.0 + index * 0.1
        manager._ingest_orderbook(
            "binance",
            symbol,
            _book(2.0 + index, timestamp_ms=int(received_at * 1000)),
            received_at=received_at,
        )

    assert len(manager.live_orderbook_history[f"binance:{symbol}"]) <= 8


def test_orderbook_samples_fail_closed_when_history_is_too_old_or_too_tight() -> None:
    manager = WebSocketManager()
    symbol = "TEST/USDT:USDT"
    for received_at in (10.0, 10.1, 10.2):
        manager._ingest_orderbook(
            "binance",
            symbol,
            _book(1.0, timestamp_ms=int(received_at * 1000)),
            received_at=received_at,
        )

    assert manager.get_realtime_orderbook_samples(
        "binance", symbol, count=3, min_span_seconds=0.5, now=10.3
    ) == []
    assert manager.get_realtime_orderbook_samples(
        "binance", symbol, count=3, min_span_seconds=0.1, now=16.0
    ) == []


def test_trade_window_deduplicates_prunes_and_stays_bounded() -> None:
    manager = WebSocketManager()
    symbol = "TEST/USDT:USDT"
    now = 100.0
    rows = [_trade(index, timestamp_ms=99_000 + index) for index in range(600)]
    rows.append(dict(rows[-1]))
    rows.append(_trade(9999, timestamp_ms=1_000))

    manager._ingest_trades("binance", symbol, rows, received_at=now)
    trades = manager.get_realtime_trades("binance", symbol, now=now)

    assert len(trades) == 500
    assert len({trade["id"] for trade in trades}) == 500
    assert all(now * 1000 - trade["timestamp"] <= 60_000 for trade in trades)


def test_unsubscribe_removes_hot_evidence_history() -> None:
    manager = WebSocketManager()
    symbol = "TEST/USDT:USDT"
    manager._ingest_orderbook(
        "binance", symbol, _book(1.0, timestamp_ms=10_000), received_at=10.0
    )
    manager._ingest_trades(
        "binance", symbol, [_trade(1, timestamp_ms=10_000)], received_at=10.0
    )

    manager.unsubscribe("binance", symbol)

    assert manager.get_realtime_orderbook_samples(
        "binance", symbol, count=1, min_span_seconds=0.0, now=10.1
    ) == []
    assert manager.get_realtime_trades("binance", symbol, now=10.1) == []
    assert f"binance:{symbol}" not in manager.live_orderbook_history
