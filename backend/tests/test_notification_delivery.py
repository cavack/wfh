from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from schema_test_support import migrate_test_database
from signal_metadata_test_support import strict_signal_metadata
from waterfallhunter.core.db import DBAdapter
from waterfallhunter.core.lbank_signal_ledger import LBankSignalLedger
from waterfallhunter.core.notification_delivery import (
    DeliveryDisposition,
    DeliveryResult,
    DurableNotificationWorker,
    notification_delivery_health,
)


class FakeTransport:
    def __init__(self, *results: DeliveryResult | Exception):
        self.results = list(results)
        self.calls: list[dict] = []

    async def deliver(self, event: dict) -> DeliveryResult:
        self.calls.append(event)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _database(path: Path) -> str:
    db_path = str(migrate_test_database(path))
    db = DBAdapter(db_path=db_path)
    symbol = "NOTICE/USDT:USDT"
    db.update_candidates(
        {
            symbol: {
                "last_price": 1.0,
                "quote_volume": 3_000_000.0,
                "is_meme": False,
                "scan_eligible": True,
            }
        }
    )
    assert db.update_candidate_state(symbol, "ARMED")
    signal_id = LBankSignalLedger(db_path).persist_trigger(
        symbol,
        "ARMED",
        score=90.0,
        trigger_metrics={
            "position_setup": {
                "entry_price": 1.0,
                "stop_loss": 1.05,
                "take_profit_1": 0.95,
                "take_profit_2": 0.90,
            }
        },
        execution_suitability={"status": "SUITABLE", "failed_checks": []},
        metadata=strict_signal_metadata(
            analysis_observed_at=90,
            reference_observed_at=90,
        ),
        triggered_at=100,
        metadata_created_at=100,
    )
    assert signal_id == 1
    return db_path


def _state(db_path: str) -> tuple:
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT status, attempt_count, available_at, lease_owner, "
            "lease_expires_at, last_error_code FROM domain_outbox_events"
        ).fetchone()


def test_success_is_delivered_once_with_material_idempotency_key(tmp_path: Path) -> None:
    db_path = _database(tmp_path / "delivered.db")
    transport = FakeTransport(DeliveryResult(DeliveryDisposition.DELIVERED))
    worker = DurableNotificationWorker(
        db_path,
        transport,
        worker_id="worker-a",
        jitter=lambda: 0.0,
    )

    outcome = asyncio.run(worker.dispatch_once(now=200))

    assert outcome is not None and outcome.state == "DELIVERED"
    assert _state(db_path) == ("DELIVERED", 1, 200, None, None, None)
    assert transport.calls[0]["event_id"] == transport.calls[0]["idempotency_key"]
    assert asyncio.run(worker.dispatch_once(now=201)) is None


def test_rate_limit_and_timeout_use_bounded_retry_then_dead_letter(tmp_path: Path) -> None:
    db_path = _database(tmp_path / "retry.db")
    transport = FakeTransport(
        DeliveryResult(
            DeliveryDisposition.RATE_LIMITED,
            error_code="HTTP 429",
            retry_after_seconds=7,
        ),
        TimeoutError(),
    )
    worker = DurableNotificationWorker(
        db_path,
        transport,
        worker_id="worker-a",
        max_attempts=2,
        jitter=lambda: 0.0,
    )

    first = asyncio.run(worker.dispatch_once(now=200))
    assert first is not None
    assert first.state == "RETRY_WAIT"
    assert first.next_available_at == 207
    assert _state(db_path)[5] == "HTTP_429"
    assert asyncio.run(worker.dispatch_once(now=206)) is None

    second = asyncio.run(worker.dispatch_once(now=207))
    assert second is not None and second.state == "DEAD_LETTER"
    assert second.error_code == "TRANSPORT_TIMEOUT"
    assert _state(db_path)[0:2] == ("DEAD_LETTER", 2)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM lbank_signal_ledger").fetchone() == (1,)


def test_lease_prevents_double_claim_and_expiry_becomes_delivery_uncertain(tmp_path: Path) -> None:
    db_path = _database(tmp_path / "uncertain.db")
    transport = FakeTransport(DeliveryResult(DeliveryDisposition.DELIVERED))
    first = DurableNotificationWorker(
        db_path,
        transport,
        worker_id="worker-a",
        lease_seconds=10,
    )
    second = DurableNotificationWorker(
        db_path,
        transport,
        worker_id="worker-b",
        lease_seconds=10,
    )

    claimed = first.claim_next(now=200)
    assert claimed is not None
    assert second.claim_next(now=201) is None
    assert second.recover_expired_leases(now=210) == 1
    assert _state(db_path)[0] == "DELIVERY_UNCERTAIN"

    health = notification_delivery_health(db_path, now=500)
    assert health["healthy"] is False
    assert "NOTIFICATION_DELIVERY_UNCERTAIN_PRESENT" in health["alerts"]
    assert second.claim_next(now=500) is None


def test_pending_queue_lag_has_an_operator_alert(tmp_path: Path) -> None:
    db_path = _database(tmp_path / "lag.db")

    health = notification_delivery_health(db_path, now=401)

    assert health["oldest_pending_age_seconds"] == 301
    assert health["alerts"] == ["NOTIFICATION_QUEUE_LAG_HIGH"]
