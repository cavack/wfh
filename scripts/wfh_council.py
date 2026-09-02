#!/usr/bin/env python3
from __future__ import annotations

import json
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
