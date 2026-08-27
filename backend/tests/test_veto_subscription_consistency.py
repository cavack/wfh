from __future__ import annotations

import asyncio
import time

from waterfallhunter import main
from waterfallhunter.core.signal_metadata import STRICT_STRATEGY_PROFILE


def test_failed_veto_state_persistence_keeps_websocket_subscription(monkeypatch) -> None:
    symbol = "VETO/USDT:USDT"
    monkeypatch.setattr(main.scanner, "active_candidates", {symbol: {}})
    monkeypatch.setattr(
        main.execution_decision_logger,
        "observe_evaluation",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        main.scanner,
        "get_live_reference",
        lambda requested_symbol: (0.01, int(time.time()) - 1),
    )

    async def valid_trigger(*args, **kwargs):
        return {
            "is_valid": True,
            "score": 91.0,
            "suggested_status": "TRIGGERED",
            "metrics": {
                "exchange": "binance",
                "mapped_symbol": symbol,
                "orderbook": {},
                "ticker": {},
                "strategy_profile": STRICT_STRATEGY_PROFILE,
                "score_version": "score_v2",
            },
        }

    monkeypatch.setattr(main.validator, "cross_check_symbol", valid_trigger)
    monkeypatch.setattr(
        main.ai_veto,
        "evaluate_deterministic",
        lambda *args, **kwargs: (
            True,
            {
                "deterministic_veto": True,
                "deterministic_reason": "unsafe market data",
            },
        ),
    )
    monkeypatch.setattr(main.db, "update_candidate_state", lambda *args: False)
    monkeypatch.setattr(
        main.production_evidence_recorder,
        "record",
        lambda *args, **kwargs: True,
    )
    unsubscribed = []
    monkeypatch.setattr(
        main.validator.ws_manager,
        "unsubscribe",
        lambda *args: unsubscribed.append(args),
    )

    asyncio.run(
        main.evaluate_candidate(
            symbol,
            {"status": "ARMED", "lifecycle_id": 1, "scan_eligible": True},
        )
    )

    assert unsubscribed == []
