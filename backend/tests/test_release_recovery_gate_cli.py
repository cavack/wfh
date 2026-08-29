from __future__ import annotations

import json
import sys

from scripts import evaluate_release_recovery_gate as cli


def _run_cli(tmp_path, monkeypatch, *, status: str) -> tuple[int, dict, dict]:
    production_db = tmp_path / "production.db"
    production_db.write_bytes(b"sqlite-placeholder")
    backup_path = tmp_path / "backup-certification.json"
    restore_path = tmp_path / "independent-restore-verification.json"
    rehearsal_path = tmp_path / "migration-rehearsal.json"
    report_path = tmp_path / "recovery-report.json"
    backup = {"certification_sha256": "b" * 64}
    restore = {"verification_report_sha256": "c" * 64}
    rehearsal = {"rehearsal_sha256": "d" * 64}
    backup_path.write_text(json.dumps(backup), encoding="utf-8")
    restore_path.write_text(json.dumps(restore), encoding="utf-8")
    rehearsal_path.write_text(json.dumps(rehearsal), encoding="utf-8")
    expected = {
        "contract_version": "release_recovery_gate_report_v1",
        "status": status,
        "blocking_reasons": [] if status == "READY_FOR_EXPLICIT_DISPATCH" else ["BLOCKED"],
        "report_sha256": "f" * 64,
        "deployment_allowed": False,
    }
    observed_payload: dict = {}

    def fake_evaluate(payload, **_kwargs):
        observed_payload.update(payload)
        return expected

    monkeypatch.setattr(cli, "evaluate_release_recovery_gate", fake_evaluate)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_release_recovery_gate.py",
            "--source-revision",
            "a" * 40,
            "--production-database",
            str(production_db),
            "--backup-certification",
            str(backup_path),
            "--independent-restore-verification",
            str(restore_path),
            "--migration-rehearsal",
            str(rehearsal_path),
            "--report",
            str(report_path),
            "--github-repository",
            "cavack/wfh",
            "--github-run-id",
            "123",
        ],
    )
    exit_code = cli.main()
    return (
        exit_code,
        json.loads(report_path.read_text(encoding="utf-8")),
        observed_payload,
    )


def test_recovery_gate_cli_builds_minimal_request_and_writes_ready_report(
    tmp_path,
    monkeypatch,
) -> None:
    exit_code, report, payload = _run_cli(
        tmp_path,
        monkeypatch,
        status="READY_FOR_EXPLICIT_DISPATCH",
    )
    assert exit_code == 0
    assert report["status"] == "READY_FOR_EXPLICIT_DISPATCH"
    assert payload["contract_version"] == "release_recovery_gate_request_v1"
    assert payload["source_revision"] == "a" * 40
    assert payload["backup_certification"]["certification_sha256"] == "b" * 64
    assert payload["independent_restore_verification"]["verification_report_sha256"] == "c" * 64
    assert payload["migration_rollback_rehearsal"]["rehearsal_sha256"] == "d" * 64
    assert "readiness" not in payload
    assert "shadow_soak" not in payload


def test_recovery_gate_cli_returns_two_for_not_ready(tmp_path, monkeypatch) -> None:
    exit_code, report, _payload = _run_cli(tmp_path, monkeypatch, status="NOT_READY")
    assert exit_code == 2
    assert report["blocking_reasons"] == ["BLOCKED"]
