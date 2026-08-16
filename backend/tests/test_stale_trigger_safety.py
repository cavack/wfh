import asyncio
import time
from unittest.mock import AsyncMock

from waterfallhunter import main


def test_experimental_signal_profile_suppresses_telegram_delivery():
    assert main._signal_alert_allowed({}) is True
    assert main._signal_alert_allowed(
        {"strategy_profile": "experimental_pretrigger_v1"}
    ) is False


def test_stale_trigger_persistence_failure_suppresses_telegram(
    monkeypatch,
):
    symbol = "STALE/USDT:USDT"

    monkeypatch.setattr(
        main.scanner,
        "active_candidates",
        {symbol: {}},
    )
    observe_decision = []
    monkeypatch.setattr(
        main.execution_decision_logger,
        "observe_evaluation",
        lambda *args, **kwargs: (
            observe_decision.append(
                (args, kwargs)
            )
            or True
        ),
    )
    monkeypatch.setattr(
        main.scanner,
        "get_live_reference",
        lambda requested_symbol: (
            0.01,
            time.time(),
        ),
    )

    async def valid_trigger(*args, **kwargs):
        return {
            "is_valid": True,
            "score": 90.0,
            "suggested_status": "TRIGGERED",
            "metrics": {
                "exchange": "test-exchange",
                "mapped_symbol": symbol,
                "orderbook": {},
                "ticker": {},
            },
        }

    monkeypatch.setattr(
        main.validator,
        "cross_check_symbol",
        valid_trigger,
    )
    monkeypatch.setattr(
        main.ai_veto,
        "evaluate_symbol",
        AsyncMock(
            return_value=(
                False,
                {"ai_advice": "OBSERVE"},
            )
        ),
    )
    monkeypatch.setattr(
        main,
        "get_leverage",
        lambda requested_symbol: 1,
    )
    monkeypatch.setattr(
        main.execution_suitability_enricher,
        "for_symbol",
        lambda requested_symbol: {
            "symbol": requested_symbol,
            "status": "UNKNOWN",
            "observational_only": True,
            "trade_eligible": None,
        },
    )
    monkeypatch.setattr(
        main.signal_ledger,
        "persist_trigger",
        lambda *args, **kwargs: None,
    )

    evidence_packets = []
    monkeypatch.setattr(
        main.production_evidence_recorder,
        "record",
        lambda *args, **kwargs: evidence_packets.append(kwargs["result"]) or True,
    )

    send_alert = AsyncMock()
    monkeypatch.setattr(
        main.notifier,
        "send_signal_alert",
        send_alert,
    )

    asyncio.run(
        main.evaluate_candidate(
            symbol,
            {"status": "ARMED"},
        )
    )

    send_alert.assert_not_awaited()
    assert len(observe_decision) == 1
    assert evidence_packets[-1]["metrics"]["production_decision"]["path"] == "PERSISTENCE_REJECTED"
