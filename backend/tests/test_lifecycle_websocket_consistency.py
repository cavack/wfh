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
    # Synthetic symbols in this unit test do not exist in lbank_catalog.
    # Bypass the independent canonical lifecycle CAS so this fixture continues
    # to isolate websocket unsubscribe behavior.
    monkeypatch.setattr(
        main.entry_decision_store,
        "latest_for_symbol",
        lambda _symbol: None,
    )
    monkeypatch.setattr(
        main.entry_decision_store,
        "append_if_changed",
        lambda *_args, **_kwargs: None,
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


def test_armed_source_failover_retires_previous_websocket_subscription(monkeypatch) -> None:
    symbol = "FAILOVER/USDT:USDT"
    old_symbol = "OLD/USDT:USDT"
    new_symbol = "NEW/USDT:USDT"
    monkeypatch.setattr(
        main.scanner,
        "active_candidates",
        {symbol: {"metrics": {"exchange": "binance", "mapped_symbol": old_symbol}}},
    )
    monkeypatch.setattr(
        main.scanner,
        "get_live_reference",
        lambda requested_symbol: (0.01, __import__("time").time()),
    )
    monkeypatch.setattr(main.execution_decision_logger, "observe_evaluation", lambda *args, **kwargs: None)

    async def cross_check_symbol(*args, **kwargs):
        return {
            "is_valid": True,
            "score": 80.0,
            "suggested_status": "ARMED",
            "metrics": {"exchange": "bybit", "mapped_symbol": new_symbol},
        }

    monkeypatch.setattr(main.validator, "cross_check_symbol", cross_check_symbol)
    monkeypatch.setattr(main, "_apply_deterministic_entry_gate", lambda _s, state, _m: (state, False))
    monkeypatch.setattr(main, "build_signal_leverage_advisory", lambda metrics, execution_suitability=None: {
        "policy_version": "adaptive_signal_leverage_v1",
        "minimum": 4, "maximum": 18, "symbol_agnostic": True,
        "signal_only": True, "advisory_only": True,
        "status": "UNAVAILABLE", "leverage": None, "reason": "test unavailable",
    })
    monkeypatch.setattr(main.entry_decision_store, "latest_for_symbol", lambda _symbol: None)
    monkeypatch.setattr(main.entry_decision_store, "append_if_changed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main.production_evidence_recorder, "record", lambda *args, **kwargs: True)
    monkeypatch.setattr(main.lifecycle_v2_shadow_store, "latest_state", lambda **kwargs: LifecycleV2State.WATCH)
    monkeypatch.setattr(main.lifecycle_v2_shadow_store, "append_comparison", lambda **kwargs: True)

    subscribed: list[tuple[str, str]] = []
    unsubscribed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main.validator.ws_manager,
        "subscribe",
        lambda exchange, mapped_symbol: subscribed.append((exchange, mapped_symbol)),
    )
    monkeypatch.setattr(
        main.validator.ws_manager,
        "unsubscribe",
        lambda exchange, mapped_symbol: unsubscribed.append((exchange, mapped_symbol)),
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

    assert unsubscribed == [("binance", old_symbol)]
    assert subscribed == [("bybit", new_symbol)]


def test_pretrigger_observation_starts_websocket_evidence_subscription(monkeypatch) -> None:
    symbol = "PREWS/USDT:USDT"
    mapped_symbol = "PREWS/USDT:USDT"
    result = {
        "is_valid": False,
        "score": None,
        "suggested_status": "REJECTED",
        "observation_status": "PRE-TRIGGER",
        "observation_score": 58.0,
        "metrics": {
            "exchange": "binance",
            "mapped_symbol": mapped_symbol,
            "analysis_reason": "strict gates incomplete",
        },
    }
    unsubscribed = _prepare_invalid_evaluation(
        monkeypatch, symbol=symbol, result=result, persist_state=True
    )
    full_subscribed: list[tuple[str, str]] = []
    liquidation_subscribed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main.validator.ws_manager,
        "subscribe",
        lambda exchange, mapped: full_subscribed.append((exchange, mapped)),
    )
    monkeypatch.setattr(
        main.validator.ws_manager,
        "subscribe_liquidations",
        lambda exchange, mapped: liquidation_subscribed.append((exchange, mapped)),
    )

    asyncio.run(
        main.evaluate_candidate(
            symbol,
            {
                "status": "WATCH", "lifecycle_id": 1, "scan_eligible": True,
                "quote_volume": 3_000_000.0, "last_price": 0.01,
            },
        )
    )

    assert full_subscribed == []
    assert liquidation_subscribed == [("binance", mapped_symbol)]
    assert unsubscribed == []


def test_pretrigger_source_failover_retires_previous_websocket_subscription(monkeypatch) -> None:
    symbol = "PREFLOW/USDT:USDT"
    old_symbol = "OLDPREFLOW/USDT:USDT"
    new_symbol = "NEWPREFLOW/USDT:USDT"
    result = {
        "is_valid": False,
        "score": None,
        "suggested_status": "REJECTED",
        "observation_status": "PRE-TRIGGER",
        "observation_score": 59.0,
        "metrics": {
            "exchange": "bybit",
            "mapped_symbol": new_symbol,
            "analysis_reason": "strict gates incomplete",
        },
    }
    unsubscribed = _prepare_invalid_evaluation(
        monkeypatch, symbol=symbol, result=result, persist_state=True
    )
    monkeypatch.setattr(
        main.scanner,
        "active_candidates",
        {symbol: {"metrics": {"exchange": "binance", "mapped_symbol": old_symbol}}},
    )
    full_subscribed: list[tuple[str, str]] = []
    liquidation_subscribed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main.validator.ws_manager,
        "subscribe",
        lambda exchange, mapped: full_subscribed.append((exchange, mapped)),
    )
    monkeypatch.setattr(
        main.validator.ws_manager,
        "subscribe_liquidations",
        lambda exchange, mapped: liquidation_subscribed.append((exchange, mapped)),
    )

    asyncio.run(
        main.evaluate_candidate(
            symbol,
            {
                "status": "PRE-TRIGGER", "lifecycle_id": 1, "scan_eligible": True,
                "quote_volume": 3_000_000.0, "last_price": 0.01,
            },
        )
    )

    assert unsubscribed == [("binance", old_symbol)]
    assert full_subscribed == []
    assert liquidation_subscribed == [("bybit", new_symbol)]


def test_pretrigger_downgrade_to_watch_retires_websocket_subscription(monkeypatch) -> None:
    symbol = "PREWATCH/USDT:USDT"
    mapped_symbol = "PREWATCH/USDT:USDT"
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
        monkeypatch, symbol=symbol, result=result, persist_state=True
    )
    monkeypatch.setattr(
        main.scanner,
        "active_candidates",
        {symbol: {"metrics": {"exchange": "binance", "mapped_symbol": mapped_symbol}}},
    )
    subscribed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main.validator.ws_manager,
        "subscribe",
        lambda exchange, mapped: subscribed.append((exchange, mapped)),
    )

    asyncio.run(
        main.evaluate_candidate(
            symbol,
            {
                "status": "PRE-TRIGGER", "lifecycle_id": 1, "scan_eligible": True,
                "quote_volume": 3_000_000.0, "last_price": 0.01,
            },
        )
    )

    assert subscribed == []
    assert unsubscribed == [("binance", mapped_symbol)]
