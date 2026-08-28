from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

import waterfallhunter.core.deployment_certification as deployment_certification_module
from pydantic import ValidationError

from waterfallhunter.core.deployment_certification import (
    MAXIMUM_BACKUP_AGE_SECONDS,
    MAXIMUM_BACKUP_START_BIRTHTIME_SKEW_SECONDS,
    MAXIMUM_READINESS_AGE_SECONDS,
    MAXIMUM_REPORT_VALIDITY_SECONDS,
    MINIMUM_SHADOW_REQUEST_COUNT,
    MINIMUM_SHADOW_SOAK_SECONDS,
    evaluate_deployment_certification,
)
from waterfallhunter.core.github_ci_verification import (
    TrustedCIVerification,
    TrustedCIVerificationError,
)
from waterfallhunter.core.schema_contract import CURRENT_RUNTIME_SCHEMA_VERSION
from waterfallhunter.core.signal_metadata import canonical_sha256
from waterfallhunter.core.sqlite_backup_certification import create_certified_backup
from waterfallhunter.core.migration_rehearsal import rehearse_migration_and_rollback


REVISION = "a" * 40
DIGEST = "sha256:" + "b" * 64
FINGERPRINT = "9" * 64
VERIFICATION_REPORT = "7" * 64


def _hashed(document: dict, field: str) -> dict:
    return {**document, field: canonical_sha256(document)}


def _trusted_ci(**overrides: object) -> dict:
    body = {
        "contract_version": "github_actions_ci_verification_v1",
        "repository": "cavack/wfh",
        "workflow_path": ".github/workflows/ci.yml",
        "run_id": 123,
        "run_attempt": 1,
        "source_revision": REVISION,
        "tested_image_digest": DIGEST,
        "required_job_ids": {
            "backend": 10,
            "frontend": 11,
            "dependency-audit": 12,
            "container-validation": 13,
            "repository-hygiene": 14,
        },
        "critical_steps_sha256": "8" * 64,
    }
    body.update(overrides)
    return {
        **body,
        "verification_report_sha256": canonical_sha256(body),
    }


@pytest.fixture(autouse=True)
def _stub_github_ci_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def resolver(
        *,
        repository: str,
        run_id: int,
        expected_revision: str,
    ) -> TrustedCIVerification:
        assert repository == "cavack/wfh"
        assert run_id == 123
        return TrustedCIVerification.model_validate(
            _trusted_ci(source_revision=expected_revision)
        )

    monkeypatch.setattr(
        deployment_certification_module,
        "resolve_github_ci_verification",
        resolver,
    )


def _evaluate(
    request: dict,
    *,
    now: int | None = None,
) -> dict:
    return evaluate_deployment_certification(
        request,
        now=now,
        github_repository="cavack/wfh",
        github_run_id=123,
    )


def _empty_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=0")


def _request(tmp_path: Path, *, now: int | None = None) -> tuple[dict, int]:
    """Build certification evidence before choosing the evaluation timestamp."""
    source_dir = tmp_path / "source"
    destination_dir = tmp_path / "independent"
    source_dir.mkdir()
    destination_dir.mkdir()
    source = source_dir / "registry.db"
    _empty_database(source)
    backup = create_certified_backup(
        source=source,
        backup=destination_dir / "backup.db",
        restore_target=destination_dir / "restore.db",
        source_failure_domain="production",
        destination_failure_domain="independent",
        enforce_distinct_device=False,
    )
    # Tests cannot allocate independent block devices; keep the real artifact and
    # hash-bind the production-required device-separation claim separately.
    backup = _hashed(
        {
            **{
                key: value
                for key, value in backup.items()
                if key != "certification_sha256"
            },
            "device_separation_enforced": True,
        },
        "certification_sha256",
    )
    rehearsal = rehearse_migration_and_rollback(
        backup_certification=backup,
        migration_target=(destination_dir / "migration.db").resolve(),
        rollback_target=(destination_dir / "rollback.db").resolve(),
        source_revision=REVISION,
    )
    observed_now = int(time.time() if now is None else now)
    request = {
        "source_revision": REVISION,
        "ci_revision": REVISION,
        "expected_production_database_path": str(source.resolve()),
        "artifact_provenance": {
            "git_sha": REVISION,
            "dependency_lock_sha256": "c" * 64,
            "dockerfile_sha256": "d" * 64,
            "base_image_digest": DIGEST,
            "built_image_digest": DIGEST,
            "tested_image_digest": DIGEST,
            "deployment_manifest_sha256": "e" * 64,
            "running_image_digest": DIGEST,
            "runtime_fingerprint_sha256": FINGERPRINT,
        },
        "backup_certification": backup,
        "migration_rollback_rehearsal": rehearsal,
        "verification": {
            "source_revision": REVISION,
            "tested_image_digest": DIGEST,
            "verification_report_sha256": _trusted_ci()["verification_report_sha256"],
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
            "source_revision": REVISION,
            "running_image_digest": DIGEST,
            "runtime_fingerprint_sha256": FINGERPRINT,
            "environment": "STAGING_SHADOW",
            "observed_at": observed_now - 60,
            "livez_ok": True,
            "healthz_ok": True,
            "readyz_ok": True,
            "schema_ready": True,
            "database_ready": True,
            "observed_schema_version": CURRENT_RUNTIME_SCHEMA_VERSION,
        },
        "shadow_soak": {
            "source_revision": REVISION,
            "built_image_digest": DIGEST,
            "runtime_fingerprint_sha256": FINGERPRINT,
            "environment": "STAGING_SHADOW",
            "started_at": observed_now - 100_000,
            "ended_at": observed_now - 10_000,
            "request_count": MINIMUM_SHADOW_REQUEST_COUNT,
            "request_error_rate": 0,
            "oom_events": 0,
            "schema_errors": 0,
            "live_order_path_count": 0,
            "paper_only": True,
        },
    }
    return request, observed_now


def test_complete_evidence_is_only_ready_for_explicit_owner_approval(
    tmp_path: Path,
) -> None:
    request, observed_now = _request(tmp_path)
    report = _evaluate(request, now=observed_now)

    assert report["status"] == "READY_FOR_EXPLICIT_OWNER_APPROVAL"
    assert report["blocking_reasons"] == []
    assert report["deployment_allowed"] is False
    assert report["migration_allowed"] is False
    assert report["live_trading_allowed"] is False
    assert report["evaluated_at"] == observed_now
    assert report["valid_until"] > report["evaluated_at"]
    assert report["valid_until"] <= observed_now + MAXIMUM_REPORT_VALIDITY_SECONDS
    assert report["valid_until"] <= (
        request["readiness"]["observed_at"] + MAXIMUM_READINESS_AGE_SECONDS
    )
    report_body = {
        key: value for key, value in report.items() if key != "report_sha256"
    }
    assert report["report_sha256"] == canonical_sha256(report_body)


def test_missing_backup_soak_and_test_evidence_fails_closed(tmp_path: Path) -> None:
    request, observed_now = _request(tmp_path)
    request["backup_certification"]["status"] = "MISSING"
    request["verification"]["fault_tests_passed"] = False
    request["shadow_soak"]["ended_at"] = request["shadow_soak"]["started_at"] + 3_600
    request["shadow_soak"]["oom_events"] = 1

    report = _evaluate(request, now=observed_now)

    assert report["status"] == "NOT_READY"
    assert "BACKUP_CERTIFICATION_HASH_INVALID" in report["blocking_reasons"]
    assert "INDEPENDENT_BACKUP_RESTORE_NOT_CERTIFIED" in report["blocking_reasons"]
    assert "FAULT_TESTS_FAILED" in report["blocking_reasons"]
    assert "SHADOW_SOAK_DURATION_INSUFFICIENT" in report["blocking_reasons"]
    assert "SHADOW_SOAK_OOM_EVENTS_PRESENT" in report["blocking_reasons"]
    assert report["deployment_allowed"] is False


def test_schema_source_and_soak_identity_are_bound_to_certified_artifact(
    tmp_path: Path,
) -> None:
    request, observed_now = _request(tmp_path)
    request["readiness"]["observed_schema_version"] = 1
    request["expected_production_database_path"] = "/var/lib/wfh/wrong.db"
    request["shadow_soak"]["source_revision"] = "0" * 40
    request["shadow_soak"]["built_image_digest"] = "sha256:" + "0" * 64

    report = _evaluate(request, now=observed_now)

    assert "RUNTIME_SCHEMA_VERSION_MISMATCH" in report["blocking_reasons"]
    assert "BACKUP_SOURCE_IDENTITY_MISMATCH" in report["blocking_reasons"]
    assert "SHADOW_SOAK_REVISION_MISMATCH" in report["blocking_reasons"]
    assert "SHADOW_SOAK_IMAGE_MISMATCH" in report["blocking_reasons"]


def test_pass_evidence_rejects_coerced_booleans(tmp_path: Path) -> None:
    request, _observed_now = _request(tmp_path)
    request["verification"]["backend_tests_passed"] = 1

    with pytest.raises(ValidationError):
        _evaluate(request)


def test_shadow_soak_runtime_fingerprint_must_match_provenance(
    tmp_path: Path,
) -> None:
    request, observed_now = _request(tmp_path)
    request["shadow_soak"]["runtime_fingerprint_sha256"] = "0" * 64

    report = _evaluate(request, now=observed_now)

    assert "SHADOW_SOAK_RUNTIME_FINGERPRINT_MISMATCH" in report["blocking_reasons"]
    assert report["status"] == "NOT_READY"


def test_post_migration_audit_schema_must_match_runtime_contract(
    tmp_path: Path,
) -> None:
    request, observed_now = _request(tmp_path)
    mismatched = dict(request["migration_rollback_rehearsal"]["post_migration_audit"])
    mismatched["user_version"] = CURRENT_RUNTIME_SCHEMA_VERSION - 1
    mismatched.pop("audit_sha256", None)
    request["migration_rollback_rehearsal"]["post_migration_audit"] = _hashed(
        mismatched,
        "audit_sha256",
    )
    request["migration_rollback_rehearsal"] = _hashed(
        {
            key: value
            for key, value in request["migration_rollback_rehearsal"].items()
            if key != "rehearsal_sha256"
        },
        "rehearsal_sha256",
    )

    report = _evaluate(request, now=observed_now)

    assert "POST_MIGRATION_SCHEMA_VERSION_MISMATCH" in report["blocking_reasons"]
    assert report["status"] == "NOT_READY"


def test_deployment_certification_revalidates_backup_artifact(tmp_path: Path) -> None:
    request, observed_now = _request(tmp_path)
    backup_path = Path(request["backup_certification"]["backup_path"])
    with sqlite3.connect(backup_path) as connection:
        connection.execute("CREATE TABLE tamper(id INTEGER PRIMARY KEY)")
        connection.commit()

    report = _evaluate(request, now=observed_now)

    assert "BACKUP_ARTIFACT_TAMPERED" in report["blocking_reasons"]
    assert report["status"] == "NOT_READY"


def test_deployment_certification_rejects_unreadable_backup_bytes(
    tmp_path: Path,
) -> None:
    request, observed_now = _request(tmp_path)
    Path(request["backup_certification"]["backup_path"]).write_bytes(b"tampered")

    report = _evaluate(request, now=observed_now)

    assert "BACKUP_ARTIFACT_UNREADABLE" in report["blocking_reasons"]
    assert report["status"] == "NOT_READY"


def test_deployment_certification_rejects_missing_backup_artifact(
    tmp_path: Path,
) -> None:
    request, observed_now = _request(tmp_path)
    Path(request["backup_certification"]["backup_path"]).unlink()

    report = _evaluate(request, now=observed_now)

    assert "BACKUP_ARTIFACT_UNREADABLE" in report["blocking_reasons"]
    assert report["status"] == "NOT_READY"


def test_readiness_must_bind_running_artifact_and_freshness(tmp_path: Path) -> None:
    request, observed_now = _request(tmp_path)
    request["readiness"]["source_revision"] = "0" * 40
    request["readiness"]["running_image_digest"] = "sha256:" + "0" * 64
    request["readiness"]["runtime_fingerprint_sha256"] = "0" * 64
    request["readiness"]["observed_at"] = observed_now - MAXIMUM_READINESS_AGE_SECONDS - 1

    report = _evaluate(request, now=observed_now)

    assert "READINESS_REVISION_MISMATCH" in report["blocking_reasons"]
    assert "READINESS_IMAGE_MISMATCH" in report["blocking_reasons"]
    assert "READINESS_RUNTIME_FINGERPRINT_MISMATCH" in report["blocking_reasons"]
    assert "READINESS_EVIDENCE_STALE" in report["blocking_reasons"]
    assert report["status"] == "NOT_READY"


def test_stale_backup_certificate_is_rejected(tmp_path: Path) -> None:
    request, observed_now = _request(tmp_path)
    body = {
        key: value
        for key, value in request["backup_certification"].items()
        if key != "certification_sha256"
    }
    body["backup_started_at"] = observed_now - MAXIMUM_BACKUP_AGE_SECONDS - 120
    body["backup_completed_at"] = observed_now - MAXIMUM_BACKUP_AGE_SECONDS - 60
    request["backup_certification"] = _hashed(body, "certification_sha256")
    request["migration_rollback_rehearsal"] = _hashed(
        {
            **{
                key: value
                for key, value in request["migration_rollback_rehearsal"].items()
                if key != "rehearsal_sha256"
            },
            "backup_certification_sha256": request["backup_certification"][
                "certification_sha256"
            ],
        },
        "rehearsal_sha256",
    )

    report = _evaluate(request, now=observed_now)

    assert "BACKUP_EVIDENCE_STALE" in report["blocking_reasons"]
    assert report["status"] == "NOT_READY"


def test_shadow_soak_ending_in_future_is_rejected(tmp_path: Path) -> None:
    request, observed_now = _request(tmp_path)
    request["shadow_soak"]["ended_at"] = observed_now + 1
    request["shadow_soak"]["started_at"] = (
        request["shadow_soak"]["ended_at"] - MINIMUM_SHADOW_SOAK_SECONDS
    )

    report = _evaluate(request, now=observed_now)

    assert report["status"] == "NOT_READY"
    assert "SHADOW_SOAK_ENDED_IN_FUTURE" in report["blocking_reasons"]


def test_shadow_soak_requires_minimum_traffic(tmp_path: Path) -> None:
    request, observed_now = _request(tmp_path)
    request["shadow_soak"]["request_count"] = MINIMUM_SHADOW_REQUEST_COUNT - 1

    report = _evaluate(request, now=observed_now)

    assert report["status"] == "NOT_READY"
    assert "SHADOW_SOAK_TRAFFIC_INSUFFICIENT" in report["blocking_reasons"]


def test_report_validity_is_bounded_by_freshness_evidence(tmp_path: Path) -> None:
    request, observed_now = _request(tmp_path)

    report = _evaluate(request, now=observed_now)

    assert report["evaluated_at"] == observed_now
    assert report["valid_until"] == min(
        observed_now + MAXIMUM_REPORT_VALIDITY_SECONDS,
        request["readiness"]["observed_at"] + MAXIMUM_READINESS_AGE_SECONDS,
        request["backup_certification"]["backup_completed_at"]
        + MAXIMUM_BACKUP_AGE_SECONDS,
    )


def test_migration_rehearsal_artifact_is_revalidated(tmp_path: Path) -> None:
    request, observed_now = _request(tmp_path)
    migration_target = Path(
        request["migration_rollback_rehearsal"]["migration_target"]
    )

    with sqlite3.connect(migration_target) as connection:
        connection.execute(
            "CREATE TABLE certification_tamper_probe(id INTEGER PRIMARY KEY)"
        )

    report = _evaluate(request, now=observed_now)

    assert report["status"] == "NOT_READY"
    assert (
        "MIGRATION_REHEARSAL_ARTIFACT_TAMPERED"
        in report["blocking_reasons"]
    )


def test_missing_rollback_rehearsal_artifact_is_rejected(
    tmp_path: Path,
) -> None:
    request, observed_now = _request(tmp_path)
    rollback_target = Path(
        request["migration_rollback_rehearsal"]["rollback_target"]
    )
    rollback_target.unlink()

    report = _evaluate(request, now=observed_now)

    assert report["status"] == "NOT_READY"
    assert (
        "ROLLBACK_REHEARSAL_ARTIFACT_UNREADABLE"
        in report["blocking_reasons"]
    )


def test_backup_timestamp_relabel_is_rejected_by_artifact_birthtime(
    tmp_path: Path,
) -> None:
    request, observed_now = _request(tmp_path)

    body = {
        key: value
        for key, value in request["backup_certification"].items()
        if key != "certification_sha256"
    }

    body["backup_started_at"] = (
        observed_now
        - MAXIMUM_BACKUP_START_BIRTHTIME_SKEW_SECONDS
        - 600
    )
    body["backup_completed_at"] = body["backup_started_at"] + 1

    request["backup_certification"] = _hashed(
        body,
        "certification_sha256",
    )

    request["migration_rollback_rehearsal"] = _hashed(
        {
            **{
                key: value
                for key, value in request[
                    "migration_rollback_rehearsal"
                ].items()
                if key != "rehearsal_sha256"
            },
            "backup_certification_sha256": request[
                "backup_certification"
            ]["certification_sha256"],
        },
        "rehearsal_sha256",
    )

    report = _evaluate(
        request,
        now=observed_now,
    )

    assert report["status"] == "NOT_READY"
    assert (
        "BACKUP_TIMESTAMP_ARTIFACT_MISMATCH"
        in report["blocking_reasons"]
    )


def test_verification_fails_closed_without_trusted_ci(
    tmp_path: Path,
) -> None:
    request, observed_now = _request(tmp_path)

    report = evaluate_deployment_certification(
        request,
        now=observed_now,
    )

    assert report["status"] == "NOT_READY"
    assert (
        "CI_VERIFICATION_TRUST_UNAVAILABLE"
        in report["blocking_reasons"]
    )


def test_trusted_ci_report_hash_must_match_packet(
    tmp_path: Path,
) -> None:
    request, observed_now = _request(tmp_path)
    request["verification"]["verification_report_sha256"] = "0" * 64

    report = _evaluate(request, now=observed_now)

    assert report["status"] == "NOT_READY"
    assert "CI_VERIFICATION_REPORT_MISMATCH" in report["blocking_reasons"]


def test_trusted_ci_resolution_failure_blocks_certification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, observed_now = _request(tmp_path)

    def failed_resolver(**_kwargs: object) -> TrustedCIVerification:
        raise TrustedCIVerificationError("GITHUB_REQUIRED_CI_JOB_FAILED")

    monkeypatch.setattr(
        deployment_certification_module,
        "resolve_github_ci_verification",
        failed_resolver,
    )

    report = _evaluate(request, now=observed_now)

    assert report["status"] == "NOT_READY"
    assert "GITHUB_REQUIRED_CI_JOB_FAILED" in report["blocking_reasons"]


def test_verification_evidence_must_bind_revision_and_tested_image(
    tmp_path: Path,
) -> None:
    request, observed_now = _request(tmp_path)
    request["verification"]["source_revision"] = "0" * 40
    request["verification"]["tested_image_digest"] = "sha256:" + "0" * 64

    report = _evaluate(request, now=observed_now)

    assert "VERIFICATION_REVISION_MISMATCH" in report["blocking_reasons"]
    assert "VERIFICATION_IMAGE_MISMATCH" in report["blocking_reasons"]
    assert report["status"] == "NOT_READY"
