from waterfallhunter.core.final_ranking import FinalRanking


EVALUATION_TIME = 1_700_000_000.0


def _candidate(
    *,
    status="ARMED",
    score=80.0,
    execution="SUITABLE",
    analysis_age=10.0,
    reference_age=5.0,
):
    return {
        "status": status,
        "score": score,
        "analysis_observed_at": EVALUATION_TIME - analysis_age,
        "reference_observed_at": EVALUATION_TIME - reference_age,
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
        },
    }


def test_ranking_is_observational_and_never_claims_eligibility_or_anti_chase_veto():
    packet = FinalRanking.for_candidate(
        "TEST",
        _candidate(),
        evaluation_time=EVALUATION_TIME,
    )

    assert packet["observational_only"] is True
    assert packet["trade_eligible"] is None
    assert packet["anti_chase"]["status"] == "NOT_EVALUATED"
    assert packet["anti_chase"]["veto"] is None


def test_analysis_and_reference_freshness_are_independent_and_never_zero_filled():
    missing_reference = _candidate()
    missing_reference["reference_observed_at"] = None
    packet = FinalRanking.for_candidate(
        "MISSING_REFERENCE",
        missing_reference,
        evaluation_time=EVALUATION_TIME,
    )

    assert packet["components"]["analysis_freshness"]["available"] is True
    assert packet["components"]["reference_freshness"]["available"] is False
    assert packet["components"]["reference_freshness"]["points"] is None
    assert packet["confidence"] < 1.0


def test_ranking_rewards_readiness_execution_and_complete_evidence():
    result = FinalRanking.rank({
        "WATCH": _candidate(status="WATCH", score=60.0, execution="MARGINAL", analysis_age=20.0),
        "READY": _candidate(status="TRIGGERED", score=85.0, execution="SUITABLE", analysis_age=5.0),
    }, evaluation_time=EVALUATION_TIME)

    assert result["top"][0]["symbol"] == "READY"
    assert result["top"][0]["rank"] == 1
    assert result["observational_only"] is True


def test_unknown_execution_is_missing_not_suitable_or_zero():
    packet = FinalRanking.for_candidate(
        "UNKNOWN",
        _candidate(execution="UNKNOWN"),
        evaluation_time=EVALUATION_TIME,
    )

    assert packet["components"]["execution_quality"]["available"] is False
    assert "execution_quality" in packet["missing_components"]


def test_ranking_rejects_hidden_or_invalid_evaluation_clock():
    import pytest

    with pytest.raises(ValueError, match="evaluation_time"):
        FinalRanking.for_candidate("TEST", _candidate(), evaluation_time=float("nan"))
