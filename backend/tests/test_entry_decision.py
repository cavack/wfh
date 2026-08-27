from waterfallhunter.core.entry_decision import (
    EntryDecisionPolicy,
    build_entry_decision,
)


def strong_metrics() -> dict:
    return {
        "candle_features": {
            "4h": {"valid": True, "hype_context": True, "lower_high": True, "setup": "FAILED_PULLBACK", "bearish_close": True, "support_broken": False, "volume_acceleration": True},
            "1h": {"valid": True, "lower_high": True, "reclaim": True, "repump": False, "rsi_rollover": True, "bearish_close": True, "volume_acceleration": True},
            "15m": {"valid": True, "lower_high": True, "reclaim": True, "repump": False, "rsi_rollover": True, "bearish_close": True, "volume_acceleration": True},
            "5m": {"valid": True, "lower_high": True, "reclaim": True, "repump": False, "rsi_rollover": True, "bearish_close": True, "volume_acceleration": True},
        },
        "microstructure": {"approved": True, "spoofing_detected": False, "sell_flow_usdt": 180000.0, "buy_flow_usdt": 70000.0, "bid_depth_usdt": 220000.0, "ask_depth_usdt": 180000.0, "spread_pct": 0.04, "slippage_pct": 0.06, "footprint": {"available": True, "aggressive_selling": True}},
        "derivatives": {"available": True, "funding_rate": 0.0002, "funding_percentile": 0.91, "oi_change_1h_pct": 0.7, "taker_buy_sell_ratio": 0.72, "taker_ratio_change_1h": -0.35, "top_trader_long_short_ratio": 2.1},
        "breakdown_confirmation": {"confirmation_exchange_15m": True},
        "price_location": {"below_vwap": True},
        "position_setup": {"status": "READY", "entry_price": 0.1, "stop_loss": 0.103, "take_profit_1": 0.097, "take_profit_2": 0.094, "reward_to_risk": 1.8},
        "applied_leverage": 3,
    }


def decide(metrics: dict, status: str = "PRE-TRIGGER", *, analysis_age: float = 10.0, reference_age: float = 3.0):
    return build_entry_decision(
        metrics,
        status,
        evaluated_at=1_788_000_000,
        analysis_age_seconds=analysis_age,
        reference_age_seconds=reference_age,
    )


def test_strong_fresh_setup_is_entry_ready() -> None:
    packet = decide(strong_metrics())
    assert packet["contract_version"] == "entry_decision_v1"
    assert packet["decision"] == "ENTRY_READY"
    assert packet["entry_readiness"] >= EntryDecisionPolicy().entry_ready_minimum
    assert packet["hard_blocked"] is False
    assert packet["trade_plan"]["entry_price"] == 0.1
    assert packet["reason_codes"] == sorted(packet["reason_codes"])


def test_stale_analysis_is_hard_blocked_no_trade() -> None:
    packet = decide(strong_metrics(), analysis_age=181.0)
    assert packet["decision"] == "NO_TRADE"
    assert packet["hard_blocked"] is True
    assert "STALE_ANALYSIS" in packet["block_reasons"]


def test_moderate_setup_is_forming_instead_of_zeroed_by_one_missing_family() -> None:
    metrics = strong_metrics()
    metrics["breakdown_confirmation"] = {}
    metrics["derivatives"]["funding_percentile"] = 0.55
    metrics["derivatives"]["oi_change_1h_pct"] = -0.1
    metrics["candle_features"]["5m"]["rsi_rollover"] = False
    packet = decide(metrics)
    assert packet["decision"] == "FORMING"
    assert packet["entry_readiness"] >= EntryDecisionPolicy().forming_minimum
    assert "CROSS_EXCHANGE_UNAVAILABLE" in packet["reason_codes"]


def test_extended_move_is_late_even_when_other_evidence_is_strong() -> None:
    metrics = strong_metrics()
    metrics["anti_chase"] = {
        "available": True,
        "cross_timeframe": {"max_post_break_extension_atr": 1.35},
    }
    packet = decide(metrics, status="TRIGGERED")
    assert packet["decision"] == "LATE"
    assert "ANTI_CHASE_HARD_BLOCK" in packet["block_reasons"]


def test_active_buying_and_weak_structure_do_not_promote() -> None:
    metrics = strong_metrics()
    metrics["derivatives"]["taker_buy_sell_ratio"] = 1.55
    metrics["microstructure"]["sell_flow_usdt"] = 40000.0
    metrics["microstructure"]["buy_flow_usdt"] = 160000.0
    metrics["microstructure"]["footprint"]["aggressive_selling"] = False
    for timeframe in ("1h", "15m", "5m"):
        metrics["candle_features"][timeframe]["rsi_rollover"] = False
        metrics["candle_features"][timeframe]["bearish_close"] = False
    packet = decide(metrics, status="WATCH")
    assert packet["decision"] == "NO_TRADE"
    assert packet["entry_readiness"] < EntryDecisionPolicy().forming_minimum
    assert "BUYERS_ACTIVE" in packet["reason_codes"]


def test_deterministic_market_data_veto_hard_blocks_strong_setup() -> None:
    metrics = strong_metrics()
    metrics["ai_advisory"] = {
        "deterministic_veto": True,
        "deterministic_reason": "Bid wall is 4.0x larger than Ask wall.",
        "ai_observational_only": True,
        "ai_decision_critical": False,
    }
    packet = decide(metrics, status="TRIGGERED")
    assert packet["decision"] == "NO_TRADE"
    assert packet["hard_blocked"] is True
    assert "DETERMINISTIC_MARKET_DATA_VETO" in packet["block_reasons"]


def test_triggered_strong_setup_becomes_active_not_a_disappearing_trigger() -> None:
    packet = decide(strong_metrics(), status="TRIGGERED")
    assert packet["decision"] == "ACTIVE"
    assert packet["hard_blocked"] is False
