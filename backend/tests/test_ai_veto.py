import asyncio
from pathlib import Path

from waterfallhunter import main
from waterfallhunter.core.ai_veto import AIVetoEngine


def test_ai_veto_engine_has_no_local_model_fallback():
    engine = AIVetoEngine()

    assert not hasattr(engine, "ollama_url")
    assert not hasattr(engine, "ollama_model")
    assert not hasattr(engine, "_get_ollama_opinion")


def test_deterministic_veto_does_not_invoke_gemini(monkeypatch):
    engine = AIVetoEngine()
    invoked = False

    async def opinion(*args, **kwargs):
        nonlocal invoked
        invoked = True
        return {
            "advice": "AVOID",
            "confidence": 99,
            "reasoning": "provider must not be part of deterministic evaluation",
            "provider": "gemini",
        }

    monkeypatch.setattr(engine, "_get_gemini_opinion", opinion)

    vetoed, advisory = engine.evaluate_deterministic(
        "TESTUSDT",
        {"bids": [[1.0, 1.0]], "asks": [[1.1, 1.0]]},
        {"last": 1.0},
    )

    assert vetoed is False
    assert invoked is False
    assert advisory["deterministic_veto"] is False
    assert advisory["ai_observational_only"] is True
    assert advisory["ai_decision_critical"] is False


def test_evaluate_symbol_preserves_the_advisory_provider(monkeypatch):
    engine = AIVetoEngine()

    async def opinion(*args, **kwargs):
        return {
            "advice": "NEUTRAL",
            "confidence": 42,
            "reasoning": "live data is mixed",
            "provider": "gemini",
        }

    monkeypatch.setattr(engine, "_get_gemini_opinion", opinion)
    vetoed, advisory = asyncio.run(
        engine.evaluate_symbol(
            "TESTUSDT",
            {"bids": [[1.0, 1.0]], "asks": [[1.1, 1.0]]},
            {"last": 1.0},
        )
    )

    assert vetoed is False
    assert advisory["ai_provider"] == "gemini"
    assert advisory["ai_advice"] == "NEUTRAL"
    assert advisory["ai_observational_only"] is True
    assert advisory["ai_decision_critical"] is False


def test_deterministic_entry_gate_runs_for_armed_candidate(monkeypatch):
    metrics = {"orderbook": {"bids": [[1.0, 4.0]], "asks": [[1.1, 1.0]]}, "ticker": {"last": 1.0}}

    state, vetoed = main._apply_deterministic_entry_gate("TESTUSDT", "ARMED", metrics)

    assert state == "ARMED"
    assert vetoed is True
    assert metrics["ai_advisory"]["deterministic_veto"] is True


def test_runtime_applies_deterministic_gate_before_canonical_decision() -> None:
    source = Path(main.__file__).read_text(encoding="utf-8")
    body = source.split("async def evaluate_candidate(", maxsplit=1)[1].split(
        "episode_id =", maxsplit=1
    )[0]
    assert body.index("_apply_deterministic_entry_gate(") < body.index(
        "entry_decision = build_entry_decision("
    )
