from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


NonEmptyStr = Annotated[str, Field(min_length=1)]
Score100 = Annotated[float, Field(ge=0.0, le=100.0, allow_inf_nan=False)]
Probability = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
PositiveFinite = Annotated[float, Field(gt=0.0, allow_inf_nan=False)]
NonNegativeFinite = Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SystemLeverage = Annotated[float, Field(ge=3.0, le=20.0, allow_inf_nan=False)]


class SourceRevisionStatus(str, Enum):
    VERIFIED_GIT_REVISION = "VERIFIED_GIT_REVISION"
    LEGACY_RUNTIME_UNVERIFIED_REVISION = "LEGACY_RUNTIME_UNVERIFIED_REVISION"


class SignalClass(str, Enum):
    STRICT = "STRICT"
    EXPERIMENTAL = "EXPERIMENTAL"


class LifecycleState(str, Enum):
    WATCH = "WATCH"
    FUEL_RICH = "FUEL_RICH"
    PRE_TRIGGER = "PRE_TRIGGER"
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"
    LATE = "LATE"
    EXHAUSTED = "EXHAUSTED"


class DecisionPrimary(str, Enum):
    OBSERVING = "OBSERVING"
    NOT_TRADE_ELIGIBLE = "NOT_TRADE_ELIGIBLE"
    CONFIRMED = "CONFIRMED"
    INVALIDATED = "INVALIDATED"
    UNAVAILABLE = "UNAVAILABLE"


class DecisionQualifier(str, Enum):
    AI_CAUTION = "AI_CAUTION"
    EXECUTION_LEVELS_UNAVAILABLE = "EXECUTION_LEVELS_UNAVAILABLE"
    STALE_ANALYSIS = "STALE_ANALYSIS"
    STALE_REFERENCE = "STALE_REFERENCE"
    LATE_ENTRY_BLOCKED = "LATE_ENTRY_BLOCKED"
    ANTI_CHASE_BLOCKED = "ANTI_CHASE_BLOCKED"
    EXECUTION_DEGRADED = "EXECUTION_DEGRADED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ExecutionMode(str, Enum):
    PAPER_ONLY = "PAPER_ONLY"


class MarginMode(str, Enum):
    ISOLATED = "ISOLATED"


class PositionExecutionState(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"
    LIQUIDATED = "LIQUIDATED"


class PositionThesisState(str, Enum):
    VALID = "VALID"
    CAUTION = "CAUTION"
    HIGH_RISK = "HIGH_RISK"
    THESIS_INVALIDATED = "THESIS_INVALIDATED"


class DecisionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    primary: DecisionPrimary
    qualifiers: tuple[DecisionQualifier, ...] = ()

    @field_validator("qualifiers", mode="before")
    @classmethod
    def _canonicalize_qualifiers(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, (str, DecisionQualifier)):
            items = [value]
        else:
            items = list(value)

        normalized = {DecisionQualifier(item).value for item in items}
        return tuple(sorted(normalized))


class CommonContractEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_type: NonEmptyStr
    contract_version: NonEmptyStr
    schema_version: NonEmptyStr
    generated_at: Annotated[int, Field(ge=0)]
    producer: NonEmptyStr
    model_generation: NonEmptyStr
    source_revision_status: SourceRevisionStatus
    observational_only: Literal[True] = True


class EvidenceQualityPacket(CommonContractEnvelope):
    coverage_pct: Score100
    completeness_status: NonEmptyStr
    analysis_observed_at: Annotated[int, Field(ge=0)]
    analysis_age_seconds: NonNegativeFinite
    reference_observed_at: Annotated[int, Field(ge=0)] | None = None
    reference_age_seconds: NonNegativeFinite | None = None
    timestamp_alignment_status: NonEmptyStr
    candle_coverage: Score100 | None = None
    derivatives_coverage: Score100 | None = None
    microstructure_coverage: Score100 | None = None
    execution_coverage: Score100 | None = None
    cross_exchange_coverage: Score100 | None = None
    missing_sources: tuple[str, ...] = ()
    stale_sources: tuple[str, ...] = ()
    uncertainty_reasons: tuple[str, ...] = ()


class SignalDecisionPacket(CommonContractEnvelope):
    decision_id: NonEmptyStr
    signal_id: NonEmptyStr
    symbol: NonEmptyStr
    signal_class: SignalClass
    strategy_profile: NonEmptyStr
    lifecycle_state: LifecycleState
    decision_status: DecisionStatus
    score_version: NonEmptyStr
    decision_contract_hash: Sha256Hex
    analysis_observed_at: Annotated[int, Field(ge=0)]
    reference_observed_at: Annotated[int, Field(ge=0)] | None = None
    eligibility_gates: dict[str, Any]
    evidence_quality: EvidenceQualityPacket
    predictive_evidence_score: Score100 | None = None
    final_signal_score: Score100
    calibrated_probability: Probability | None = None
    anti_chase_risk: NonEmptyStr
    execution_risk: NonEmptyStr
    execution_plan_id: NonEmptyStr
    reason_codes: tuple[str, ...]
    execution_mode: ExecutionMode = ExecutionMode.PAPER_ONLY


class ExecutionPlan(CommonContractEnvelope):
    execution_plan_id: NonEmptyStr
    signal_id: NonEmptyStr
    venue: Literal["LBANK"] = "LBANK"
    contract_identity: NonEmptyStr
    margin_mode: MarginMode = MarginMode.ISOLATED
    cross_margin_allowed: Literal[False] = False
    auto_add_margin: Literal[False] = False
    entry_primary: PositiveFinite | None = None
    entry_secondary: PositiveFinite | None = None
    tp1: PositiveFinite | None = None
    tp2: PositiveFinite | None = None
    stop_loss: PositiveFinite | None = None
    raw_safe_leverage: PositiveFinite | None = None
    system_leverage: SystemLeverage | None = None
    risk_label: NonEmptyStr | None = None
    spread: NonNegativeFinite | None = None
    entry_slippage: NonNegativeFinite | None = None
    exit_slippage: NonNegativeFinite | None = None
    depth: NonNegativeFinite | None = None
    gross_tp1_pnl: FiniteFloat | None = None
    net_tp1_pnl: FiniteFloat | None = None
    gross_tp2_pnl: FiniteFloat | None = None
    net_tp2_pnl: FiniteFloat | None = None
    gross_sl_pnl: FiniteFloat | None = None
    net_sl_pnl: FiniteFloat | None = None
    fees_model_version: NonEmptyStr | None = None
    funding_model_version: NonEmptyStr | None = None
    levels_available: bool
    unavailable_reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _validate_level_availability(self) -> "ExecutionPlan":
        if self.levels_available:
            required = (
                self.entry_primary,
                self.tp1,
                self.tp2,
                self.stop_loss,
                self.system_leverage,
            )
            if any(value is None for value in required):
                raise ValueError(
                    "available execution levels require entry_primary, tp1, tp2, "
                    "stop_loss, and system_leverage"
                )
        elif self.unavailable_reason is None:
            raise ValueError("unavailable execution levels require unavailable_reason")
        return self


class PositionState(CommonContractEnvelope):
    position_id: NonEmptyStr
    signal_id: NonEmptyStr
    execution_state: PositionExecutionState
    thesis_state: PositionThesisState
    original_execution_plan_id: NonEmptyStr
    margin_mode: MarginMode = MarginMode.ISOLATED
    isolated_margin_initial: NonNegativeFinite
    isolated_margin_current: NonNegativeFinite
    notional: NonNegativeFinite
    entry_price: PositiveFinite
    realized_pnl: FiniteFloat
    unrealized_pnl: FiniteFloat
    fees: NonNegativeFinite
    funding: FiniteFloat
    current_sl: PositiveFinite | None = None
    current_tp1: PositiveFinite | None = None
    current_tp2: PositiveFinite | None = None
    latest_amendment_id: NonEmptyStr | None = None
    opened_at: Annotated[int, Field(ge=0)]
    last_reassessed_at: Annotated[int, Field(ge=0)]
    closed_at: Annotated[int, Field(ge=0)] | None = None


class PositionAmendment(CommonContractEnvelope):
    amendment_id: NonEmptyStr
    position_id: NonEmptyStr
    action: NonEmptyStr
    reason_codes: tuple[str, ...]
    created_at: Annotated[int, Field(ge=0)]
    proposed_sl: PositiveFinite | None = None
    proposed_tp1: PositiveFinite | None = None
    proposed_tp2: PositiveFinite | None = None
    source_context_version: NonEmptyStr


class NotificationEvent(CommonContractEnvelope):
    event_id: NonEmptyStr
    event_type: NonEmptyStr
    aggregate_type: NonEmptyStr
    aggregate_id: NonEmptyStr
    symbol: NonEmptyStr | None = None
    signal_class: SignalClass | None = None
    lifecycle_state: LifecycleState | None = None
    decision_status: DecisionStatus | None = None
    material_state_hash: Sha256Hex
    idempotency_key: NonEmptyStr
    priority: int
    payload_contract_version: NonEmptyStr
    payload: dict[str, Any]
    created_at: Annotated[int, Field(ge=0)]
