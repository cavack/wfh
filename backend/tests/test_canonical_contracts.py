from importlib import import_module, util

import pytest
from pydantic import ValidationError


def _contracts():
    spec = util.find_spec("waterfallhunter.core.contracts")
    assert spec is not None, "canonical contracts module must exist"
    return import_module("waterfallhunter.core.contracts")


def test_signal_class_is_only_strict_or_experimental():
    contracts = _contracts()
    assert {item.value for item in contracts.SignalClass} == {"STRICT", "EXPERIMENTAL"}


def test_decision_status_canonicalizes_qualifier_order_and_duplicates():
    contracts = _contracts()
    status = contracts.DecisionStatus(
        primary="CONFIRMED",
        qualifiers=["STALE_REFERENCE", "AI_CAUTION", "AI_CAUTION"],
    )
    assert status.qualifiers == (
        contracts.DecisionQualifier.AI_CAUTION,
        contracts.DecisionQualifier.STALE_REFERENCE,
    )


def test_unknown_decision_primary_is_rejected():
    contracts = _contracts()
    with pytest.raises(ValidationError):
        contracts.DecisionStatus(primary="MAYBE")
