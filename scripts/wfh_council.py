#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED_INVARIANTS = {
    "live_order_placement": "FORBIDDEN",
    "live_trading_enabled": False,
    "missing_evidence_directional_imputation": "FORBIDDEN",
    "entry_ready_minimum": 78.0,
    "forming_minimum": 55.0,
    "anti_chase_atr": 1.2,
    "persistence_before_notification": True,
    "immutable_signal_provenance": True,
    "frontend_decision_logic_authority": "BACKEND_ONLY",
}


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("Council manifest must be a JSON object")
    return value

def _role_index(manifest: dict[str, Any], errors: list[str]) -> dict[str, dict[str, Any]]:
    roles = manifest.get("roles")
    if not isinstance(roles, list):
        errors.append("manifest roles must be a list")
        return {}

    index: dict[str, dict[str, Any]] = {}
    for role in roles:
        if not isinstance(role, dict) or not isinstance(role.get("id"), str):
            errors.append("every role must be an object with a string id")
            continue
        role_id = role["id"]
        if role_id in index:
            errors.append(f"duplicate role id: {role_id}")
            continue
        index[role_id] = role
    return index


def _validate_skills(repo_root: Path, roles: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for role_id, role in roles.items():
        skills = role.get("skills")
        if not isinstance(skills, list) or not skills:
            errors.append(f"role {role_id}: skills must be a non-empty list")
            continue
        for skill in skills:
            if not isinstance(skill, str):
                errors.append(f"role {role_id}: skill names must be strings")
                continue
            canonical = repo_root / "skills" / "waterfallhunter" / skill / "SKILL.md"
            adapter = repo_root / ".agents" / "skills" / skill / "SKILL.md"
            if not canonical.is_file():
                errors.append(f"role {role_id}: missing canonical skill {skill}")
            if not adapter.is_file():
                errors.append(f"role {role_id}: missing discovery adapter {skill}")
    return errors

def _validate_routes(manifest: dict[str, Any], roles: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    routes = manifest.get("routes")
    if not isinstance(routes, dict) or not routes:
        return ["manifest routes must be a non-empty object"]

    for route_name, route in routes.items():
        if not isinstance(route, list) or not route:
            errors.append(f"route {route_name}: must be a non-empty role list")
            continue
        for role_id in route:
            if role_id not in roles:
                errors.append(f"route {route_name}: unknown role {role_id}")
    return errors


def _validate_production_authority(
    manifest: dict[str, Any], roles: dict[str, dict[str, Any]]
) -> list[str]:
    authority = manifest.get("production_authority_role")
    if not isinstance(authority, str) or authority not in roles:
        return ["production_authority_role must name an existing role"]
    privileged = [role_id for role_id, role in roles.items() if role.get("production_authority") is True]
    if privileged != [authority]:
        return [
            "production authority must be exclusive to "
            f"{authority}; privileged roles={privileged}"
        ]
    return []


def _validate_invariants(manifest: dict[str, Any]) -> list[str]:
    invariants = manifest.get("protected_invariants")
    if not isinstance(invariants, dict):
        return ["protected_invariants must be an object"]
    errors: list[str] = []
    for key, expected in EXPECTED_INVARIANTS.items():
        if invariants.get(key) != expected:
            errors.append(f"protected invariant {key} must equal {expected!r}")
    return errors

def validate_manifest(repo_root: Path, manifest: dict[str, Any]) -> list[str]:
    repo_root = repo_root.resolve()
    errors: list[str] = []
    if manifest.get("contract_version") != "wfh_agent_council_v1":
        errors.append("contract_version must be wfh_agent_council_v1")

    roles = _role_index(manifest, errors)
    errors.extend(_validate_skills(repo_root, roles))
    errors.extend(_validate_routes(manifest, roles))
    errors.extend(_validate_production_authority(manifest, roles))
    errors.extend(_validate_invariants(manifest))

    model_route = manifest.get("routes", {}).get("model_optimization", [])
    required = [
        "chief_orchestrator",
        "market_evidence_forensics",
        "strategy_owner",
        "quant_validation_lead",
        "false_positive_hunter",
        "false_negative_hunter",
        "regression_lead",
        "release_certifier",
    ]
    if model_route != required:
        errors.append("model_optimization route must match the canonical Council order")
    return errors

def route_task(manifest: dict[str, Any], task_type: str) -> list[dict[str, Any]]:
    routes = manifest.get("routes")
    if not isinstance(routes, dict) or task_type not in routes:
        raise KeyError(f"unknown Council route: {task_type}")

    role_map = {
        role["id"]: role
        for role in manifest.get("roles", [])
        if isinstance(role, dict) and isinstance(role.get("id"), str)
    }
    packets: list[dict[str, Any]] = []
    for role_id in routes[task_type]:
        role = role_map.get(role_id)
        if role is None:
            raise ValueError(f"route references unknown role: {role_id}")
        packets.append(
            {
                "role": role_id,
                "skills": list(role.get("skills", [])),
                "production_authority": role.get("production_authority") is True,
            }
        )
    return packets


def _git_output(repo_root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo_root, text=True, stderr=subprocess.DEVNULL
    ).strip()

LOCAL_TOOL_COMMANDS = {
    "git": "git",
    "python": "python3",
    "docker": "docker",
    "node": "node",
    "npm": "npm",
    "coderabbit": "coderabbit",
}
REQUIRED_LOCAL_TOOLS = {"git", "python"}


def doctor(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    repo_status = "UNAVAILABLE"
    git_sha: str | None = None
    branch: str | None = None
    try:
        git_sha = _git_output(repo_root, "rev-parse", "HEAD")
        branch = _git_output(repo_root, "branch", "--show-current") or None
        repo_status = "AVAILABLE"
    except (OSError, subprocess.CalledProcessError):
        pass

    tools: dict[str, dict[str, Any]] = {}
    missing_required: list[str] = []
    for tool_id, command in LOCAL_TOOL_COMMANDS.items():
        path = shutil.which(command)
        status = "AVAILABLE" if path else "UNAVAILABLE"
        tools[tool_id] = {"status": status, "path": path}
        if tool_id in REQUIRED_LOCAL_TOOLS and path is None:
            missing_required.append(tool_id)

    ready = repo_status == "AVAILABLE" and not missing_required
    return {
        "contract_version": "wfh_council_doctor_v1",
        "status": "READY" if ready else "BLOCKED",
        "repo": {
            "status": repo_status,
            "path": str(repo_root),
            "git_sha": git_sha,
            "branch": branch,
        },
        "tools": tools,
        "missing_required": missing_required,
    }


RESEARCH_ARTIFACTS = (
    "DATASET_AUDIT.json",
    "OOS_VALIDATION.json",
    "BEST_DEVELOPMENT_CONFIG.json",
    "PRODUCTION_VS_CHALLENGERS.json",
    "GATE_REJECTION_FUNNEL.json",
    "OUTCOME_INTEGRITY.json",
)


def _read_research_artifact(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not path.is_file():
        return None, {"status": "MISSING_ARTIFACT"}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, {"status": "INVALID_ARTIFACT", "error": str(exc)}
    if not isinstance(value, dict):
        return None, {"status": "INVALID_ARTIFACT", "error": "root must be a JSON object"}
    return value, {"status": "AVAILABLE", "contract": value.get("contract")}


def summarize_research_evidence(research_dir: Path) -> dict[str, Any]:
    research_dir = research_dir.resolve()
    values: dict[str, dict[str, Any] | None] = {}
    artifact_status: dict[str, dict[str, Any]] = {}
    for name in RESEARCH_ARTIFACTS:
        value, status = _read_research_artifact(research_dir / name)
        values[name] = value
        artifact_status[name] = status

    dataset = values["DATASET_AUDIT.json"] or {}
    oos = values["OOS_VALIDATION.json"] or {}
    champion = values["BEST_DEVELOPMENT_CONFIG.json"] or {}
    comparison = values["PRODUCTION_VS_CHALLENGERS.json"] or {}
    funnel = values["GATE_REJECTION_FUNNEL.json"] or {}
    outcome = values["OUTCOME_INTEGRITY.json"] or {}

    blockers: list[str] = []
    span = dataset.get("span_days")
    if not isinstance(span, (int, float)) or span < 42.0:
        blockers.append("insufficient_promotion_span")

    accepted_oos = {"PASSED", "VALIDATED", "COMPLETE"}
    if oos.get("status") not in accepted_oos:
        blockers.append("insufficient_oos_evidence")

    if champion.get("promotion_allowed") is not True:
        blockers.append("no_scientific_champion")
    if comparison.get("promotion_allowed") is not True:
        blockers.append("production_promotion_not_allowed")
    if outcome.get("net_cost_adjusted_r_available") is not True:
        blockers.append("missing_net_cost_adjusted_r")

    disposition = "PROMOTION_EVIDENCE_CANDIDATE" if not blockers else "NO_PROMOTION_EVIDENCE"

    return {
        "contract_version": "wfh_council_research_snapshot_v1",
        "research_dir": str(research_dir),
        "promotion_disposition": disposition,
        "blockers": blockers,
        "artifacts": artifact_status,
        "dataset": _research_dataset_summary(dataset),
        "oos": _research_oos_summary(oos),
        "champion": _research_champion_summary(champion),
        "production_comparison": _research_comparison_summary(comparison),
        "gate_funnel": _research_funnel_summary(funnel),
        "outcome_integrity": _research_outcome_summary(outcome),
    }


def _select(source: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: source.get(key) for key in keys if key in source}


def _research_dataset_summary(source: dict[str, Any]) -> dict[str, Any]:
    return _select(
        source,
        "contract", "evidence_tier", "data_sha256", "rows", "episodes", "symbols",
        "span_days", "fresh_production_like_rows", "production_like_episodes",
        "fresh_tier2_strict_rows", "tier2_strict_episodes", "limitations",
    )


def _research_oos_summary(source: dict[str, Any]) -> dict[str, Any]:
    return _select(
        source,
        "contract", "status", "reason", "dataset_sha256", "outcome_cache_sha256",
        "maximum_complete_outcomes_any_stage2_config", "span_days", "required_properties",
    )


def _research_champion_summary(source: dict[str, Any]) -> dict[str, Any]:
    return _select(
        source,
        "contract", "status", "promotion_allowed", "reasons",
        "maximum_complete_outcomes_any_stage2_config", "best_observed_safety_preserving_by_entry_count",
    )


def _research_comparison_summary(source: dict[str, Any]) -> dict[str, Any]:
    return _select(
        source,
        "contract", "production", "development_profiles", "promotion_allowed", "why_not",
    )


def _research_funnel_summary(source: dict[str, Any]) -> dict[str, Any]:
    return _select(
        source,
        "contract", "anti_chase_atr", "episodes_total", "episodes_with_prelate_row",
        "episodes_without_fresh_prelate_row", "episodes_ever_passing_gate_prelate",
        "episodes_reaching_threshold", "prelate_max_readiness", "most_common_best_row_failure_sets",
    )


def _research_outcome_summary(source: dict[str, Any]) -> dict[str, Any]:
    return _select(
        source,
        "contract", "cache_sha256", "label_contract", "rows", "outcome_complete",
        "unavailable", "unavailable_reasons", "outcomes", "net_cost_adjusted_r_available",
        "causal_entry_before_observation_count", "duplicate_snapshot_ids", "limitations",
    )



def build_snapshot(
    repo_root: Path,
    manifest: dict[str, Any],
    *,
    research_dir: Path | None = None,
    production_revision: str | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    repo = doctor(repo_root)["repo"]
    research = (
        summarize_research_evidence(research_dir)
        if research_dir is not None
        else {"promotion_disposition": "UNAVAILABLE", "artifacts": {}}
    )
    production_fact = {
        "classification": "VERIFIED_FACT" if production_revision else "UNAVAILABLE",
        "value": production_revision,
    }
    unknowns: list[str] = []
    if not production_revision:
        unknowns.append("production_revision")
    repo_classification = "VERIFIED_FACT" if repo.get("status") == "AVAILABLE" else "UNAVAILABLE"
    if repo_classification == "UNAVAILABLE":
        unknowns.append("repo_identity")
    return {
        "contract_version": "wfh_council_snapshot_v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "repo": {**repo, "classification": repo_classification},
        "runtime": {
            "production_revision": production_fact,
            "live_trading_enabled": {"classification": "POLICY_ASSERTION", "value": False},
        },
        "research": research,
        "protected_invariants": manifest["protected_invariants"],
        "readiness": {
            "research_promotion_disposition": research.get("promotion_disposition", "UNAVAILABLE"),
            "repo_matches_production": bool(production_revision and repo.get("git_sha") == production_revision),
        },
        "unknowns": unknowns,
    }

def _emit(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2, sort_keys=True))
    elif isinstance(value, list):
        for item in value:
            print(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            print(f"{key}={item}")
    else:
        print(value)


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WaterfallHunter Senior Agent Council")
    parser.add_argument("--repo-root", type=Path, default=_default_repo_root())
    sub = parser.add_subparsers(dest="command", required=True)

    validate_cmd = sub.add_parser("validate", help="validate the Council contract")
    validate_cmd.add_argument("--json", action="store_true")

    route_cmd = sub.add_parser("route", help="resolve a Council route")
    route_cmd.add_argument("task_type")
    route_cmd.add_argument("--json", action="store_true")

    doctor_cmd = sub.add_parser("doctor", help="inspect local deterministic capabilities")
    doctor_cmd.add_argument("--json", action="store_true")

    research_cmd = sub.add_parser("research-snapshot", help="summarize existing research evidence")
    research_cmd.add_argument("--research-dir", type=Path, required=True)
    research_cmd.add_argument("--json", action="store_true")

    snapshot_cmd = sub.add_parser("snapshot", help="emit a safe repository/runtime/research snapshot")
    snapshot_cmd.add_argument("--research-dir", type=Path)
    snapshot_cmd.add_argument("--production-revision")
    snapshot_cmd.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    manifest_path = repo_root / ".agents" / "wfh-council" / "manifest.json"
    try:
        manifest = load_manifest(manifest_path)
    except (OSError, ValueError) as exc:
        _emit({"status": "INVALID", "errors": [str(exc)]}, getattr(args, "json", False))
        return 2

    if args.command == "validate":
        errors = validate_manifest(repo_root, manifest)
        result = {"status": "VALID" if not errors else "INVALID", "errors": errors}
        _emit(result, args.json)
        return 0 if not errors else 2

    if args.command == "route":
        try:
            route = route_task(manifest, args.task_type)
        except (KeyError, ValueError) as exc:
            _emit({"status": "INVALID", "error": str(exc)}, args.json)
            return 2
        _emit({"status": "OK", "task_type": args.task_type, "route": route}, args.json)
        return 0

    if args.command == "doctor":
        result = doctor(repo_root)
        _emit(result, args.json)
        return 0 if result["status"] == "READY" else 3

    if args.command == "research-snapshot":
        result = summarize_research_evidence(args.research_dir)
        _emit(result, args.json)
        return 0

    if args.command == "snapshot":
        result = build_snapshot(
            repo_root,
            manifest,
            research_dir=args.research_dir,
            production_revision=args.production_revision,
        )
        _emit(result, args.json)
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
