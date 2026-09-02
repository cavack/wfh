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
    def fake_git_output(repo_root: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return "abc123"
        if args == ("branch", "--show-current"):
            return "test-branch"
        raise AssertionError(args)

    def fake_which(name: str) -> str | None:
        if name == "git":
            return "/usr/bin/git"
        if name == "python3":
            return "/usr/bin/python3"
        return None

    monkeypatch.setattr(council, "_git_output", fake_git_output)
    monkeypatch.setattr(council.shutil, "which", fake_which)
    result = council.doctor(REPO)

    assert result["repo"]["git_sha"] == "abc123"
    assert result["repo"]["branch"] == "test-branch"
    assert result["repo"]["status"] == "AVAILABLE"
    assert result["tools"]["git"]["status"] == "AVAILABLE"
    assert result["tools"]["python"]["status"] == "AVAILABLE"
    assert result["tools"]["coderabbit"]["status"] == "UNAVAILABLE"
    assert result["status"] == "READY"

def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_research_snapshot_refuses_sparse_development_evidence(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "DATASET_AUDIT.json",
        {
            "contract": "DATASET_AUDIT.v1",
            "evidence_tier": "TIER_2_DEVELOPMENT_GRADE_NOT_PROMOTION_EVIDENCE",
            "data_sha256": "abc",
            "rows": 204338,
            "episodes": 773,
            "symbols": 281,
            "span_days": 15.9,
            "limitations": ["Tier-2 causal reconstruction is development-only"],
        },
    )
    _write_json(
        tmp_path / "OOS_VALIDATION.json",
        {
            "contract": "OOS_VALIDATION.v1",
            "status": "BLOCKED_NOT_RUN_AS_SELECTION_EVIDENCE",
            "maximum_complete_outcomes_any_stage2_config": 2,
            "reason": "insufficient promotion evidence",
        },
    )
    _write_json(
        tmp_path / "BEST_DEVELOPMENT_CONFIG.json",
        {
            "contract": "BEST_DEVELOPMENT_CONFIG.v1",
            "status": "NO_SCIENTIFIC_CHAMPION",
            "promotion_allowed": False,
            "maximum_complete_outcomes_any_stage2_config": 2,
            "reasons": ["Tier-2 dataset only"],
        },
    )
    _write_json(
        tmp_path / "PRODUCTION_VS_CHALLENGERS.json",
        {"contract": "PRODUCTION_VS_CHALLENGERS.v1", "promotion_allowed": False},
    )
    _write_json(
        tmp_path / "OUTCOME_INTEGRITY.json",
        {
            "contract": "OUTCOME_INTEGRITY.v1",
            "outcome_complete": 210,
            "unavailable": 580,
            "net_cost_adjusted_r_available": False,
            "limitations": ["gross_r is not net"],
        },
    )

    summary = council.summarize_research_evidence(tmp_path)

    assert summary["promotion_disposition"] == "NO_PROMOTION_EVIDENCE"
    assert "insufficient_oos_evidence" in summary["blockers"]
    assert "insufficient_promotion_span" in summary["blockers"]
    assert "missing_net_cost_adjusted_r" in summary["blockers"]
    assert summary["dataset"]["span_days"] == 15.9
    assert summary["dataset"]["data_sha256"] == "abc"

def test_research_snapshot_marks_missing_artifacts_without_guessing(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "DATASET_AUDIT.json",
        {"contract": "DATASET_AUDIT.v1", "span_days": 60.0},
    )

    summary = council.summarize_research_evidence(tmp_path)

    assert summary["promotion_disposition"] == "NO_PROMOTION_EVIDENCE"
    assert summary["artifacts"]["OOS_VALIDATION.json"]["status"] == "MISSING_ARTIFACT"
    assert "insufficient_oos_evidence" in summary["blockers"]

def test_research_snapshot_cli_emits_json(tmp_path: Path, capsys) -> None:
    _write_json(
        tmp_path / "DATASET_AUDIT.json",
        {"contract": "DATASET_AUDIT.v1", "span_days": 10.0},
    )

    rc = council.main(
        [
            "--repo-root",
            str(REPO),
            "research-snapshot",
            "--research-dir",
            str(tmp_path),
            "--json",
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert output["promotion_disposition"] == "NO_PROMOTION_EVIDENCE"

def test_council_docs_cover_every_role_and_tool_class() -> None:
    manifest = council.load_manifest(MANIFEST)
    council_doc = (REPO / ".agents/wfh-council/COUNCIL.md").read_text(encoding="utf-8")
    tools_doc = (REPO / ".agents/wfh-council/TOOLS.md").read_text(encoding="utf-8")

    for role in manifest["roles"]:
        assert role["id"] in council_doc
    for tool_class in [*manifest["tools"]["required"], *manifest["tools"]["optional"]]:
        assert tool_class in tools_doc


def test_research_registry_is_preregisterable_and_falsifiable() -> None:
    text = (REPO / ".agents/wfh-council/RESEARCH.md").read_text(encoding="utf-8")

    for label in [
        "mechanism:",
        "point_in_time_requirement:",
        "falsifier:",
        "promotion_gate:",
    ]:
        assert label in text
    assert "order flow" in text.lower()
    assert "basis" in text.lower()
    assert "regime" in text.lower()


def test_snapshot_separates_repository_and_production_revision(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "DATASET_AUDIT.json",
        {"contract": "DATASET_AUDIT.v1", "span_days": 10.0},
    )
    manifest = council.load_manifest(MANIFEST)

    snapshot = council.build_snapshot(
        REPO,
        manifest,
        research_dir=tmp_path,
        production_revision="production-sha-123",
    )

    assert snapshot["repo"]["git_sha"] != "production-sha-123"
    assert snapshot["repo"]["classification"] == "VERIFIED_FACT"
    assert snapshot["runtime"]["production_revision"] == {
        "classification": "VERIFIED_FACT",
        "value": "production-sha-123",
    }
    assert snapshot["research"]["promotion_disposition"] == "NO_PROMOTION_EVIDENCE"


def test_snapshot_marks_unknown_runtime_and_preserves_policy_assertion() -> None:
    manifest = council.load_manifest(MANIFEST)

    snapshot = council.build_snapshot(REPO, manifest)

    assert snapshot["runtime"]["production_revision"] == {
        "classification": "UNAVAILABLE",
        "value": None,
    }
    assert "production_revision" in snapshot["unknowns"]
    assert snapshot["runtime"]["live_trading_enabled"] == {
        "classification": "POLICY_ASSERTION",
        "value": False,
    }
    assert snapshot["protected_invariants"]["entry_ready_minimum"] == 78.0
    assert snapshot["protected_invariants"]["anti_chase_atr"] == 1.2


def test_snapshot_cli_emits_stable_json(capsys) -> None:
    rc = council.main(
        ["--repo-root", str(REPO), "snapshot", "--production-revision", "prod-456", "--json"]
    )
    output = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert output["contract_version"] == "wfh_council_snapshot_v1"
    assert output["runtime"]["production_revision"]["value"] == "prod-456"
    assert output["generated_at"].endswith("Z")


def test_snapshot_marks_repo_identity_unavailable_when_doctor_cannot_resolve_git(monkeypatch) -> None:
    manifest = council.load_manifest(MANIFEST)
    unavailable_repo = {
        "status": "UNAVAILABLE",
        "path": str(REPO),
        "git_sha": None,
        "branch": None,
    }
    monkeypatch.setattr(
        council,
        "doctor",
        lambda repo_root: {"repo": unavailable_repo},
    )

    snapshot = council.build_snapshot(REPO, manifest)

    assert snapshot["repo"]["classification"] == "UNAVAILABLE"
    assert "repo_identity" in snapshot["unknowns"]
