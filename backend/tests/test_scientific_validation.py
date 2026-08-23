from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from waterfallhunter.core.scientific_validation import (
    DAY_SECONDS,
    ScientificValidationPolicy,
    ScientificValidationRequest,
    validate_strict_scientific_evidence,
)


def _request(*, days: int = 70, row_count: int = 180) -> ScientificValidationRequest:
    start = 1_800_000_000
    interval = max(1, days * DAY_SECONDS // (row_count - 1))
    rows = []
    for index in range(row_count):
        triggered_at = start + index * interval
        target = index % 2 == 0
        rows.append(
            {
                "signal_id": f"strict-{index:04d}",
                "signal_class": "STRICT",
                "strategy_profile": "strict_score_v2",
                "score_version": "score_v2",
                "signal_triggered_at": triggered_at,
                "feature_observed_at": triggered_at - 60,
                "label_observed_at": triggered_at + DAY_SECONDS,
                "predictive_evidence_score": 90 if target else 10,
                "target_tp2_hit_within_horizon": target,
                "canonical_symbol": f"ASSET{index % 4}-USDT-PERP",
                "regime": "BEAR_TREND" if index % 4 < 2 else "RANGE_HIGH_VOL",
                "net_utility_r": 1.0 if target else -0.75,
                "execution_costs_complete": True,
                "execution_cost_basis": "REALIZED",
                "source_row_sha256": hashlib.sha256(
                    f"strict-source:{index}".encode()
                ).hexdigest(),
            }
        )
    return ScientificValidationRequest.model_validate(
        {
            "source_dataset_manifest_sha256": "a" * 64,
            "source_revision": "b" * 40,
            "generated_at": rows[-1]["label_observed_at"],
            "target_horizon_seconds": DAY_SECONDS,
            "rows": rows,
        }
    )


def test_complete_validation_is_deterministic_purged_and_owner_gated() -> None:
    request = _request()

    first = validate_strict_scientific_evidence(request)
    second = validate_strict_scientific_evidence(request)

    assert first == second
    assert first["report_sha256"] == second["report_sha256"]
    assert first["evidence_gate_status"] == "COMPLETE_FOR_OWNER_REVIEW"
    assert first["promotion_decision"] == "OWNER_REVIEW_REQUIRED"
    assert first["promotion_allowed"] is False
    assert first["feature_promotion_approval_required"] is True
    assert (
        first["champion_challenger"]["champion_model_id"]
        == "regularized_logistic_score_v1"
    )
    assert first["champion_challenger"]["holdout_used_for_selection"] is False
    assert first["independent_calibration"]["fit_source"] == "CALIBRATION_SPLIT_ONLY"
    assert first["untouched_holdout"]["used_for_selection"] is False
    assert first["untouched_holdout"]["multi_regime_audit"]["regime_count"] == 2
    assert first["untouched_holdout"]["symbol_concentration_audit"][
        "maximum_symbol_share"
    ] <= 0.6
    assert "pr_auc_average_precision" in first["untouched_holdout"][
        "probability_metrics"
    ]
    assert "maximum_drawdown_r" in first["untouched_holdout"]["net_utility"]
    assert (
        first["untouched_holdout"]["block_bootstrap_confidence_intervals"]
        ["method"]
        == "DETERMINISTIC_MOVING_BLOCK_BOOTSTRAP"
    )
    for fold in first["walk_forward"]["folds"]:
        assert fold["maximum_train_label_observed_at"] <= (
            fold["test_start"] - first["validation_policy"]["embargo_seconds"]
        )
    assert first["model_card"]["probability_display_allowed"] is False
    assert first["model_card"]["live_execution_allowed"] is False


def test_holdout_changes_cannot_change_champion_selection() -> None:
    request = _request()
    original = validate_strict_scientific_evidence(request)
    holdout_start = original["split_summary"]["boundaries"]["holdout_start"]
    changed_rows = []
    for row in request.rows:
        payload = row.model_dump(mode="json")
        if row.signal_triggered_at >= holdout_start:
            payload["target_tp2_hit_within_horizon"] = (
                not row.target_tp2_hit_within_horizon
            )
            payload["net_utility_r"] = -row.net_utility_r
        changed_rows.append(payload)
    changed_payload = request.model_dump(mode="json")
    changed_payload["rows"] = changed_rows
    changed_request = ScientificValidationRequest.model_validate(changed_payload)

    changed = validate_strict_scientific_evidence(changed_request)

    assert changed["champion_challenger"]["champion_model_id"] == (
        original["champion_challenger"]["champion_model_id"]
    )
    assert changed["champion_challenger"]["ranking"] == (
        original["champion_challenger"]["ranking"]
    )
    assert changed["untouched_holdout"]["probability_metrics"] != (
        original["untouched_holdout"]["probability_metrics"]
    )


def test_insufficient_strict_evidence_fails_closed_with_model_card() -> None:
    report = validate_strict_scientific_evidence(
        _request(days=9, row_count=24)
    )

    assert report["evidence_gate_status"] == "INSUFFICIENT"
    assert report["promotion_decision"] == "DO_NOT_PROMOTE"
    assert report["promotion_allowed"] is False
    assert "STRICT_OBSERVATION_SPAN_BELOW_SIX_WEEKS" in report["blocking_reasons"]
    assert "STRICT_TOTAL_ROW_COUNT_BELOW_POLICY_MINIMUM" in report["blocking_reasons"]
    assert report["champion_challenger"]["available"] is False
    assert report["untouched_holdout"]["available"] is False
    assert report["model_card"]["status"] == "NOT_TRAINED"


def test_complete_data_with_negative_net_utility_still_does_not_promote() -> None:
    request = _request()
    payload = request.model_dump(mode="json")
    for row in payload["rows"]:
        row["net_utility_r"] = -1.0

    report = validate_strict_scientific_evidence(payload)

    assert report["evidence_gate_status"] == "PERFORMANCE_GATE_FAILED"
    assert report["promotion_decision"] == "DO_NOT_PROMOTE"
    assert "HOLDOUT_NET_UTILITY_NOT_POSITIVE" in report["blocking_reasons"]
    assert report["model_card"]["status"] == "VALIDATED_DO_NOT_PROMOTE"
    assert report["promotion_allowed"] is False


def test_complete_data_with_symbol_concentration_still_does_not_promote() -> None:
    payload = _request().model_dump(mode="json")
    for row in payload["rows"]:
        row["canonical_symbol"] = "ONE-ASSET-USDT-PERP"

    report = validate_strict_scientific_evidence(payload)

    assert report["evidence_gate_status"] == "PERFORMANCE_GATE_FAILED"
    assert "HOLDOUT_SYMBOL_CONCENTRATION_EXCEEDS_POLICY" in report["blocking_reasons"]
    assert report["promotion_decision"] == "DO_NOT_PROMOTE"


def test_validation_rejects_non_strict_future_or_mixed_horizon_rows() -> None:
    base = _request(days=9, row_count=24).model_dump(mode="json")
    non_strict = {**base["rows"][0], "signal_class": "EXPERIMENTAL"}
    future = {
        **base["rows"][0],
        "feature_observed_at": base["rows"][0]["signal_triggered_at"] + 1,
    }
    mixed_horizon = {
        **base["rows"][0],
        "label_observed_at": base["rows"][0]["label_observed_at"] + 1,
    }

    with pytest.raises(ValidationError):
        ScientificValidationRequest.model_validate({**base, "rows": [non_strict]})
    with pytest.raises(ValidationError, match="feature evidence"):
        ScientificValidationRequest.model_validate({**base, "rows": [future]})
    with pytest.raises(ValidationError, match="declared target horizon"):
        ScientificValidationRequest.model_validate({**base, "rows": [mixed_horizon]})


def test_validation_rejects_coerced_time_and_ambiguous_revision() -> None:
    base = _request(days=9, row_count=24).model_dump(mode="json")
    coerced = {**base["rows"][0], "signal_triggered_at": "1800000000"}

    with pytest.raises(ValidationError):
        ScientificValidationRequest.model_validate({**base, "rows": [coerced]})
    with pytest.raises(ValidationError, match="40- or 64-character"):
        ScientificValidationRequest.model_validate({**base, "source_revision": "b" * 41})


def test_policy_is_hash_bound() -> None:
    policy = ScientificValidationPolicy.v1()
    material = policy.model_dump(mode="json")
    material["minimum_total_rows"] += 1

    with pytest.raises(ValidationError, match="policy hash mismatch"):
        ScientificValidationPolicy.model_validate(material)
