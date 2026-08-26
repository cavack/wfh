from __future__ import annotations

import asyncio

from waterfallhunter.config import settings
from waterfallhunter.core.notifier import TelegramNotifier


class _CountingWorker:
    def __init__(self) -> None:
        self.calls = 0

    async def dispatch_once(self, *, now: int):
        del now
        self.calls += 1
        return None


def test_credentials_alone_do_not_enable_signal_delivery(monkeypatch) -> None:
    monkeypatch.setattr(settings, "telegram_token", "test-token")
    monkeypatch.setattr(settings, "telegram_chat_id", "123")
    monkeypatch.setattr(
        settings,
        "telegram_signal_delivery_enabled",
        False,
        raising=False,
    )

    notifier = TelegramNotifier()

    assert notifier.enabled is True
    assert getattr(notifier, "signal_delivery_enabled", None) is False


def test_delivery_loop_returns_without_claiming_when_signal_delivery_disabled() -> None:
    notifier = TelegramNotifier()
    notifier.enabled = True
    notifier.signal_delivery_enabled = False
    worker = _CountingWorker()
    notifier.delivery_worker = worker

    asyncio.run(
        asyncio.wait_for(
            notifier._delivery_loop(),
            timeout=0.1,
        )
    )

    assert worker.calls == 0
