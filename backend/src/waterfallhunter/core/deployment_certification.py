"""Fail-closed Phase 7 deployment-certification evidence gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from waterfallhunter.core.deployment_provenance import (
    DEPLOYMENT_PROVENANCE_VERIFIED,
    evaluate_deployment_provenance,
)
from waterfallhunter.core.signal_metadata import canonical_sha256
from waterfallhunter.core.schema_contract import CURRENT_RUNTIME_SCHEMA_VERSION


MINIMUM_SHADOW_SOAK_SECONDS = 86_400
MAXIMUM_SHADOW_ERROR_RATE = 0.001
SHA256_PATTERN = r"^[0-9a-f]{64}$"
IMAGE_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"


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
    observed_schema_version: int = Field(ge=0, strict=True)


class ShadowSoakEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_revision: str = Field(min_length=40, max_length=40)
    built_image_digest: str = Field(pattern=IMAGE_DIGEST_PATTERN)
    runtime_fingerprint_sha256: str = Field(pattern=SHA256_PATTERN)
    environment: Literal["STAGING_SHADOW"]
    started_at: int = Field(ge=0, strict=True)
    ended_at: int = Field(ge=0, strict=True)
    request_error_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    oom_events: int = Field(ge=0, strict=True)
    schema_errors: int = Field(ge=0, strict=True)
    live_order_path_count: int = Field(ge=0, strict=True)
    paper_only: Literal[True]

    @model_validator(mode="after")
    def _valid_window(self) -> "ShadowSoakEvidence":
        if self.ended_at <= self.started_at:
            raise ValueError("shadow soak end must follow start")
        if any(character not in "0123456789abcdef" for character in self.source_revision):
            raise ValueError("shadow soak revision must be lowercase hexadecimal")
        return self


class DeploymentCertificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["deployment_certification_request_v1"] = (
        "deployment_certification_request_v1"
    )
    source_revision: str = Field(min_length=40, max_length=40)
    ci_revision: str = Field(min_length=40, max_length=40)
    expected_production_database_path: str = Field(min_length=1)
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
        database_path = Path(self.expected_production_database_path)
        if not database_path.is_absolute() or database_path.resolve(strict=False) != database_path:
            raise ValueError("expected production database path must be canonical and absolute")
        return self


def _hash_valid(document: dict[str, Any], hash_field: str) -> bool:
    expected = document.get(hash_field)
    material = {key: value for key, value in document.items() if key != hash_field}
    return isinstance(expected, str) and expected == canonical_sha256(material)


def _provenance_reasons(
    packet: DeploymentCertificationRequest,
    provenance: dict[str, Any],
) -> list[str]:
    checks = (
        (packet.source_revision != packet.ci_revision, "CI_REVISION_MISMATCH"),
        (provenance["status"] != DEPLOYMENT_PROVENANCE_VERIFIED, "ARTIFACT_PROVENANCE_INCOMPLETE"),
        (provenance["links"]["git_sha"] != packet.source_revision, "ARTIFACT_REVISION_MISMATCH"),
    )
    return [reason for failed, reason in checks if failed]


def _snapshot_audit_valid(audit: Any) -> bool:
    if not isinstance(audit, dict):
        return False
    required = {
        "contract_version",
        "file_sha256",
        "file_size_bytes",
        "integrity_check",
        "foreign_key_violation_count",
        "user_version",
        "schema_version",
        "object_counts",
        "table_counts",
        "schema_sha256",
        "audit_sha256",
    }
    return (
        required.issubset(audit)
        and audit.get("contract_version") == "sqlite_snapshot_audit_v1"
        and audit.get("integrity_check") == "ok"
        and audit.get("foreign_key_violation_count") == 0
        and isinstance(audit.get("file_size_bytes"), int)
        and audit["file_size_bytes"] > 0
        and isinstance(audit.get("object_counts"), dict)
        and isinstance(audit.get("table_counts"), dict)
        and _hash_valid(audit, "audit_sha256")
    )


def _audits_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    fields = (
        "user_version",
        "schema_version",
        "object_counts",
        "table_counts",
        "schema_sha256",
    )
    return all(left.get(field) == right.get(field) for field in fields)


def _complete_backup_contract_valid(
    backup: dict[str, Any],
    *,
    expected_source_path: str,
) -> bool:
    required = {
        "contract_version",
        "status",
        "source_path",
        "source_identity",
        "source_failure_domain",
        "destination_failure_domain",
        "device_separation_enforced",
        "backup_path",
        "restore_target_path",
        "backup_audit",
        "restore_audit",
        "restore_matches_backup",
        "rollback_source_sha256",
        "production_migration_authorized",
        "production_deployment_authorized",
        "certification_sha256",
    }
    backup_audit = backup.get("backup_audit")
    restore_audit = backup.get("restore_audit")
    source_identity = backup.get("source_identity")
    backup_path = Path(str(backup.get("backup_path", "")))
    restore_path = Path(str(backup.get("restore_target_path", "")))
    return (
        required.issubset(backup)
        and backup.get("contract_version") == "sqlite_backup_certification_v1"
        and backup.get("status") == "BACKUP_RESTORE_CERTIFIED"
        and backup.get("source_path") == expected_source_path
        and isinstance(source_identity, dict)
        and set(source_identity) == {"device_id", "inode"}
        and all(isinstance(value, int) and value >= 0 for value in source_identity.values())
        and backup.get("source_failure_domain") != backup.get("destination_failure_domain")
        and backup.get("device_separation_enforced") is True
        and backup_path.is_absolute()
        and restore_path.is_absolute()
        and backup_path != restore_path
        and backup_path.parent == restore_path.parent
        and _snapshot_audit_valid(backup_audit)
        and _snapshot_audit_valid(restore_audit)
        and _audits_match(backup_audit, restore_audit)
        and backup.get("restore_matches_backup") is True
        and backup.get("rollback_source_sha256") == backup_audit.get("file_sha256")
        and backup.get("production_migration_authorized") is False
        and backup.get("production_deployment_authorized") is False
        and _hash_valid(backup, "certification_sha256")
    )


def _backup_reasons(
    backup: dict[str, Any],
    *,
    expected_source_path: str,
) -> list[str]:
    complete = _complete_backup_contract_valid(
        backup,
        expected_source_path=expected_source_path,
    )
    checks = (
        (not _hash_valid(backup, "certification_sha256"), "BACKUP_CERTIFICATION_HASH_INVALID"),
        (backup.get("status") != "BACKUP_RESTORE_CERTIFIED", "INDEPENDENT_BACKUP_RESTORE_NOT_CERTIFIED"),
        (backup.get("source_failure_domain") == backup.get("destination_failure_domain"), "BACKUP_FAILURE_DOMAIN_NOT_INDEPENDENT"),
        (backup.get("device_separation_enforced") is not True, "BACKUP_DEVICE_SEPARATION_NOT_ENFORCED"),
        (backup.get("source_path") != expected_source_path, "BACKUP_SOURCE_IDENTITY_MISMATCH"),
        (not complete, "BACKUP_CERTIFICATION_CONTRACT_INVALID"),
    )
    return [reason for failed, reason in checks if failed]


def _rehearsal_reasons(
    rehearsal: dict[str, Any],
    *,
    backup: dict[str, Any],
    source_revision: str,
) -> list[str]:
    backup_audit = backup.get("backup_audit", {})
    rollback_audit = rehearsal.get("rollback_audit")
    migration_result = rehearsal.get("migration_result")
    migration_path = Path(str(rehearsal.get("migration_target", "")))
    rollback_path = Path(str(rehearsal.get("rollback_target", "")))
    backup_parent = Path(str(backup.get("backup_path", ""))).parent
    required = {
        "contract_version",
        "status",
        "source_revision",
        "backup_certification_sha256",
        "baseline_audit_sha256",
        "migration_target",
        "migration_result",
        "post_migration_audit",
        "rollback_target",
        "rollback_audit",
        "rollback_matches_baseline",
        "production_migration_authorized",
        "production_deployment_authorized",
        "rehearsal_sha256",
    }
    complete = (
        required.issubset(rehearsal)
        and rehearsal.get("contract_version") == "sqlite_migration_rollback_rehearsal_v1"
        and isinstance(migration_result, dict)
        and migration_result.get("ok") is True
        and migration_result.get("user_version") == CURRENT_RUNTIME_SCHEMA_VERSION
        and _snapshot_audit_valid(rehearsal.get("post_migration_audit"))
        and _snapshot_audit_valid(rollback_audit)
        and _snapshot_audit_valid(backup_audit)
        and _audits_match(backup_audit, rollback_audit)
        and rehearsal.get("baseline_audit_sha256") == backup_audit.get("audit_sha256")
        and rehearsal.get("rollback_matches_baseline") is True
        and migration_path.is_absolute()
        and rollback_path.is_absolute()
        and migration_path != rollback_path
        and migration_path.parent == backup_parent
        and rollback_path.parent == backup_parent
        and rehearsal.get("production_migration_authorized") is False
        and rehearsal.get("production_deployment_authorized") is False
    )
    checks = (
        (not _hash_valid(rehearsal, "rehearsal_sha256"), "MIGRATION_REHEARSAL_HASH_INVALID"),
        (rehearsal.get("status") != "MIGRATION_AND_ROLLBACK_REHEARSED", "MIGRATION_AND_ROLLBACK_NOT_REHEARSED"),
        (rehearsal.get("backup_certification_sha256") != backup.get("certification_sha256"), "REHEARSAL_BACKUP_IDENTITY_MISMATCH"),
        (rehearsal.get("source_revision") != source_revision, "REHEARSAL_REVISION_MISMATCH"),
        (not complete, "MIGRATION_REHEARSAL_CONTRACT_INVALID"),
    )
    return [reason for failed, reason in checks if failed]


def _verification_reasons(evidence: VerificationEvidence) -> list[str]:
    fields = (
        "backend_tests_passed",
        "frontend_tests_passed",
        "e2e_tests_passed",
        "migration_tests_passed",
        "load_tests_passed",
        "fault_tests_passed",
        "security_tests_passed",
        "secret_scan_passed",
    )
    reasons = [
        field.upper().replace("_PASSED", "_FAILED")
        for field in fields
        if getattr(evidence, field) is not True
    ]
    if evidence.blocker_review_findings != 0:
        reasons.append("BLOCKER_REVIEW_FINDINGS_REMAIN")
    return reasons


def _runtime_reasons(
    readiness: ReadinessEvidence,
    soak: ShadowSoakEvidence,
    *,
    source_revision: str,
    built_image_digest: Any,
) -> list[str]:
    duration_seconds = soak.ended_at - soak.started_at
    checks = (
        (
            not all(
                (
                    readiness.livez_ok,
                    readiness.healthz_ok,
                    readiness.readyz_ok,
                    readiness.schema_ready,
                    readiness.database_ready,
                )
            ),
            "RUNTIME_READINESS_INCOMPLETE",
        ),
        (readiness.observed_schema_version != CURRENT_RUNTIME_SCHEMA_VERSION, "RUNTIME_SCHEMA_VERSION_MISMATCH"),
        (soak.source_revision != source_revision, "SHADOW_SOAK_REVISION_MISMATCH"),
        (soak.built_image_digest != built_image_digest, "SHADOW_SOAK_IMAGE_MISMATCH"),
        (duration_seconds < MINIMUM_SHADOW_SOAK_SECONDS, "SHADOW_SOAK_DURATION_INSUFFICIENT"),
        (soak.request_error_rate > MAXIMUM_SHADOW_ERROR_RATE, "SHADOW_SOAK_ERROR_RATE_EXCEEDED"),
        (soak.oom_events != 0, "SHADOW_SOAK_OOM_EVENTS_PRESENT"),
        (soak.schema_errors != 0, "SHADOW_SOAK_SCHEMA_ERRORS_PRESENT"),
        (soak.live_order_path_count != 0, "LIVE_ORDER_PATH_PRESENT"),
    )
    return [reason for failed, reason in checks if failed]


def evaluate_deployment_certification(
    request: DeploymentCertificationRequest | dict[str, Any],
) -> dict[str, Any]:
    packet = (
        request
        if isinstance(request, DeploymentCertificationRequest)
        else DeploymentCertificationRequest.model_validate(request)
    )
    provenance = evaluate_deployment_provenance(packet.artifact_provenance)
    backup = packet.backup_certification
    rehearsal = packet.migration_rollback_rehearsal
    reasons = [
        *_provenance_reasons(packet, provenance),
        *_backup_reasons(
            backup,
            expected_source_path=packet.expected_production_database_path,
        ),
        *_rehearsal_reasons(
            rehearsal,
            backup=backup,
            source_revision=packet.source_revision,
        ),
        *_verification_reasons(packet.verification),
        *_runtime_reasons(
            packet.readiness,
            packet.shadow_soak,
            source_revision=packet.source_revision,
            built_image_digest=provenance["links"]["built_image_digest"],
        ),
    ]

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
