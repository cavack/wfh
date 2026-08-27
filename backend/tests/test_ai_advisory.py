import asyncio

from waterfallhunter.core.ai_veto import AIVetoEngine


def canonical_metrics() -> dict:
    return {
        "derivatives": {
            "funding_rate": 0.0002,
            "oi_change_1h_pct": 0.8,
            "taker_buy_sell_ratio": 0.72,
            "top_trader_long_short_ratio": 2.1,
        },
        "microstructure": {
            "sell_flow_usdt": 180000.0,
            "buy_flow_usdt": 70000.0,
            "spread_pct": 0.04,
            "slippage_pct": 0.06,
        },
        "cascade_intelligence": {
            "status": "PASS",
            "readiness_points": 8.4,
        },
        "breakdown_confirmation": {"confirmation_exchange_15m": True},
    }


def decision_packet() -> dict:
    return {"decision": "ENTRY_READY", "entry_readiness": 84.0}


def test_canonical_prompt_contains_full_waterfall_evidence() -> None:
    engine = AIVetoEngine()
    prompt = engine._canonical_prompt("SXTUSDT", canonical_metrics(), decision_packet())
    assert "Open interest 1h" in prompt
    assert "Funding" in prompt
    assert "Taker buy/sell" in prompt
    assert "Sell flow" in prompt
    assert "Cascade" in prompt
    assert "Cross-exchange" in prompt
    assert "ENTRY_READY" in prompt


def test_canonical_advisory_failure_cannot_change_decision(monkeypatch) -> None:
    engine = AIVetoEngine()

    async def fail(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(engine, "_request_canonical_advisory", fail)
    packet = decision_packet()
    advisory = asyncio.run(engine.advisory_for_decision("SXTUSDT", canonical_metrics(), packet))
    assert packet["decision"] == "ENTRY_READY"
    assert advisory["ai_advice"] == "UNAVAILABLE"
    assert advisory["ai_provider"] == "none"
