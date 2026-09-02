#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


MISSION_CONTRACT = "wfh_mission_continuity_v1"
TASK_STATES = {
    "NOT_STARTED",
    "READY",
    "IN_PROGRESS",
    "BLOCKED",
    "VERIFYING",
    "COMPLETE",
    "SUPERSEDED",
    "REJECTED",
}
EVIDENCE_CLASSES = {
    "VERIFIED_FACT",
    "REPRODUCED_DEFECT",
    "INFERENCE",
    "DEBT",
    "PROPOSAL",
}
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA_RE.fullmatch(value))


def validate_mission_state(state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = (
        "contract_version",
        "mission_id",
        "project",
        "repository",
        "baseline_main_sha",
        "current_main_sha",
        "current_phase",
        "current_task",
        "next_action",
    )
    for key in required:
        if not state.get(key):
            errors.append(f"mission state missing required field: {key}")
    if state.get("contract_version") not in {None, MISSION_CONTRACT}:
        errors.append("mission state contract_version is unsupported")
    for key in ("baseline_main_sha", "current_main_sha"):
        if key in state and not _is_sha(state.get(key)):
            errors.append(f"mission state {key} must be a 40-character lowercase Git SHA")
    return errors


def validate_task_graph(graph: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    tasks = graph.get("tasks")
    if not isinstance(tasks, list):
        return ["task graph tasks must be an array"]
    in_progress = 0
    for task in tasks:
        if not isinstance(task, dict):
            errors.append("task graph entries must be objects")
            continue
        task_id = str(task.get("task_id") or "<missing>")
        state = task.get("state")
        if state not in TASK_STATES:
            errors.append(f"task {task_id} has invalid state: {state}")
        if state == "IN_PROGRESS":
            in_progress += 1
        parents = task.get("parents", [])
        if not isinstance(parents, list):
            errors.append(f"task {task_id} parents must be an array")
        if state == "COMPLETE" and parents and not task.get("handoff"):
            errors.append(f"task {task_id} COMPLETE requires a parent-consumable handoff")
    if in_progress > 3:
        errors.append("task graph may not have more than three IN_PROGRESS workstreams")
    return errors


def validate_evidence_ledger(ledger: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    records = ledger.get("records")
    if not isinstance(records, list):
        return ["evidence ledger records must be an array"]
    for record in records:
        if not isinstance(record, dict):
            errors.append("evidence ledger entries must be objects")
            continue
        evidence_id = str(record.get("evidence_id") or "<missing>")
        classification = record.get("classification")
        if classification not in EVIDENCE_CLASSES:
            errors.append(
                f"evidence {evidence_id} classification must be one of {sorted(EVIDENCE_CLASSES)}"
            )
    return errors


def _confined_path(path: Path, allowed_root: Path) -> Path:
    root = Path(allowed_root).resolve(strict=True)
    candidate = Path(path).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"mission path must stay within allowed root {root}") from exc
    return candidate


def atomic_write_json(
    path: Path,
    payload: dict[str, Any] | list[Any],
    *,
    allowed_root: Path,
) -> Path:
    target = _confined_path(Path(path), Path(allowed_root))
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.tmp-",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        temp_path = None
        return target
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def update_scientific_state(
    current: dict[str, Any], updates: dict[str, Any]
) -> dict[str, Any]:
    opened = current.get("final_holdout_opened") is True
    retired = current.get("final_holdout_retired") is True
    if opened and updates.get("final_holdout_opened") is False:
        raise ValueError("final holdout cannot be reset after it has been opened")
    if retired and updates.get("final_holdout_retired") is False:
        raise ValueError("retired final holdout cannot be unretired")
    updated = copy.deepcopy(current)
    updated.update(updates)
    if opened:
        updated["final_holdout_opened"] = True
    if retired:
        updated["final_holdout_retired"] = True
    return updated
