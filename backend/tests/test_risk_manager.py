import pytest

from waterfallhunter.core.risk_manager import get_leverage, recommend_signal_leverage


def _metrics(*, score=100.0, entry=100.0, stop=102.0, atr_pct=0.5, spread=0.03, slippage=0.03):
    return {
        "score": score,
        "position_setup": {"entry_price": entry, "stop_loss": stop},
        "candle_features": {
            "5m": {"atr_pct": atr_pct},
            "15m": {"atr_pct": atr_pct},
        },
        "microstructure": {
            "spread_pct": spread,
            "slippage_pct": slippage,
        },
    }


def test_legacy_leverage_contract_remains_unchanged_for_replay_compatibility():
    assert get_leverage("BTC/USDT:USDT") == 2
    assert get_leverage("ETH/USDT:USDT") == 2
    assert get_leverage("PEPE/USDT:USDT") == 3


def test_adaptive_leverage_uses_signal_risk_not_symbol_name():
    clean = recommend_signal_leverage(
        _metrics(),
        {"status": "SUITABLE"},
    )
    assert clean == 18

    medium = recommend_signal_leverage(
        _metrics(score=90.0, stop=104.0, atr_pct=1.8, spread=0.12, slippage=0.12),
        {"status": "MARGINAL"},
    )
    assert 4 <= medium < clean


def test_adaptive_leverage_changes_when_risk_changes_for_same_symbol_evidence_shape():
    low_risk = recommend_signal_leverage(_metrics(score=98.0, stop=102.0, atr_pct=0.7), {"status": "SUITABLE"})
    higher_risk = recommend_signal_leverage(_metrics(score=98.0, stop=106.0, atr_pct=2.5, spread=0.18, slippage=0.2), {"status": "MARGINAL"})
    assert 4 <= higher_risk < low_risk <= 18


def test_adaptive_leverage_rejects_when_independent_risk_bound_requires_below_4x():
    with pytest.raises(ValueError, match="below 4x"):
        recommend_signal_leverage(
            _metrics(score=86.0, stop=112.0, atr_pct=6.0, spread=0.28, slippage=0.29),
            {"status": "POOR"},
        )

def test_adaptive_leverage_requires_strict_finite_signal_inputs():
    with pytest.raises(ValueError):
        recommend_signal_leverage({"score": None}, {"status": "SUITABLE"})
