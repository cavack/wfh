import pytest
from pydantic import ValidationError

from waterfallhunter.core.contracts import ExecutionPlan, SignalDecisionPacket
from test_canonical_contracts import _valid_execution_plan, _valid_signal_packet


def test_signal_decision_rejects_wrong_contract_type_or_version():
    with pytest.raises(ValidationError):
        SignalDecisionPacket(
            **{**_valid_signal_packet(), "contract_type": "execution_plan"}
        )
    with pytest.raises(ValidationError):
        SignalDecisionPacket(
            **{**_valid_signal_packet(), "contract_version": "9.9"}
        )


def test_execution_plan_rejects_wrong_contract_type_or_version():
    with pytest.raises(ValidationError):
        ExecutionPlan(**{**_valid_execution_plan(), "contract_type": "signal_decision"})
    with pytest.raises(ValidationError):
        ExecutionPlan(**{**_valid_execution_plan(), "contract_version": "9.9"})
