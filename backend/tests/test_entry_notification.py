from __future__ import annotations

import asyncio
import json
import sqlite3
import time

import httpx

from schema_test_support import migrate_test_database
from waterfallhunter.core.entry_decision_store import EntryDecisionStore
from waterfallhunter.core.notification_delivery import (
    DeliveryDisposition,
    DeliveryResult,
    DurableNotificationWorker,
)
from waterfallhunter.core.notifier import TelegramNotifier, TelegramSignalTransport


def entry_packet(decision: str = "ENTRY_READY") -> dict:
    return {
        "contract_version": "entry_decision_v1",
        "policy_version": "entry_policy_v1",
        "evaluated_at": 100,
        "decision": decision,
        "lifecycle_state": "PRE-TRIGGER",
        "entry_readiness": 84.5,
        "evidence_coverage_pct": 91.0,
        "hard_blocked": False,
        "block_reasons": [],
        "reason_codes": ["SELL_PRESSURE_CONFIRMED"],
        "components": {"cascade": {"points": 8.5, "maximum": 10.0}},
        "trade_plan": {
            "entry_price": 0.1,
            "stop_loss": 0.103,
            "take_profit_1": 0.097,
            "take_profit_2": 0.094,
            "take_profit_3": 0.091,
            "leverage": 3.0,
        },
        "policy": {},
    }


class FakeTransport:
    def __init__(self):
        self.calls: list[dict] = []

    async def deliver(self, event: dict) -> DeliveryResult:
        self.calls.append(event)
        return DeliveryResult(DeliveryDisposition.DELIVERED)


def test_entry_ready_transition_creates_durable_notification(tmp_path) -> None:
    db_path = migrate_test_database(tmp_path / "entry-notify.db")
    store = EntryDecisionStore(db_path)
    event_id = store.append_if_changed("SXT/USDT:USDT", entry_packet())
    assert event_id == 1
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT event_id,decision_event_id,event_type,status,payload_json "
            "FROM entry_notification_outbox"
        ).fetchone()
    assert row[:4] == ("entry:1:ready", 1, "ENTRY_READY", "PENDING")
    payload = json.loads(row[4])
    assert payload["symbol"] == "SXT/USDT:USDT"
    assert payload["decision_packet"]["entry_readiness"] == 84.5


def test_entry_ready_outbox_is_delivered_by_generic_worker(tmp_path) -> None:
    db_path = migrate_test_database(tmp_path / "entry-delivery.db")
    EntryDecisionStore(db_path).append_if_changed("SXT/USDT:USDT", entry_packet())
    transport = FakeTransport()
    worker = DurableNotificationWorker(
        db_path,
        transport,
        worker_id="entry-worker",
        outbox_table="entry_notification_outbox",
    )
    result = asyncio.run(worker.dispatch_once(now=int(time.time()) + 1))
    assert result is not None and result.state == "DELIVERED"
    assert transport.calls[0]["event_type"] == "ENTRY_READY"


def test_telegram_transport_classifies_success_and_errors() -> None:
    responses = [
        httpx.Response(200, json={"ok": True, "result": {"message_id": 1}}),
        httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 7}}),
        httpx.Response(403, json={"ok": False, "description": "Forbidden"}),
    ]

    async def run() -> list[DeliveryResult]:
        queue = list(responses)

        async def handler(request: httpx.Request) -> httpx.Response:
            return queue.pop(0)

        transport = TelegramSignalTransport(
            "token",
            "123",
            http_transport=httpx.MockTransport(handler),
        )
        event = {
            "event_id": "entry:1:ready",
            "payload_json": json.dumps({
                "contract_version": "entry_ready_notification_v1",
                "symbol": "SXT/USDT:USDT",
                "decision_packet": entry_packet(),
            }),
        }
        return [await transport.deliver(event) for _ in range(3)]

    delivered, limited, forbidden = asyncio.run(run())
    assert delivered.disposition is DeliveryDisposition.DELIVERED
    assert limited.disposition is DeliveryDisposition.RATE_LIMITED
    assert limited.retry_after_seconds == 7
    assert forbidden.disposition is DeliveryDisposition.PERMANENT_FAILURE


def test_pre_cutover_entry_ready_is_acknowledged_without_send() -> None:
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    transport = TelegramSignalTransport(
        "token",
        "123",
        cutover_at=200,
        http_transport=httpx.MockTransport(handler),
    )
    event = {
        "event_id": "entry:1:ready",
        "payload_json": json.dumps({
            "contract_version": "entry_ready_notification_v1",
            "symbol": "SXT/USDT:USDT",
            "decision_packet": entry_packet(),
        }),
    }
    result = asyncio.run(transport.deliver(event))
    assert result.disposition is DeliveryDisposition.DELIVERED
    assert calls == []


def test_telegram_transport_requires_ok_true_on_http_200() -> None:
    responses = [
        httpx.Response(200, json={"ok": False, "description": "logical failure"}),
        httpx.Response(200, text="not-json"),
    ]

    async def run() -> list[DeliveryResult]:
        queue = list(responses)

        async def handler(request: httpx.Request) -> httpx.Response:
            del request
            return queue.pop(0)

        transport = TelegramSignalTransport(
            "token",
            "123",
            http_transport=httpx.MockTransport(handler),
        )
        event = {
            "event_id": "entry:1:ready",
            "payload_json": json.dumps({
                "contract_version": "entry_ready_notification_v1",
                "symbol": "SXT/USDT:USDT",
                "decision_packet": entry_packet(),
            }),
        }
        return [await transport.deliver(event), await transport.deliver(event)]

    logical_failure, invalid_json = asyncio.run(run())
    assert logical_failure.disposition is DeliveryDisposition.TRANSIENT_FAILURE
    assert logical_failure.error_code == "INVALID_TELEGRAM_RESPONSE"
    assert invalid_json.disposition is DeliveryDisposition.TRANSIENT_FAILURE
    assert invalid_json.error_code == "INVALID_TELEGRAM_RESPONSE"


def test_telegram_probe_requires_valid_bot_and_chat() -> None:
    async def run(responses):
        queue = list(responses)
        seen = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, str(request.url)))
            return queue.pop(0)

        transport = TelegramSignalTransport(
            "token",
            "123",
            http_transport=httpx.MockTransport(handler),
        )
        return await transport.probe(), seen

    success, success_seen = asyncio.run(run([
        httpx.Response(200, json={"ok": True, "result": {"id": 1}}),
        httpx.Response(200, json={"ok": True, "result": {"id": 123}}),
    ]))
    assert success["reachable"] is True
    assert success["chat_reachable"] is True
    assert len(success_seen) == 2
    assert "getMe" in success_seen[0][1]
    assert "getChat" in success_seen[1][1]

    failed, failed_seen = asyncio.run(run([
        httpx.Response(200, json={"ok": True, "result": {"id": 1}}),
        httpx.Response(400, json={"ok": False, "description": "chat not found"}),
    ]))
    assert failed["reachable"] is False
    assert failed["bot_reachable"] is True
    assert failed["chat_reachable"] is False
    assert len(failed_seen) == 2


def test_entry_ready_message_includes_lifecycle_state() -> None:
    payload = {
        "contract_version": "entry_ready_notification_v1",
        "symbol": "SXT/USDT:USDT",
        "decision_packet": entry_packet(),
    }
    message = TelegramNotifier.build_entry_ready_message(payload)
    assert "Lifecycle" in message
    assert "PRE-TRIGGER" in message
