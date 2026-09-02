from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts import wfh_council as council


REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / ".agents" / "wfh-council" / "manifest.json"


def test_manifest_is_valid_and_preserves_core_safety_contract() -> None:
    manifest = council.load_manifest(MANIFEST)

    assert council.validate_manifest(REPO, manifest) == []
    assert manifest["routes"]["model_optimization"][0] == "chief_orchestrator"
    assert manifest["production_authority_role"] == "release_certifier"
    assert manifest["protected_invariants"]["live_order_placement"] == "FORBIDDEN"
    assert manifest["protected_invariants"]["live_trading_enabled"] is False


def test_manifest_role_ids_are_unique() -> None:
    manifest = council.load_manifest(MANIFEST)
    ids = [role["id"] for role in manifest["roles"]]
    assert len(ids) == len(set(ids))

def test_manifest_rejects_missing_canonical_skill() -> None:
    manifest = council.load_manifest(MANIFEST)
    broken = copy.deepcopy(manifest)
    broken["roles"][0]["skills"] = ["invented-skill"]

    errors = council.validate_manifest(REPO, broken)

    assert any("invented-skill" in error and "missing canonical skill" in error for error in errors)


def test_model_route_has_required_owners_in_order() -> None:
    manifest = council.load_manifest(MANIFEST)
    route = manifest["routes"]["model_optimization"]

    assert route.index("market_evidence_forensics") < route.index("strategy_owner")
    assert route.index("strategy_owner") < route.index("quant_validation_lead")
    assert route.index("quant_validation_lead") < route.index("false_positive_hunter")
    assert route.index("false_negative_hunter") < route.index("regression_lead")
    assert route[-1] == "release_certifier"


def test_only_release_certifier_has_production_authority() -> None:
    manifest = council.load_manifest(MANIFEST)
    privileged = [role["id"] for role in manifest["roles"] if role.get("production_authority")]

    assert privileged == ["release_certifier"]

def test_route_task_returns_role_skill_packets() -> None:
    manifest = council.load_manifest(MANIFEST)

    packets = council.route_task(manifest, "model_optimization")
    roles = [packet["role"] for packet in packets]

    assert roles[0] == "chief_orchestrator"
    assert roles.index("strategy_owner") < roles.index("quant_validation_lead")
    assert roles[-1] == "release_certifier"
    assert packets[2]["skills"] == ["strategy-score-lifecycle"]


def test_route_task_rejects_unknown_task_type() -> None:
    manifest = council.load_manifest(MANIFEST)

    try:
        council.route_task(manifest, "invented_route")
    except KeyError as exc:
        assert "invented_route" in str(exc)
    else:
        raise AssertionError("unknown route must fail")

def test_doctor_reports_repo_identity_and_optional_unavailable(monkeypatch) -> None:
    real_which = council.shutil.which

    def fake_which(name: str) -> str | None:
        if name == "coderabbit":
            return None
        return real_which(name)

    monkeypatch.setattr(council.shutil, "which", fake_which)
    result = council.doctor(REPO)

    assert result["repo"]["git_sha"]
    assert result["repo"]["status"] == "AVAILABLE"
    assert result["tools"]["git"]["status"] == "AVAILABLE"
    assert result["tools"]["python"]["status"] == "AVAILABLE"
    assert result["tools"]["coderabbit"]["status"] == "UNAVAILABLE"
    assert result["status"] == "READY"
