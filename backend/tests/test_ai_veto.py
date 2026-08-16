import asyncio

from waterfallhunter.core.ai_veto import AIVetoEngine


def test_ai_veto_engine_has_no_local_model_fallback():
    engine = AIVetoEngine()

    assert not hasattr(engine, "ollama_url")
    assert not hasattr(engine, "ollama_model")
    assert not hasattr(engine, "_get_ollama_opinion")


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
