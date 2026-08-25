from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from waterfallhunter.config import settings
from waterfallhunter.core.notification_delivery import DeliveryDisposition, DeliveryResult
from waterfallhunter.core.notifier import TelegramNotifier


class CapturingActivationNotifier(TelegramNotifier):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sent: list[str] = []

    async def _send_text_result(self, text: str) -> DeliveryResult:
        self.sent.append(text)
        return DeliveryResult(DeliveryDisposition.DELIVERED)


def _configure(
    monkeypatch,
    *,
    delivery_enabled: bool,
    cutover_at: int | None,
) -> None:
    monkeypatch.setattr(settings, "telegram_token", "test-token")
    monkeypatch.setattr(settings, "telegram_chat_id", "123")
    monkeypatch.setattr(
        settings,
        "telegram_signal_delivery_enabled",
        delivery_enabled,
        raising=False,
    )
    monkeypatch.setattr(
        settings,
        "telegram_signal_delivery_cutover_at",
        cutover_at,
        raising=False,
    )


def test_interactive_bot_credentials_do_not_enable_signal_delivery_by_default(
    monkeypatch,
    tmp_path,
) -> None:
    _configure(
        monkeypatch,
        delivery_enabled=False,
        cutover_at=0,
    )
    notifier = TelegramNotifier(
        db_adapter=SimpleNamespace(
            db_path=str(tmp_path / "missing.db")
        )
    )

    assert notifier.enabled is True
    assert notifier.signal_delivery_enabled is False

    async def scenario() -> None:
        await asyncio.wait_for(
            notifier._delivery_loop(),
            timeout=0.1,
        )

    asyncio.run(scenario())


def test_signal_delivery_requires_explicit_cutover_even_when_enabled(
    monkeypatch,
    tmp_path,
) -> None:
    _configure(
        monkeypatch,
        delivery_enabled=True,
        cutover_at=None,
    )
    notifier = TelegramNotifier(
        db_adapter=SimpleNamespace(
            db_path=str(tmp_path / "missing.db")
        )
    )

    assert notifier.enabled is True
    assert notifier.signal_delivery_enabled is False


def test_pre_cutover_strict_event_is_acknowledged_without_network_send(
    monkeypatch,
) -> None:
    _configure(
        monkeypatch,
        delivery_enabled=True,
        cutover_at=200,
    )
    notifier = CapturingActivationNotifier()
    payload = {
        "contract_version": "signal_confirmed_event_v1",
        "signal_id": 1,
        "symbol": "OLD/USDT:USDT",
        "signal_class": "STRICT",
        "strategy_profile": "strict_score_v2",
        "created_at": 100,
    }

    result = asyncio.run(
        notifier.deliver(
            {
                "event_id": "signal:1:confirmed:1",
                "idempotency_key": "signal:1:confirmed:1",
                "event_type": "SIGNAL_CONFIRMED",
                "payload_contract_version": "signal_confirmed_event_v1",
                "payload_json": json.dumps(payload),
                "payload_hash": "unused-in-transport-test",
            }
        )
    )

    assert notifier.signal_delivery_enabled is True
    assert result.disposition is DeliveryDisposition.DELIVERED
    assert notifier.sent == []
