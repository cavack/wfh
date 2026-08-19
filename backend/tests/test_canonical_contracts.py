from importlib import import_module, util

import pytest
from pydantic import ValidationError


def _contracts():
    spec = util.find_spec("waterfallhunter.core.contracts")
    assert spec is not None, "canonical contracts module must exist"
    return import_module("waterfallhunter.core.contracts")


def _envelope(contract_type: str, version: str = "1.1") -> dict:
    return {
        "contract_type": contract_type,
        "contract_version": version,
        "schema_version": "1",
        "generated_at": 1,
        "producer": "test-suite",
        "model_generation": "legacy",
        "source_revision_status": "VERIFIED_GIT_REVISION",
        "observational_only": True,
    }


def _valid_evidence_packet() -> dict:
    return {
        **_envelope("evidence_quality", "1.0"),
        "coverage_pct": 100.0,
        "completeness_status": "COMPLETE",
        "analysis_observed_at": 1,
        "analysis_age_seconds": 0,
        "reference_observed_at": 1,
        "reference_age_seconds": 0,
        "timestamp_alignment_status": "ALIGNED",
        "candle_coverage": 100.0,
        "derivatives_coverage": 100.0,
        "microstructure_coverage": 100.0,
        "execution_coverage": 100.0,
        "cross_exchange_coverage": 100.0,
        "missing_sources": [],
        "stale_sources": [],
        "uncertainty_reasons": [],
    }


def _valid_signal_packet() -> dict:
    return {
        **_envelope("signal_decision"),
        "decision_id": "decision-1",
        "signal_id": "signal-1",
        "symbol": "BTC/USDT:USDT",
        "signal_class": "STRICT",
        "strategy_profile": "strict_v1",
        "lifecycle_state": "TRIGGERED",
        "decision_status": {"primary": "CONFIRMED"},
        "score_version": "legacy_evidence_score_v2",
        "decision_contract_hash": "a" * 64,
        "analysis_observed_at": 1,
        "reference_observed_at": 1,
        "eligibility_gates": {"fresh": True, "execution": True},
        "evidence_quality": _valid_evidence_packet(),
        "predictive_evidence_score": None,
        "final_signal_score": 88.0,
        "calibrated_probability": None,
        "anti_chase_risk": "NOT_EVALUATED",
        "execution_risk": "SUITABLE",
        "execution_plan_id": "plan-1",
        "reason_codes": ["STRICT_GATES_PASS"],
        "execution_mode": "PAPER_ONLY",
    }


def _valid_execution_plan() -> dict:
    return {
        **_envelope("execution_plan"),
        "execution_plan_id": "plan-1",
        "signal_id": "signal-1",
        "venue": "LBANK",
        "contract_identity": "BTCUSDT-PERP",
        "margin_mode": "ISOLATED",
        "cross_margin_allowed": False,
        "auto_add_margin": False,
        "entry_primary": 100.0,
        "entry_secondary": None,
        "tp1": 95.0,
        "tp2": 90.0,
        "stop_loss": 103.0,
        "raw_safe_leverage": 1.8,
        "system_leverage": 3.0,
        "risk_label": "VERY_HIGH_RISK",
        "spread": 0.0008,
        "entry_slippage": 0.0011,
        "exit_slippage": 0.0013,
        "depth": 250000.0,
        "gross_tp1_pnl": 0.15,
        "net_tp1_pnl": 0.14,
        "gross_tp2_pnl": 0.30,
        "net_tp2_pnl": 0.29,
        "gross_sl_pnl": -0.09,
        "net_sl_pnl": -0.10,
        "fees_model_version": "fees_v1",
        "funding_model_version": "funding_v1",
        "levels_available": True,
        "unavailable_reason": None,
    }


def _valid_position_state() -> dict:
    return {
        **_envelope("position_state", "1.0"),
        "position_id": "position-1",
        "signal_id": "signal-1",
        "execution_state": "OPEN",
        "thesis_state": "CAUTION",
        "original_execution_plan_id": "plan-1",
        "margin_mode": "ISOLATED",
        "isolated_margin_initial": 20.0,
        "isolated_margin_current": 20.0,
        "notional": 120.0,
        "entry_price": 100.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": -2.0,
        "fees": 0.1,
        "funding": 0.0,
        "current_sl": 103.0,
        "current_tp1": 95.0,
        "current_tp2": 90.0,
        "latest_amendment_id": None,
        "opened_at": 1,
        "last_reassessed_at": 1,
        "closed_at": None,
    }


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


def test_signal_decision_packet_keeps_probability_unavailable_explicit():
    contracts = _contracts()
    packet = contracts.SignalDecisionPacket(**_valid_signal_packet())
    assert packet.calibrated_probability is None
    assert packet.execution_mode.value == "PAPER_ONLY"
    assert packet.evidence_quality.coverage_pct == 100.0


def test_signal_decision_packet_rejects_fake_probability_and_bad_hash():
    contracts = _contracts()
    with pytest.raises(ValidationError):
        contracts.SignalDecisionPacket(
            **{**_valid_signal_packet(), "calibrated_probability": 1.01}
        )
    with pytest.raises(ValidationError):
        contracts.SignalDecisionPacket(
            **{**_valid_signal_packet(), "decision_contract_hash": "not-a-sha256"}
        )


def test_execution_plan_is_lbank_isolated_only_and_preserves_raw_leverage():
    contracts = _contracts()
    plan = contracts.ExecutionPlan(**_valid_execution_plan())
    assert plan.venue == "LBANK"
    assert plan.margin_mode.value == "ISOLATED"
    assert plan.cross_margin_allowed is False
    assert plan.auto_add_margin is False
    assert plan.raw_safe_leverage == 1.8
    assert plan.system_leverage == 3.0


def test_execution_plan_rejects_cross_margin_and_out_of_range_system_leverage():
    contracts = _contracts()
    with pytest.raises(ValidationError):
        contracts.ExecutionPlan(
            **{**_valid_execution_plan(), "cross_margin_allowed": True}
        )
    with pytest.raises(ValidationError):
        contracts.ExecutionPlan(**{**_valid_execution_plan(), "system_leverage": 21})


def test_execution_plan_requires_reason_when_levels_are_unavailable():
    contracts = _contracts()
    unavailable = {
        **_valid_execution_plan(),
        "levels_available": False,
        "entry_primary": None,
        "tp1": None,
        "tp2": None,
        "stop_loss": None,
        "system_leverage": None,
        "unavailable_reason": None,
    }
    with pytest.raises(ValidationError):
        contracts.ExecutionPlan(**unavailable)


def test_position_state_keeps_execution_and_thesis_states_separate():
    contracts = _contracts()
    state = contracts.PositionState(**_valid_position_state())
    assert state.execution_state.value == "OPEN"
    assert state.thesis_state.value == "CAUTION"
    assert state.margin_mode.value == "ISOLATED"
    assert not hasattr(state, "lifecycle_state")


def test_position_state_rejects_non_isolated_margin():
    contracts = _contracts()
    with pytest.raises(ValidationError):
        contracts.PositionState(**{**_valid_position_state(), "margin_mode": "CROSS"})


def test_position_amendment_is_frozen_append_only_vocabulary():
    contracts = _contracts()
    amendment = contracts.PositionAmendment(
        **_envelope("position_amendment", "1.0"),
        amendment_id="amendment-1",
        position_id="position-1",
        action="TIGHTEN_RISK",
        reason_codes=["BTC_REGIME_WEAKENED"],
        created_at=2,
        proposed_sl=101.0,
        proposed_tp1=None,
        proposed_tp2=None,
        source_context_version="market_context_v1",
    )
    with pytest.raises(ValidationError):
        amendment.action = "CLOSE_EARLY"


def test_notification_event_requires_sha256_material_hash():
    contracts = _contracts()
    with pytest.raises(ValidationError):
        contracts.NotificationEvent(
            **_envelope("notification_event", "1.0"),
            event_id="event-1",
            event_type="SIGNAL_CONFIRMED",
            aggregate_type="signal",
            aggregate_id="signal-1",
            symbol="BTC/USDT:USDT",
            signal_class="STRICT",
            lifecycle_state="TRIGGERED",
            decision_status={"primary": "CONFIRMED"},
            material_state_hash="not-a-hash",
            idempotency_key="signal-confirmed:signal-1",
            priority=100,
            payload_contract_version="1",
            payload={},
            created_at=2,
        )


def test_notification_event_contains_no_delivery_or_secret_fields():
    contracts = _contracts()
    event = contracts.NotificationEvent(
        **_envelope("notification_event", "1.0"),
        event_id="event-1",
        event_type="SIGNAL_CONFIRMED",
        aggregate_type="signal",
        aggregate_id="signal-1",
        symbol="BTC/USDT:USDT",
        signal_class="STRICT",
        lifecycle_state="TRIGGERED",
        decision_status={"primary": "CONFIRMED"},
        material_state_hash="b" * 64,
        idempotency_key="signal-confirmed:signal-1",
        priority=100,
        payload_contract_version="1",
        payload={},
        created_at=2,
    )
    dumped = event.model_dump(mode="json")
    assert "telegram_message_id" not in dumped
    assert "delivery_state" not in dumped
    assert "token" not in dumped
