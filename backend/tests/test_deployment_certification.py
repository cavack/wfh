from __future__ import annotations

from waterfallhunter.core.deployment_certification import (
    evaluate_deployment_certification,
)
from waterfallhunter.core.signal_metadata import canonical_sha256


REVISION = "a" * 40
DIGEST = "sha256:" + "b" * 64


def _hashed(document: dict, field: str) -> dict:
    return {**document, field: canonical_sha256(document)}


def _request() -> dict:
    backup = _hashed(
        {
            "contract_version": "sqlite_backup_certification_v1",
            "status": "BACKUP_RESTORE_CERTIFIED",
            "source_failure_domain": "production",
            "destination_failure_domain": "independent",
            "device_separation_enforced": True,
        },
        "certification_sha256",
    )
    rehearsal = _hashed(
        {
            "contract_version": "sqlite_migration_rollback_rehearsal_v1",
            "status": "MIGRATION_AND_ROLLBACK_REHEARSED",
            "source_revision": REVISION,
            "backup_certification_sha256": backup["certification_sha256"],
        },
        "rehearsal_sha256",
    )
    return {
        "source_revision": REVISION,
        "ci_revision": REVISION,
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
            "expected_schema_version": 5,
            "observed_schema_version": 5,
        },
        "shadow_soak": {
            "duration_seconds": 86_400,
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
    request["shadow_soak"]["duration_seconds"] = 3_600
    request["shadow_soak"]["oom_events"] = 1

    report = evaluate_deployment_certification(request)

    assert report["status"] == "NOT_READY"
    assert "BACKUP_CERTIFICATION_HASH_INVALID" in report["blocking_reasons"]
    assert "INDEPENDENT_BACKUP_RESTORE_NOT_CERTIFIED" in report["blocking_reasons"]
    assert "FAULT_TESTS_FAILED" in report["blocking_reasons"]
    assert "SHADOW_SOAK_DURATION_INSUFFICIENT" in report["blocking_reasons"]
    assert "SHADOW_SOAK_OOM_EVENTS_PRESENT" in report["blocking_reasons"]
    assert report["deployment_allowed"] is False
