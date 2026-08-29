from __future__ import annotations

import pytest

import waterfallhunter.core.github_remote_restore_verification as verifier


def test_independent_restore_verification_binds_exact_run_artifact_and_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_gh_json(endpoint: str) -> dict:
        if endpoint.endswith("/artifacts"):
            return {
                "artifacts": [{
                    "id": 456,
                    "name": "restore-verification-wfh-dr-test",
                    "expired": False,
                    "digest": "sha256:" + "b" * 64,
                }]
            }
        return {
            "id": 123,
            "name": "Verify or restore encrypted DR backup",
            "path": ".github/workflows/restore.yml",
            "head_branch": "main",
            "head_sha": "add3f01cf3b9f3e55d735294dae99d5a5792b5c2",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "repository": {"full_name": "cavack/wfh-dr"},
            "updated_at": "2026-08-28T22:38:34Z",
        }

    monkeypatch.setattr(verifier, "_gh_json", fake_gh_json)
    monkeypatch.setattr(verifier, "_download_report", lambda **_kwargs: {
        "ok": True,
        "status": "RESTORE_VERIFIED",
        "file_sha256": "c" * 64,
        "file_size_bytes": 4096,
        "integrity_check": "ok",
        "foreign_key_violation_count": 0,
        "user_version": 5,
    })

    result = verifier.resolve_github_independent_restore_verification(
        repository="cavack/wfh-dr",
        run_id=123,
        release_tag="wfh-dr-test",
        expected_plaintext_sha256="c" * 64,
        expected_plaintext_size_bytes=4096,
        expected_user_version=5,
    )

    assert result.github_host == "github.com"
    assert result.workflow_revision == "add3f01cf3b9f3e55d735294dae99d5a5792b5c2"
    assert result.artifact_id == 456
    assert result.restore_file_sha256 == "c" * 64
    assert len(result.verification_report_sha256) == 64


def test_independent_restore_verification_rejects_wrong_restored_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verifier, "_gh_json", lambda endpoint: (
        {"artifacts": [{
            "id": 456,
            "name": "restore-verification-wfh-dr-test",
            "expired": False,
            "digest": "sha256:" + "b" * 64,
        }]}
        if endpoint.endswith("/artifacts")
        else {
            "id": 123,
            "name": "Verify or restore encrypted DR backup",
            "path": ".github/workflows/restore.yml",
            "head_branch": "main",
            "head_sha": "add3f01cf3b9f3e55d735294dae99d5a5792b5c2",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "repository": {"full_name": "cavack/wfh-dr"},
            "updated_at": "2026-08-28T22:38:34Z",
        }
    ))
    monkeypatch.setattr(verifier, "_download_report", lambda **_kwargs: {
        "ok": True,
        "status": "RESTORE_VERIFIED",
        "file_sha256": "d" * 64,
        "file_size_bytes": 4096,
        "integrity_check": "ok",
        "foreign_key_violation_count": 0,
        "user_version": 5,
    })

    with pytest.raises(
        verifier.TrustedIndependentRestoreVerificationError,
        match="INDEPENDENT_RESTORE_REPORT_MISMATCH",
    ):
        verifier.resolve_github_independent_restore_verification(
            repository="cavack/wfh-dr",
            run_id=123,
            release_tag="wfh-dr-test",
            expected_plaintext_sha256="c" * 64,
            expected_plaintext_size_bytes=4096,
            expected_user_version=5,
        )


def test_independent_restore_verification_rejects_unapproved_workflow_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verifier, "_gh_json", lambda endpoint: (
        {"artifacts": [{
            "id": 456,
            "name": "restore-verification-wfh-dr-test",
            "expired": False,
            "digest": "sha256:" + "b" * 64,
        }]}
        if endpoint.endswith("/artifacts")
        else {
            "id": 123,
            "name": "Verify or restore encrypted DR backup",
            "path": ".github/workflows/restore.yml",
            "head_branch": "main",
            "head_sha": "f" * 40,
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "repository": {"full_name": "cavack/wfh-dr"},
            "updated_at": "2026-08-28T22:38:34Z",
        }
    ))
    monkeypatch.setattr(verifier, "_download_report", lambda **_kwargs: {
        "ok": True,
        "status": "RESTORE_VERIFIED",
        "file_sha256": "c" * 64,
        "file_size_bytes": 4096,
        "integrity_check": "ok",
        "foreign_key_violation_count": 0,
        "user_version": 5,
    })

    with pytest.raises(
        verifier.TrustedIndependentRestoreVerificationError,
        match="INDEPENDENT_RESTORE_WORKFLOW_REVISION_NOT_TRUSTED",
    ):
        verifier.resolve_github_independent_restore_verification(
            repository="cavack/wfh-dr",
            run_id=123,
            release_tag="wfh-dr-test",
            expected_plaintext_sha256="c" * 64,
            expected_plaintext_size_bytes=4096,
            expected_user_version=5,
        )


def test_independent_restore_translates_untrusted_gh_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from waterfallhunter.core.github_release_backup_verification import (
        TrustedRemoteBackupVerificationError,
    )

    def unavailable() -> str:
        raise TrustedRemoteBackupVerificationError("GITHUB_CLI_UNAVAILABLE_OR_UNTRUSTED")

    monkeypatch.setattr(verifier, "_gh_executable", unavailable)
    with pytest.raises(
        verifier.TrustedIndependentRestoreVerificationError,
        match="INDEPENDENT_RESTORE_GITHUB_CLI_UNTRUSTED",
    ):
        verifier._gh_json("repos/cavack/wfh-dr/actions/runs/123")
