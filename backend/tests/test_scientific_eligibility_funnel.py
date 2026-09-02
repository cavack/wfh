import importlib.util
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "funnel",
    Path(__file__).parents[2] / "scripts/research/build_scientific_eligibility_funnel.py",
)
funnel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(funnel)


def _row(**kwargs):
    row = {
        "decision": {"value": "ENTRY_READY", "reason": None},
        "code_sha": {"value": "a" * 64, "reason": None},
        "decision_contract_sha": {"value": "b" * 64, "reason": None},
        "decision_at": {"value": 100, "reason": None},
        "evidence_as_of": {"value": 100, "reason": None},
        "trade_plan": {
            "value": {
                "status": "READY",
                "entry_price": 100,
                "stop_loss": 90,
                "take_profit_1": 110,
                "take_profit_2": 120,
            },
            "reason": None,
        },
        "outcome": {
            "status": "COMPLETE",
            "observed_candles": {"value": 288},
            "expected_candles": {"value": 288},
            "gross_r": {"value": 1.0},
            "costs": {
                "fees": {"value": 0.1},
                "slippage": {"value": 0.1},
                "funding": {"value": 0.01},
                "net_r": {"value": 0.79},
            },
        },
    }
    row.update(kwargs)
    return row


def test_signal_id_or_timestamp_does_not_create_scientific_outcome_link():
    result = funnel.build([_row(signal_id=7, observed_at={"value": 100})], source="fixture")
    assert result["outcome_linkable_count"] == 0
    assert result["scientifically_evaluable_count"] == 0
    assert result["linkage_assessment"]["status"] == "INVALID_FOR_SCIENCE"


def test_explicit_decision_identity_allows_linkage():
    row = _row(
        decision_event_id=11,
        candidate_evaluation_id=11,
        outcome={"status": "COMPLETE", "decision_event_id": 11,
                 "observed_candles": {"value": 288}, "expected_candles": {"value": 288},
                 "gross_r": {"value": 1.0},
                 "costs": {"fees": {"value": 0.1}, "slippage": {"value": 0.1},
                           "funding": {"value": 0.01}, "net_r": {"value": 0.79}}},
    )
    result = funnel.build([row], source="fixture")
    assert result["outcome_linkable_count"] == 1
    assert result["scientifically_evaluable_count"] == 1
