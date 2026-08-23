from __future__ import annotations

import pytest
from pydantic import ValidationError

from waterfallhunter.core.deployment_certification import (
    evaluate_deployment_certification,
)
from waterfallhunter.core.signal_metadata import canonical_sha256


REVISION = "a" * 40
DIGEST = "sha256:" + "b" * 64
DATABASE_PATH = "/var/lib/wfh/waterfall_registry.db"


def _hashed(document: dict, field: str) -> dict:
    return {**document, field: canonical_sha256(document)}


def _audit(*, file_sha256: str, schema_version: int = 5) -> dict:
    return _hashed(
        {
            "contract_version": "sqlite_snapshot_audit_v1",
            "file_sha256": file_sha256,
            "file_size_bytes": 4_096,
            "integrity_check": "ok",
            "foreign_key_violation_count": 0,
            "user_version": schema_version,
            "schema_version": schema_version,
            "object_counts": {"table": 1, "index": 0, "trigger": 0, "view": 0},
            "table_counts": {"signals": 10},
            "schema_sha256": "f" * 64,
            "logical_content_sha256": "8" * 64,
        },
        "audit_sha256",
    )


def _request() -> dict:
    backup_audit = _audit(file_sha256="1" * 64)
    restore_audit = _audit(file_sha256="2" * 64)
    backup = _hashed(
        {
            "contract_version": "sqlite_backup_certification_v1",
            "status": "BACKUP_RESTORE_CERTIFIED",
            "source_path": DATABASE_PATH,
            "source_identity": {"device_id": 1, "inode": 2},
            "source_failure_domain": "production",
            "destination_failure_domain": "independent",
            "device_separation_enforced": True,
            "backup_path": "/independent/backup.db",
            "restore_target_path": "/independent/restore.db",
            "backup_audit": backup_audit,
            "restore_audit": restore_audit,
            "restore_matches_backup": True,
            "rollback_source_sha256": backup_audit["file_sha256"],
            "production_migration_authorized": False,
            "production_deployment_authorized": False,
        },
        "certification_sha256",
    )
    rehearsal = _hashed(
        {
            "contract_version": "sqlite_migration_rollback_rehearsal_v1",
            "status": "MIGRATION_AND_ROLLBACK_REHEARSED",
            "source_revision": REVISION,
            "backup_certification_sha256": backup["certification_sha256"],
            "baseline_audit_sha256": backup_audit["audit_sha256"],
            "migration_target": "/independent/migration.db",
            "migration_result": {"ok": True, "user_version": 5},
            "post_migration_audit": _audit(file_sha256="3" * 64),
            "rollback_target": "/independent/rollback.db",
            "rollback_audit": _audit(file_sha256="4" * 64),
            "rollback_matches_baseline": True,
            "production_migration_authorized": False,
            "production_deployment_authorized": False,
        },
        "rehearsal_sha256",
    )
    return {
        "source_revision": REVISION,
        "ci_revision": REVISION,
        "expected_production_database_path": DATABASE_PATH,
        "artifact_provenance": {
            "git_sha": REVISION,
            "dependency_lock_sha256": "c" * 64,
            "dockerfile_sha256": "d" * 64,
            "base_image_digest": DIGEST,
            "built_image_digest": DIGEST,
            "tested_image_digest": DIGEST,
            "deployment_manifest_sha256": "e" * 64,
            "running_image_digest": DIGEST,
        },
        "backup_certification": backup,
        "migration_rollback_rehearsal": rehearsal,
        "verification": {
            "backend_tests_passed": True,
            "frontend_tests_passed": True,
            "e2e_tests_passed": True,
            "migration_tests_passed": True,
            "load_tests_passed": True,
            "fault_tests_passed": True,
            "security_tests_passed": True,
            "secret_scan_passed": True,
            "blocker_review_findings": 0,
        },
        "readiness": {
            "livez_ok": True,
            "healthz_ok": True,
            "readyz_ok": True,
            "schema_ready": True,
            "database_ready": True,
            "observed_schema_version": 5,
        },
        "shadow_soak": {
            "source_revision": REVISION,
            "built_image_digest": DIGEST,
            "runtime_fingerprint_sha256": "9" * 64,
            "environment": "STAGING_SHADOW",
            "started_at": 1_000_000,
            "ended_at": 1_086_400,
            "request_error_rate": 0,
            "oom_events": 0,
            "schema_errors": 0,
            "live_order_path_count": 0,
            "paper_only": True,
        },
    }


def test_complete_evidence_is_only_ready_for_explicit_owner_approval() -> None:
    report = evaluate_deployment_certification(_request())

    assert report["status"] == "READY_FOR_EXPLICIT_OWNER_APPROVAL"
    assert report["blocking_reasons"] == []
    assert report["deployment_allowed"] is False
    assert report["migration_allowed"] is False
    assert report["live_trading_allowed"] is False
    assert len(report["report_sha256"]) == 64


def test_missing_backup_soak_and_test_evidence_fails_closed() -> None:
    request = _request()
    request["backup_certification"]["status"] = "MISSING"
    request["verification"]["fault_tests_passed"] = False
    request["shadow_soak"]["ended_at"] = request["shadow_soak"]["started_at"] + 3_600
    request["shadow_soak"]["oom_events"] = 1

    report = evaluate_deployment_certification(request)

    assert report["status"] == "NOT_READY"
    assert "BACKUP_CERTIFICATION_HASH_INVALID" in report["blocking_reasons"]
    assert "INDEPENDENT_BACKUP_RESTORE_NOT_CERTIFIED" in report["blocking_reasons"]
    assert "FAULT_TESTS_FAILED" in report["blocking_reasons"]
    assert "SHADOW_SOAK_DURATION_INSUFFICIENT" in report["blocking_reasons"]
    assert "SHADOW_SOAK_OOM_EVENTS_PRESENT" in report["blocking_reasons"]
    assert report["deployment_allowed"] is False


def test_schema_source_and_soak_identity_are_bound_to_certified_artifact() -> None:
    request = _request()
    request["readiness"]["observed_schema_version"] = 1
    request["expected_production_database_path"] = "/var/lib/wfh/wrong.db"
    request["shadow_soak"]["source_revision"] = "0" * 40
    request["shadow_soak"]["built_image_digest"] = "sha256:" + "0" * 64

    report = evaluate_deployment_certification(request)

    assert "RUNTIME_SCHEMA_VERSION_MISMATCH" in report["blocking_reasons"]
    assert "BACKUP_SOURCE_IDENTITY_MISMATCH" in report["blocking_reasons"]
    assert "SHADOW_SOAK_REVISION_MISMATCH" in report["blocking_reasons"]
    assert "SHADOW_SOAK_IMAGE_MISMATCH" in report["blocking_reasons"]


def test_pass_evidence_rejects_coerced_booleans() -> None:
    request = _request()
    request["verification"]["backend_tests_passed"] = 1

    with pytest.raises(ValidationError):
        evaluate_deployment_certification(request)
