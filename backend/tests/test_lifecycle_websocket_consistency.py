from __future__ import annotations

import asyncio

from waterfallhunter import main
from waterfallhunter.core.lifecycle_v2_shadow import LifecycleV2State


def _prepare_invalid_evaluation(monkeypatch, *, symbol: str, result: dict, persist_state: bool):
    monkeypatch.setattr(main.scanner, "active_candidates", {symbol: {}})
    monkeypatch.setattr(
        main.scanner,
        "get_live_reference",
        lambda requested_symbol: (0.01, 1_700_000_000.0),
    )
    monkeypatch.setattr(
        main.execution_decision_logger,
        "observe_evaluation",
        lambda *args, **kwargs: None,
    )

    async def cross_check_symbol(*args, **kwargs):
        return result

    monkeypatch.setattr(main.validator, "cross_check_symbol", cross_check_symbol)
    monkeypatch.setattr(
        main.production_evidence_recorder,
        "record",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(main, "_store_live_metrics", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        main.lifecycle_v2_shadow_store,
        "latest_state",
        lambda **kwargs: LifecycleV2State.WATCH,
    )
    monkeypatch.setattr(
        main.lifecycle_v2_shadow_store,
        "append_comparison",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        main.db,
        "update_candidate_state",
        lambda *args, **kwargs: persist_state,
    )

    unsubscribed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main.validator.ws_manager,
        "unsubscribe",
        lambda exchange, mapped_symbol: unsubscribed.append((exchange, mapped_symbol)),
    )
    return unsubscribed


def test_failed_observation_downgrade_keeps_armed_websocket_subscription(monkeypatch) -> None:
    symbol = "DRIFTFAIL/USDT:USDT"
    mapped_symbol = "DRIFTFAIL/USDT:USDT"
    result = {
        "is_valid": False,
        "score": None,
        "suggested_status": "REJECTED",
        "observation_status": "WATCH",
        "observation_score": 35.0,
        "metrics": {
            "exchange": "binance",
            "mapped_symbol": mapped_symbol,
            "analysis_reason": "observational downgrade",
        },
    }
    unsubscribed = _prepare_invalid_evaluation(
        monkeypatch,
        symbol=symbol,
        result=result,
        persist_state=False,
    )

    asyncio.run(
        main.evaluate_candidate(
            symbol,
            {
                "status": "ARMED",
                "lifecycle_id": 1,
                "scan_eligible": True,
                "quote_volume": 3_000_000.0,
                "last_price": 0.01,
            },
        )
    )

    assert unsubscribed == []


def test_successful_unavailable_downgrade_unsubscribes_armed_websocket(monkeypatch) -> None:
    symbol = "DRIFTPASS/USDT:USDT"
    mapped_symbol = "DRIFTPASS/USDT:USDT"
    result = {
        "is_valid": False,
        "score": None,
        "suggested_status": "REJECTED",
        "metrics": {
            "exchange": "binance",
            "mapped_symbol": mapped_symbol,
            "error": "live validation unavailable",
        },
    }
    unsubscribed = _prepare_invalid_evaluation(
        monkeypatch,
        symbol=symbol,
        result=result,
        persist_state=True,
    )

    asyncio.run(
        main.evaluate_candidate(
            symbol,
            {
                "status": "ARMED",
                "lifecycle_id": 1,
                "scan_eligible": True,
                "quote_volume": 3_000_000.0,
                "last_price": 0.01,
            },
        )
    )

    assert unsubscribed == [("binance", mapped_symbol)]
