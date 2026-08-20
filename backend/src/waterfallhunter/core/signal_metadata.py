from __future__ import annotations

import hashlib
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from waterfallhunter.core.canonical_json import canonical_json_bytes
from waterfallhunter.core.contracts import SignalClass


Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonEmptyStr = Annotated[str, Field(min_length=1)]
NonNegativeTimestamp = Annotated[int, Field(ge=0)]

METADATA_CONTRACT_VERSION: Literal["signal_metadata_v1"] = "signal_metadata_v1"
STRICT_STRATEGY_PROFILE = "strict_score_v2"
EXPERIMENTAL_STRATEGY_PROFILE = "experimental_pretrigger_v1"
MODEL_GENERATION = "waterfall_signal_model_v1"


class ClassificationMethod(str, Enum):
    FUTURE_PIPELINE_EXPLICIT = "FUTURE_PIPELINE_EXPLICIT"
    LEGACY_PROFILE_EXACT_MATCH = "LEGACY_PROFILE_EXACT_MATCH"


def validate_lineage_pair(
    signal_class: SignalClass,
    strategy_profile: str,
) -> None:
    expected_profile = {
        SignalClass.STRICT: STRICT_STRATEGY_PROFILE,
        SignalClass.EXPERIMENTAL: EXPERIMENTAL_STRATEGY_PROFILE,
    }.get(signal_class)
    if expected_profile != strategy_profile:
        raise ValueError(
            "signal class and strategy profile do not match canonical lineage"
        )


class SignalMetadataInput(BaseModel):
    """Immutable first-class lineage required for a canonical signal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_class: SignalClass
    strategy_profile: NonEmptyStr
    score_version: NonEmptyStr
    model_generation: NonEmptyStr
    decision_contract_hash: Sha256Hex
    analysis_observed_at: NonNegativeTimestamp
    reference_observed_at: NonNegativeTimestamp | None = None
    metadata_contract_version: Literal["signal_metadata_v1"] = (
        METADATA_CONTRACT_VERSION
    )
    classification_method: ClassificationMethod
    classification_evidence_hash: Sha256Hex | None = None

    @model_validator(mode="after")
    def _validate_lineage(self) -> "SignalMetadataInput":
        validate_lineage_pair(
            self.signal_class,
            self.strategy_profile,
        )
        if (
            self.classification_method
            is ClassificationMethod.FUTURE_PIPELINE_EXPLICIT
            and self.classification_evidence_hash is not None
        ):
            raise ValueError(
                "future explicit lineage must not carry legacy evidence hash"
            )
        if (
            self.classification_method
            is ClassificationMethod.LEGACY_PROFILE_EXACT_MATCH
            and self.classification_evidence_hash is None
        ):
            raise ValueError(
                "legacy classification requires classification evidence hash"
            )
        return self


def canonical_sha256(value: Any) -> str:
    """Return SHA-256 over RFC8785/JCS canonical bytes."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
