from __future__ import annotations

import waterfallhunter.main as main


class _GaugeCapture:
    def __init__(self) -> None:
        self.values: list[float] = []

    def set(self, value: float) -> None:
        self.values.append(float(value))


def test_update_websocket_metrics_exports_runtime_fanout(monkeypatch) -> None:
    diagnostics = {
        "active_tasks": 7,
        "liquidation_tasks": 3,
        "shared_liquidation_tasks": 1,
        "shared_liquidation_subscribers": 19,
        "shared_evidence_tasks": 3,
        "shared_evidence_subscribers": 43,
        "direct_exchange_instances": 2,
        "liquidation_exchange_instances": 1,
        "direct_exchange_retire_tasks": 4,
        "liquidation_exchange_retire_tasks": 1,
        "ccxt_clients": 11,
        "ccxt_subscriptions": 9,
    }
    monkeypatch.setattr(
        main.validator.ws_manager,
        "runtime_diagnostics",
        lambda: diagnostics,
        raising=False,
    )
    active = _GaugeCapture()
    liquidation = _GaugeCapture()
    shared = _GaugeCapture()
    subscribers = _GaugeCapture()
    shared_evidence_tasks = _GaugeCapture()
    shared_evidence_subscribers = _GaugeCapture()
    direct_instances = _GaugeCapture()
    liquidation_instances = _GaugeCapture()
    direct_retire = _GaugeCapture()
    liquidation_retire = _GaugeCapture()
    ccxt_clients = _GaugeCapture()
    ccxt_subscriptions = _GaugeCapture()
    monkeypatch.setattr(main, "websocket_active_tasks_metric", active, raising=False)
    monkeypatch.setattr(main, "websocket_liquidation_tasks_metric", liquidation, raising=False)
    monkeypatch.setattr(main, "websocket_shared_liquidation_tasks_metric", shared, raising=False)
    monkeypatch.setattr(main, "websocket_shared_liquidation_subscribers_metric", subscribers, raising=False)
    monkeypatch.setattr(main, "websocket_shared_evidence_tasks_metric", shared_evidence_tasks, raising=False)
    monkeypatch.setattr(main, "websocket_shared_evidence_subscribers_metric", shared_evidence_subscribers, raising=False)
    monkeypatch.setattr(main, "websocket_direct_exchange_instances_metric", direct_instances, raising=False)
    monkeypatch.setattr(main, "websocket_liquidation_exchange_instances_metric", liquidation_instances, raising=False)
    monkeypatch.setattr(main, "websocket_direct_exchange_retire_tasks_metric", direct_retire, raising=False)
    monkeypatch.setattr(main, "websocket_liquidation_exchange_retire_tasks_metric", liquidation_retire, raising=False)
    monkeypatch.setattr(main, "websocket_ccxt_clients_metric", ccxt_clients, raising=False)
    monkeypatch.setattr(main, "websocket_ccxt_subscriptions_metric", ccxt_subscriptions, raising=False)

    main._update_websocket_metrics()

    assert active.values == [7.0]
    assert liquidation.values == [3.0]
    assert shared.values == [1.0]
    assert subscribers.values == [19.0]
    assert shared_evidence_tasks.values == [3.0]
    assert shared_evidence_subscribers.values == [43.0]
    assert direct_instances.values == [2.0]
    assert liquidation_instances.values == [1.0]
    assert direct_retire.values == [4.0]
    assert liquidation_retire.values == [1.0]
    assert ccxt_clients.values == [11.0]
    assert ccxt_subscriptions.values == [9.0]
