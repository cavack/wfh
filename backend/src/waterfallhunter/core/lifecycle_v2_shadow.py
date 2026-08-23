"""Deterministic Lifecycle V2 evaluator that cannot mutate V1 state."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from waterfallhunter.core.lifecycle_feature_registry import (
    LifecycleProfile,
    LifecycleV2Policy,
    lifecycle_feature_registry,
    lifecycle_v2_policy_v1,
)
from waterfallhunter.core.signal_metadata import canonical_sha256


POLICY_VERSION = "lifecycle_v2_shadow_policy_v1"
STRATEGY_PROFILE = LifecycleProfile.STRICT.value


class LifecycleV2State(str, Enum):
    WATCH = "WATCH"
    FUEL_RICH = "FUEL_RICH"
    PRE_TRIGGER = "PRE_TRIGGER"
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"
    LATE = "LATE"
    EXHAUSTED = "EXHAUSTED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    EXECUTION_BLOCKED = "EXECUTION_BLOCKED"


TERMINAL_STATES = frozenset(
    {
        LifecycleV2State.LATE,
        LifecycleV2State.EXHAUSTED,
        LifecycleV2State.INVALIDATED,
        LifecycleV2State.EXPIRED,
        LifecycleV2State.EXECUTION_BLOCKED,
    }
)


class LifecycleV2Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    eligible_data: bool
    evaluated_profile: LifecycleProfile = LifecycleProfile.STRICT
    feature_registry_hash: str = Field(
        default_factory=lambda: str(lifecycle_feature_registry()["registry_hash"]),
        pattern=r"^[0-9a-f]{64}$",
    )
    unavailable_fields: tuple[str, ...] = ()
    fuel_rich: bool | None = None
    structure_count: int | None = Field(default=None, ge=0)
    flow_family_pass: bool | None = None
    relative_family_pass: bool | None = None
    anti_chase_pass: bool | None = None
    strict_setup_ready: bool | None = None
    lower_tf_trigger_closed: bool | None = None
    distance_to_trigger_atr: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )
    lbank_constraints_fresh: bool | None = None
    orderbook_fresh: bool | None = None
    levels_constructible: bool | None = None
    estimated_round_trip_cost_r: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )
    executable_depth_multiple: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )
    preliminary_portfolio_capacity: bool | None = None
    confirmation_count: int | None = Field(default=None, ge=0)
    confirmation_family_count: int | None = Field(default=None, ge=0)
    extension_atr: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    invalidation_closed: bool = False
    expired: bool = False
    exhausted: bool = False
    liquidity_shock: bool = False
    oldest_required_observed_at: int | None = Field(default=None, ge=0)
    decision_at: int = Field(ge=0)
    max_required_age_seconds: int = Field(default=60, ge=1)
    evidence_refs: tuple[str, ...]

    @model_validator(mode="after")
    def _clock_order(self) -> "LifecycleV2Evidence":
        required_fields = (
            "fuel_rich",
            "structure_count",
            "flow_family_pass",
            "relative_family_pass",
            "anti_chase_pass",
            "strict_setup_ready",
            "lower_tf_trigger_closed",
            "distance_to_trigger_atr",
            "lbank_constraints_fresh",
            "orderbook_fresh",
            "levels_constructible",
            "estimated_round_trip_cost_r",
            "executable_depth_multiple",
            "preliminary_portfolio_capacity",
            "confirmation_count",
            "confirmation_family_count",
            "extension_atr",
            "oldest_required_observed_at",
        )
        actually_missing = tuple(
            name for name in required_fields if getattr(self, name) is None
        )
        if self.eligible_data and (actually_missing or self.unavailable_fields):
            raise ValueError("eligible lifecycle evidence must be complete")
        if not self.eligible_data and not self.unavailable_fields:
            raise ValueError("ineligible lifecycle evidence must name unavailable fields")
        if set(actually_missing) - set(self.unavailable_fields):
            raise ValueError("every missing lifecycle field must be declared unavailable")
        if (
            self.oldest_required_observed_at is not None
            and self.oldest_required_observed_at > self.decision_at
        ):
            raise ValueError("required evidence cannot be observed after decision_at")
        if not self.evidence_refs:
            raise ValueError("lifecycle transitions require evidence references")
        return self

    @property
    def fresh(self) -> bool:
        if self.oldest_required_observed_at is None:
            return False
        return (
            self.decision_at - self.oldest_required_observed_at
            <= self.max_required_age_seconds
        )


class LifecycleV2Transition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["lifecycle_v2_shadow_transition_v1"]
    episode_id: str = Field(min_length=1)
    from_state: LifecycleV2State
    to_state: LifecycleV2State
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    observed_at: int = Field(ge=0)
    policy_version: Literal["lifecycle_v2_shadow_policy_v1"]
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    strategy_profile: LifecycleProfile
    shadow_only: Literal[True]
    trade_eligible: Literal[False]
    transition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def evaluate_lifecycle_v2_shadow(
    *,
    episode_id: str,
    current_state: LifecycleV2State,
    evidence: LifecycleV2Evidence,
    policy: LifecycleV2Policy | None = None,
) -> LifecycleV2Transition:
    active_policy = policy or lifecycle_v2_policy_v1()
    if evidence.feature_registry_hash != active_policy.feature_registry_hash:
        raise ValueError("LIFECYCLE_FEATURE_REGISTRY_MISMATCH")
    next_state, reasons = _next_state(current_state, evidence, active_policy)
    material = {
        "contract_version": "lifecycle_v2_shadow_transition_v1",
        "episode_id": episode_id,
        "from_state": current_state.value,
        "to_state": next_state.value,
        "reason_codes": list(reasons),
        "evidence_refs": list(evidence.evidence_refs),
        "observed_at": evidence.decision_at,
        "policy_version": POLICY_VERSION,
        "policy_hash": active_policy.policy_hash,
        "feature_registry_hash": active_policy.feature_registry_hash,
        "strategy_profile": evidence.evaluated_profile.value,
        "shadow_only": True,
        "trade_eligible": False,
    }
    return LifecycleV2Transition.model_validate(
        {**material, "transition_hash": canonical_sha256(material)}
    )


def compare_v1_v2_shadow(
    *,
    episode_id: str,
    v1_state: str,
    v2_state: LifecycleV2State,
    evidence: LifecycleV2Evidence,
    policy: LifecycleV2Policy | None = None,
) -> dict:
    transition = evaluate_lifecycle_v2_shadow(
        episode_id=episode_id,
        current_state=v2_state,
        evidence=evidence,
        policy=policy,
    )
    packet = {
        "contract_version": "lifecycle_v1_v2_shadow_comparison_v1",
        "episode_id": episode_id,
        "v1_state_unchanged": str(v1_state),
        "v2_from_state": transition.from_state.value,
        "v2_to_state": transition.to_state.value,
        "diverged": str(v1_state) != transition.to_state.value,
        "v2_transition_hash": transition.transition_hash,
        "shadow_only": True,
        "promotion_allowed": False,
    }
    return {**packet, "comparison_hash": canonical_sha256(packet)}


def _next_state(
    current: LifecycleV2State,
    evidence: LifecycleV2Evidence,
    policy: LifecycleV2Policy,
) -> tuple[LifecycleV2State, tuple[str, ...]]:
    thresholds = policy.thresholds
    if current in TERMINAL_STATES:
        return current, ("TERMINAL_EPISODE_IMMUTABLE",)
    if not evidence.eligible_data:
        return current, ("INSUFFICIENT_EVIDENCE",)
    if evidence.invalidation_closed:
        return LifecycleV2State.INVALIDATED, ("INVALIDATION_CLOSED",)
    if evidence.expired:
        return LifecycleV2State.EXPIRED, ("SIGNAL_EXPIRED",)
    if evidence.liquidity_shock:
        return LifecycleV2State.EXECUTION_BLOCKED, ("EXECUTION_LIQUIDITY_SHOCK",)
    if evidence.exhausted:
        return LifecycleV2State.EXHAUSTED, ("MOVE_EXHAUSTED",)
    if evidence.extension_atr >= thresholds.hard_block_atr:
        return LifecycleV2State.EXECUTION_BLOCKED, ("ANTI_CHASE_HARD_BLOCK",)
    if evidence.extension_atr > thresholds.late_atr:
        return LifecycleV2State.LATE, ("LATE_EXTENSION",)
    if not evidence.fresh:
        return current, ("DATA_STALE",)
    if current is LifecycleV2State.WATCH:
        if evidence.fuel_rich:
            return LifecycleV2State.FUEL_RICH, ("FUEL_EXPANSION_CONFIRMED",)
        return current, ("FUEL_RICH_NOT_CONFIRMED",)
    if current is LifecycleV2State.FUEL_RICH:
        if (
            evidence.structure_count >= thresholds.structure_count_minimum
            and (evidence.flow_family_pass or evidence.relative_family_pass)
            and evidence.anti_chase_pass
        ):
            return LifecycleV2State.PRE_TRIGGER, ("STRUCTURE_AND_WEAKNESS_CONFIRMED",)
        return current, ("STRUCTURE_NOT_CONFIRMED",)
    if current is LifecycleV2State.PRE_TRIGGER:
        if evidence.evaluated_profile is LifecycleProfile.EXPERIMENTAL:
            return current, ("EXPERIMENTAL_PROFILE_OBSERVATIONAL_ONLY",)
        reasons = []
        if not evidence.strict_setup_ready:
            reasons.append("STRICT_SETUP_NOT_READY")
        if evidence.lower_tf_trigger_closed:
            reasons.append("TRIGGER_ALREADY_CLOSED_BEFORE_ARMING")
        if evidence.distance_to_trigger_atr > thresholds.controlled_momentum_max_atr:
            reasons.append("TRIGGER_DISTANCE_TOO_LARGE")
        if not evidence.lbank_constraints_fresh:
            reasons.append("LBANK_CONSTRAINTS_STALE")
        if not evidence.orderbook_fresh:
            reasons.append("DATA_STALE")
        if not evidence.levels_constructible:
            reasons.append("EXECUTION_LEVELS_UNAVAILABLE")
        if evidence.estimated_round_trip_cost_r > thresholds.estimated_cost_r_maximum:
            reasons.append("ESTIMATED_COST_TOO_HIGH")
        if evidence.executable_depth_multiple < thresholds.executable_depth_multiple_minimum:
            reasons.append("DEPTH_INSUFFICIENT")
        if not evidence.preliminary_portfolio_capacity:
            reasons.append("PORTFOLIO_CAPACITY_FULL")
        if reasons:
            return current, tuple(reasons)
        return LifecycleV2State.ARMED, ("STRICT_SETUP_ARMED",)
    if current is LifecycleV2State.ARMED:
        if (
            evidence.lower_tf_trigger_closed
            and evidence.confirmation_count >= thresholds.confirmation_count_minimum
            and evidence.confirmation_family_count
            >= thresholds.confirmation_family_count_minimum
        ):
            return LifecycleV2State.TRIGGERED, ("CLOSED_TRIGGER_CONFIRMED",)
        return current, ("TRIGGER_NOT_CLOSED",)
    return current, ("NO_FORWARD_TRANSITION",)


def build_lifecycle_v2_evidence_from_metrics(
    *,
    metrics: dict[str, Any],
    decision_at: int,
    analysis_observed_at: int | None,
    reference_observed_at: int | None,
) -> LifecycleV2Evidence:
    """Map runtime facts into V2 evidence without inventing missing values."""

    stage = metrics.get("stage_lifecycle")
    confirmed = stage.get("confirmed") if isinstance(stage, dict) else None
    candles = metrics.get("candle_features")
    micro = metrics.get("microstructure")
    relative = metrics.get("relative_weakness_features")
    breakdown = metrics.get("breakdown_confirmation")
    constraints = metrics.get("validated_lbank_constraints")
    preview = metrics.get("execution_preview")
    capacity = metrics.get("portfolio_capacity")

    candle_packets = (
        tuple(value for value in candles.values() if isinstance(value, dict))
        if isinstance(candles, dict)
        else ()
    )
    structure_count = (
        sum(
            bool(packet.get("lower_high") is True or packet.get("setup") is True)
            for packet in candle_packets
        )
        if candle_packets
        else None
    )
    distances = tuple(
        abs(float(value))
        for packet in candle_packets
        if isinstance((value := packet.get("distance_to_support_atr")), (int, float))
        and not isinstance(value, bool)
    )
    extensions = tuple(
        max(0.0, float(value))
        for packet in candle_packets
        if isinstance((value := packet.get("extension_from_support_atr")), (int, float))
        and not isinstance(value, bool)
    )
    relative_values = (
        tuple(
            float(value)
            for packet in relative.get("timeframes", {}).values()
            if isinstance(packet, dict)
            for key, value in packet.items()
            if key.startswith("relative_return_")
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        )
        if isinstance(relative, dict) and isinstance(relative.get("timeframes"), dict)
        else ()
    )
    footprint = micro.get("footprint") if isinstance(micro, dict) else None
    orderbook_observed_at = (
        int(float(micro["observed_at"]))
        if isinstance(micro, dict)
        and isinstance(micro.get("observed_at"), (int, float))
        and not isinstance(micro.get("observed_at"), bool)
        else None
    )
    constraints_observed_at = (
        int(constraints["constraints_observed_at"])
        if isinstance(constraints, dict)
        and isinstance(constraints.get("constraints_observed_at"), int)
        and not isinstance(constraints.get("constraints_observed_at"), bool)
        else None
    )
    constraints_expires_at = (
        int(constraints["expires_at"])
        if isinstance(constraints, dict)
        and isinstance(constraints.get("expires_at"), int)
        and not isinstance(constraints.get("expires_at"), bool)
        else None
    )

    values: dict[str, Any] = {
        "fuel_rich": (
            confirmed.get("hype") is True if isinstance(confirmed, dict) else None
        ),
        "structure_count": structure_count,
        "flow_family_pass": (
            footprint.get("aggressive_selling") is True
            if isinstance(footprint, dict)
            else None
        ),
        "relative_family_pass": (
            sum(value < 0 for value in relative_values) >= 2
            if relative_values
            else None
        ),
        "anti_chase_pass": max(extensions) <= 0.8 if extensions else None,
        "strict_setup_ready": (
            metrics.get("trade_eligible") is True
            and isinstance(confirmed, dict)
            and confirmed.get("setup") is True
        ) if isinstance(confirmed, dict) else None,
        "lower_tf_trigger_closed": (
            breakdown.get("composite_breakdown_confirmed")
            if isinstance(breakdown, dict)
            and isinstance(breakdown.get("composite_breakdown_confirmed"), bool)
            else None
        ),
        "distance_to_trigger_atr": min(distances) if distances else None,
        "lbank_constraints_fresh": (
            constraints_observed_at is not None
            and constraints_expires_at is not None
            and constraints_observed_at <= decision_at < constraints_expires_at
        ) if isinstance(constraints, dict) else None,
        "orderbook_fresh": (
            0 <= decision_at - orderbook_observed_at <= 5
            if orderbook_observed_at is not None
            else None
        ),
        "levels_constructible": (
            preview.get("status") == "READY" if isinstance(preview, dict) else None
        ),
        "estimated_round_trip_cost_r": (
            float(preview["estimated_round_trip_cost_r"])
            if isinstance(preview, dict)
            and isinstance(preview.get("estimated_round_trip_cost_r"), (int, float))
            and not isinstance(preview.get("estimated_round_trip_cost_r"), bool)
            else None
        ),
        "executable_depth_multiple": (
            float(preview["executable_depth_multiple"])
            if isinstance(preview, dict)
            and isinstance(preview.get("executable_depth_multiple"), (int, float))
            and not isinstance(preview.get("executable_depth_multiple"), bool)
            else None
        ),
        "preliminary_portfolio_capacity": (
            capacity.get("available") is True if isinstance(capacity, dict) else None
        ),
        "confirmation_count": (
            sum(
                value is True
                for value in (
                    breakdown.get("primary_breakdown_confirmed"),
                    breakdown.get("confirmation_exchange_15m"),
                    footprint.get("aggressive_selling") if isinstance(footprint, dict) else None,
                )
            )
            if isinstance(breakdown, dict)
            else None
        ),
        "confirmation_family_count": (
            sum(
                value is True
                for value in (
                    breakdown.get("primary_breakdown_confirmed"),
                    breakdown.get("confirmation_exchange_15m"),
                    footprint.get("aggressive_selling") if isinstance(footprint, dict) else None,
                )
            )
            if isinstance(breakdown, dict)
            else None
        ),
        "extension_atr": max(extensions) if extensions else None,
        "oldest_required_observed_at": (
            min(
                timestamp
                for timestamp in (
                    analysis_observed_at,
                    reference_observed_at,
                    orderbook_observed_at,
                    constraints_observed_at,
                )
                if timestamp is not None
            )
            if all(
                timestamp is not None
                for timestamp in (
                    analysis_observed_at,
                    reference_observed_at,
                    orderbook_observed_at,
                    constraints_observed_at,
                )
            )
            else None
        ),
    }
    unavailable = tuple(sorted(name for name, value in values.items() if value is None))
    refs = tuple(
        f"{name}:{timestamp}"
        for name, timestamp in (
            ("analysis", analysis_observed_at),
            ("reference", reference_observed_at),
            ("orderbook", orderbook_observed_at),
            ("lbank_constraints", constraints_observed_at),
        )
        if timestamp is not None
    ) or (f"decision:{decision_at}",)
    registry = lifecycle_feature_registry()
    runtime_profile = (
        LifecycleProfile.EXPERIMENTAL
        if str(metrics.get("strategy_profile") or "").lower().startswith("experimental")
        else LifecycleProfile.STRICT
    )
    refs = (
        *refs,
        f"feature_registry:{registry['registry_hash']}",
        f"derived_evidence:{canonical_sha256(values)}",
    )
    return LifecycleV2Evidence.model_validate(
        {
            "eligible_data": not unavailable,
            "evaluated_profile": runtime_profile,
            "feature_registry_hash": registry["registry_hash"],
            "unavailable_fields": unavailable,
            **values,
            "decision_at": decision_at,
            "evidence_refs": refs,
        }
    )
