"""Fail-closed Phase 7 deployment-certification evidence gate."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from waterfallhunter.core.deployment_provenance import (
    DEPLOYMENT_PROVENANCE_VERIFIED,
    evaluate_deployment_provenance,
)
from waterfallhunter.core.signal_metadata import canonical_sha256


class VerificationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    backend_tests_passed: bool
    frontend_tests_passed: bool
    e2e_tests_passed: bool
    migration_tests_passed: bool
    load_tests_passed: bool
    fault_tests_passed: bool
    security_tests_passed: bool
    secret_scan_passed: bool
    blocker_review_findings: int = Field(ge=0, strict=True)


class ReadinessEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    livez_ok: bool
    healthz_ok: bool
    readyz_ok: bool
    schema_ready: bool
    database_ready: bool
    expected_schema_version: int = Field(ge=1, strict=True)
    observed_schema_version: int = Field(ge=0, strict=True)


class ShadowSoakEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    duration_seconds: int = Field(ge=0, strict=True)
    minimum_required_seconds: int = Field(default=86_400, ge=3_600, strict=True)
    request_error_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    maximum_request_error_rate: float = Field(default=0.001, ge=0, le=1)
    oom_events: int = Field(ge=0, strict=True)
    schema_errors: int = Field(ge=0, strict=True)
    live_order_path_count: int = Field(ge=0, strict=True)
    paper_only: Literal[True]


class DeploymentCertificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["deployment_certification_request_v1"] = (
        "deployment_certification_request_v1"
    )
    source_revision: str = Field(min_length=40, max_length=40)
    ci_revision: str = Field(min_length=40, max_length=40)
    artifact_provenance: dict[str, Any]
    backup_certification: dict[str, Any]
    migration_rollback_rehearsal: dict[str, Any]
    verification: VerificationEvidence
    readiness: ReadinessEvidence
    shadow_soak: ShadowSoakEvidence

    @model_validator(mode="after")
    def _revision_shape(self) -> "DeploymentCertificationRequest":
        for value in (self.source_revision, self.ci_revision):
            if any(character not in "0123456789abcdef" for character in value):
                raise ValueError("revisions must be exact lowercase Git SHA-1 values")
        return self


def _hash_valid(document: dict[str, Any], hash_field: str) -> bool:
    expected = document.get(hash_field)
    material = {key: value for key, value in document.items() if key != hash_field}
    return isinstance(expected, str) and expected == canonical_sha256(material)


def evaluate_deployment_certification(
    request: DeploymentCertificationRequest | dict[str, Any],
) -> dict[str, Any]:
    packet = (
        request
        if isinstance(request, DeploymentCertificationRequest)
        else DeploymentCertificationRequest.model_validate(request)
    )
    reasons: list[str] = []
    provenance = evaluate_deployment_provenance(packet.artifact_provenance)
    if packet.source_revision != packet.ci_revision:
        reasons.append("CI_REVISION_MISMATCH")
    if provenance["status"] != DEPLOYMENT_PROVENANCE_VERIFIED:
        reasons.append("ARTIFACT_PROVENANCE_INCOMPLETE")
    if provenance["links"]["git_sha"] != packet.source_revision:
        reasons.append("ARTIFACT_REVISION_MISMATCH")

    backup = packet.backup_certification
    if not _hash_valid(backup, "certification_sha256"):
        reasons.append("BACKUP_CERTIFICATION_HASH_INVALID")
    if backup.get("status") != "BACKUP_RESTORE_CERTIFIED":
        reasons.append("INDEPENDENT_BACKUP_RESTORE_NOT_CERTIFIED")
    if backup.get("source_failure_domain") == backup.get("destination_failure_domain"):
        reasons.append("BACKUP_FAILURE_DOMAIN_NOT_INDEPENDENT")
    if backup.get("device_separation_enforced") is not True:
        reasons.append("BACKUP_DEVICE_SEPARATION_NOT_ENFORCED")

    rehearsal = packet.migration_rollback_rehearsal
    if not _hash_valid(rehearsal, "rehearsal_sha256"):
        reasons.append("MIGRATION_REHEARSAL_HASH_INVALID")
    if rehearsal.get("status") != "MIGRATION_AND_ROLLBACK_REHEARSED":
        reasons.append("MIGRATION_AND_ROLLBACK_NOT_REHEARSED")
    if rehearsal.get("backup_certification_sha256") != backup.get(
        "certification_sha256"
    ):
        reasons.append("REHEARSAL_BACKUP_IDENTITY_MISMATCH")
    if rehearsal.get("source_revision") != packet.source_revision:
        reasons.append("REHEARSAL_REVISION_MISMATCH")

    verification = packet.verification
    for field in (
        "backend_tests_passed",
        "frontend_tests_passed",
        "e2e_tests_passed",
        "migration_tests_passed",
        "load_tests_passed",
        "fault_tests_passed",
        "security_tests_passed",
        "secret_scan_passed",
    ):
        if getattr(verification, field) is not True:
            reasons.append(field.upper().replace("_PASSED", "_FAILED"))
    if verification.blocker_review_findings != 0:
        reasons.append("BLOCKER_REVIEW_FINDINGS_REMAIN")

    readiness = packet.readiness
    if not all(
        (
            readiness.livez_ok,
            readiness.healthz_ok,
            readiness.readyz_ok,
            readiness.schema_ready,
            readiness.database_ready,
        )
    ):
        reasons.append("RUNTIME_READINESS_INCOMPLETE")
    if readiness.observed_schema_version != readiness.expected_schema_version:
        reasons.append("RUNTIME_SCHEMA_VERSION_MISMATCH")

    soak = packet.shadow_soak
    if soak.duration_seconds < soak.minimum_required_seconds:
        reasons.append("SHADOW_SOAK_DURATION_INSUFFICIENT")
    if soak.request_error_rate > soak.maximum_request_error_rate:
        reasons.append("SHADOW_SOAK_ERROR_RATE_EXCEEDED")
    if soak.oom_events != 0:
        reasons.append("SHADOW_SOAK_OOM_EVENTS_PRESENT")
    if soak.schema_errors != 0:
        reasons.append("SHADOW_SOAK_SCHEMA_ERRORS_PRESENT")
    if soak.live_order_path_count != 0:
        reasons.append("LIVE_ORDER_PATH_PRESENT")

    body = {
        "contract_version": "deployment_certification_report_v1",
        "source_revision": packet.source_revision,
        "status": (
            "READY_FOR_EXPLICIT_OWNER_APPROVAL"
            if not reasons
            else "NOT_READY"
        ),
        "blocking_reasons": sorted(set(reasons)),
        "artifact_provenance_sha256": provenance["provenance_sha256"],
        "backup_certification_sha256": backup.get("certification_sha256"),
        "migration_rehearsal_sha256": rehearsal.get("rehearsal_sha256"),
        "deployment_allowed": False,
        "migration_allowed": False,
        "telegram_send_allowed": False,
        "feature_promotion_allowed": False,
        "live_trading_allowed": False,
        "required_next_authority": "EXPLICIT_OWNER_APPROVALS",
    }
    return {**body, "report_sha256": canonical_sha256(body)}
