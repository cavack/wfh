from waterfallhunter.core.final_ranking import FinalRanking


def _candidate(*, status="ARMED", score=80.0, execution="SUITABLE", age=10.0, probability=None):
    position = {} if probability is None else {"tp_24h_probability": probability}
    return {
        "status": status,
        "score": score,
        "age_seconds": age,
        "execution_suitability": {"status": execution},
        "metrics": {
            "strategy_stages": {"hype": True, "damage": True, "setup": True, "trigger": status == "TRIGGERED"},
            "relative_weakness_features": {
                "available": True,
                "timeframes": {
                    "4h": {"relative_return_6bars_pct": -5.0},
                    "1h": {"relative_return_6bars_pct": -4.0},
                    "15m": {"relative_return_6bars_pct": -2.0},
                    "5m": {"relative_return_6bars_pct": -1.0},
                },
            },
            "position_setup": position,
        },
    }


def test_ranking_is_observational_and_never_claims_eligibility_or_anti_chase_veto():
    packet = FinalRanking.for_candidate("TEST", _candidate())

    assert packet["observational_only"] is True
    assert packet["trade_eligible"] is None
    assert packet["anti_chase"]["status"] == "NOT_EVALUATED"
    assert packet["anti_chase"]["veto"] is None


def test_missing_empirical_probability_reduces_confidence_without_zero_filling():
    missing = FinalRanking.for_candidate("MISSING", _candidate())
    available = FinalRanking.for_candidate("AVAILABLE", _candidate(probability=0.7))

    assert missing["components"]["empirical_probability"]["available"] is False
    assert missing["components"]["empirical_probability"]["points"] is None
    assert missing["confidence"] == 0.9
    assert available["confidence"] == 1.0


def test_ranking_rewards_readiness_execution_and_complete_evidence():
    result = FinalRanking.rank({
        "WATCH": _candidate(status="WATCH", score=60.0, execution="MARGINAL", age=20.0),
        "READY": _candidate(status="TRIGGERED", score=85.0, execution="SUITABLE", age=5.0, probability=0.7),
    })

    assert result["top"][0]["symbol"] == "READY"
    assert result["top"][0]["rank"] == 1
    assert result["observational_only"] is True


def test_unknown_execution_is_missing_not_suitable_or_zero():
    packet = FinalRanking.for_candidate("UNKNOWN", _candidate(execution="UNKNOWN"))

    assert packet["components"]["execution_quality"]["available"] is False
    assert "execution_quality" in packet["missing_components"]
