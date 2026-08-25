from __future__ import annotations

from types import SimpleNamespace

from waterfallhunter.core import notifier as notifier_module
from waterfallhunter.core.notifier import TelegramNotifier


def test_telegram_credentials_do_not_activate_signal_delivery_without_explicit_flag(
    monkeypatch,
    tmp_path,
) -> None:
    """Interactive credentials alone must never authorize STRICT signal sends."""

    monkeypatch.setattr(
        notifier_module,
        "settings",
        SimpleNamespace(
            telegram_token="test-token",
            telegram_chat_id="123",
            telegram_signal_delivery_enabled=False,
        ),
    )

    notifier = TelegramNotifier(
        db_adapter=SimpleNamespace(
            db_path=str(tmp_path / "telegram-activation.db"),
        )
    )

    assert notifier.enabled is True
    assert notifier.delivery_worker is None
