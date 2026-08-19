from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


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
