#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.request
import tempfile
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
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
MISSION_STATE_FILE = "MISSION_STATE.json"
STEP_JOURNAL_FILE = "STEP_JOURNAL.json"
GITHUB_ISSUE_NUMBER_ERROR = "GitHub issue number must be positive"

DURABLE_STATE_FILES = (
    MISSION_STATE_FILE,
    "TASK_GRAPH.json",
    "EVIDENCE_LEDGER.json",
    "BRANCH_REGISTRY.json",
    "SCIENTIFIC_STATE.json",
    "DECISION_LOG.jsonl",
    STEP_JOURNAL_FILE,
)
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


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _mission_lock(mission_dir: Path):
    root = Path(mission_dir).resolve(strict=True)
    lock_path = _confined_path(root / ".mission-control.lock", root)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


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
        _fsync_directory(target.parent)
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


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _atomic_write_bytes(path: Path, payload: bytes, *, allowed_root: Path) -> Path:
    target = _confined_path(Path(path), Path(allowed_root))
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=f".{target.name}.tmp-", delete=False
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        _fsync_directory(target.parent)
        temp_path = None
        return target
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _highest_checkpoint_number(mission_dir: Path) -> int:
    checkpoints = mission_dir / "checkpoints"
    checkpoints.mkdir(parents=True, exist_ok=True)
    highest = 0
    for path in checkpoints.glob("CP-*.json"):
        match = re.fullmatch(r"CP-(\d{6})\.json", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest


def _next_checkpoint_id(mission_dir: Path) -> str:
    return f"CP-{_highest_checkpoint_number(mission_dir) + 1:06d}"


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _resume_projection(checkpoint: dict[str, Any]) -> str:
    state = checkpoint["mission_state"]
    completed = ", ".join(state.get("completed_tasks", [])) or "none"
    no_repeat = ", ".join(state.get("do_not_repeat", [])) or "none"
    blockers = ", ".join(state.get("blocked_tasks", [])) or "none"
    defects = ", ".join(state.get("open_defects", [])) or "none"
    steps = checkpoint.get("step_journal", {}).get("steps", [])
    active_steps = [step for step in steps if step.get("status") == "IN_PROGRESS"]
    operation = "none"
    if active_steps:
        active = active_steps[-1]
        operation = f"{active.get('step_id', 'UNKNOWN')}: {active.get('action', 'UNKNOWN')}"
    return "\n".join(
        [
            "# TWFH Mission Resume",
            "",
            f"Mission: {checkpoint['mission_id']}",
            f"Checkpoint: {checkpoint['checkpoint_id']}",
            f"Main SHA: {state.get('current_main_sha', 'UNAVAILABLE')}",
            f"Production SHA: {state.get('production_sha', 'UNAVAILABLE')}",
            f"Phase: {state.get('current_phase', 'UNAVAILABLE')}",
            f"Current task: {state.get('current_task', 'UNAVAILABLE')}",
            f"Completed: {completed}",
            f"Do not repeat: {no_repeat}",
            f"Open defects: {defects}",
            f"Blocked: {blockers}",
            f"Active branch: {state.get('active_branch', 'UNAVAILABLE')}",
            f"Active worktree: {state.get('active_worktree', 'UNAVAILABLE')}",
            f"Active PR: {state.get('active_pr', 'UNAVAILABLE')}",
            f"In-progress operation: {operation}",
            f"Next action: {state.get('next_action', 'UNAVAILABLE')}",
            f"Preconditions: {', '.join(state.get('next_action_preconditions', [])) or 'none'}",
            f"Do not: {', '.join(state.get('do_not', [])) or 'none'}",
            "",
        ]
    )


def _validate_checkpoint_control_bundle(root: Path) -> list[str]:
    errors: list[str] = []
    validators = (
        ("TASK_GRAPH.json", validate_task_graph),
        ("EVIDENCE_LEDGER.json", validate_evidence_ledger),
    )
    for name, validator in validators:
        path = _confined_path(root / name, root)
        if not path.exists():
            errors.append(f"required checkpoint state missing: {name}")
            continue
        try:
            payload = _load_json(path)
        except (OSError, ValueError) as exc:
            errors.append(f"invalid {name}: {type(exc).__name__}")
            continue
        errors.extend(f"{name}: {message}" for message in validator(payload))
    return errors


def create_checkpoint(mission_dir: Path, *, created_at: str | None = None) -> dict[str, Any]:
    root = Path(mission_dir).resolve(strict=True)
    with _mission_lock(root):
        state_path = _confined_path(root / MISSION_STATE_FILE, root)
        state = _load_json(state_path)
        errors = validate_mission_state(state) + _validate_checkpoint_control_bundle(root)
        if errors:
            raise ValueError("; ".join(errors))
        checkpoint_id = _next_checkpoint_id(root)
        journal = _load_journal(root)
        state_files: dict[str, str | None] = {}
        for name in DURABLE_STATE_FILES:
            candidate = _confined_path(root / name, root)
            state_files[name] = (
                _sha256_bytes(candidate.read_bytes()) if candidate.exists() else None
            )
        checkpoint = {
            "contract_version": "wfh_mission_checkpoint_v1",
            "mission_id": state["mission_id"],
            "checkpoint_id": checkpoint_id,
            "created_at": created_at or _utc_now(),
            "mission_state": state,
            "step_journal": journal,
            "state_files": state_files,
        }
        checkpoint_rel = Path("checkpoints") / f"{checkpoint_id}.json"
        checkpoint_path = root / checkpoint_rel
        checkpoint_bytes = _canonical_json_bytes(checkpoint)
        _atomic_write_bytes(checkpoint_path, checkpoint_bytes, allowed_root=root)
        pointer = {
            "contract_version": "wfh_latest_checkpoint_v1",
            "mission_id": state["mission_id"],
            "checkpoint_id": checkpoint_id,
            "path": checkpoint_rel.as_posix(),
            "sha256": _sha256_bytes(checkpoint_bytes),
        }
        atomic_write_json(root / "LATEST_CHECKPOINT.json", pointer, allowed_root=root)
        _atomic_write_bytes(
            root / "RESUME.md",
            _resume_projection(checkpoint).encode("utf-8"),
            allowed_root=root,
        )
        return pointer


def load_latest_checkpoint(mission_dir: Path) -> dict[str, Any]:
    root = Path(mission_dir).resolve(strict=True)
    pointer_path = _confined_path(root / "LATEST_CHECKPOINT.json", root)
    if not pointer_path.exists():
        return {"disposition": "RESUME_BLOCKED", "reason": "latest_checkpoint_missing"}
    try:
        pointer = _load_json(pointer_path)
        checkpoint_path = _confined_path(root / str(pointer["path"]), root)
    except (KeyError, ValueError):
        return {"disposition": "RESUME_BLOCKED", "reason": "latest_checkpoint_pointer_invalid"}
    if not checkpoint_path.exists():
        return {"disposition": "RESUME_BLOCKED", "reason": "checkpoint_missing"}
    payload = checkpoint_path.read_bytes()
    if _sha256_bytes(payload) != pointer.get("sha256"):
        return {"disposition": "RESUME_BLOCKED", "reason": "checkpoint_hash_mismatch"}
    try:
        checkpoint = json.loads(payload)
    except json.JSONDecodeError:
        return {"disposition": "RESUME_BLOCKED", "reason": "checkpoint_json_invalid"}
    if checkpoint.get("mission_id") != pointer.get("mission_id"):
        return {"disposition": "RESUME_BLOCKED", "reason": "checkpoint_mission_mismatch"}
    if checkpoint.get("checkpoint_id") != pointer.get("checkpoint_id"):
        return {"disposition": "RESUME_BLOCKED", "reason": "checkpoint_sequence_mismatch"}
    match = re.fullmatch(r"CP-(\d{6})", str(pointer.get("checkpoint_id") or ""))
    if match is None:
        return {"disposition": "RESUME_BLOCKED", "reason": "checkpoint_sequence_invalid"}
    highest = _highest_checkpoint_number(root)
    if int(match.group(1)) < highest:
        return {
            "disposition": "RESUME_BLOCKED",
            "reason": "checkpoint_sequence_regression",
            "pointer_checkpoint_id": pointer.get("checkpoint_id"),
            "highest_checkpoint_id": f"CP-{highest:06d}",
        }
    return {
        "disposition": "RESUME_READY",
        "reason": None,
        "pointer": pointer,
        "checkpoint": checkpoint,
    }


def _journal_path(mission_dir: Path) -> Path:
    return Path(mission_dir).resolve(strict=True) / STEP_JOURNAL_FILE


def _load_journal(mission_dir: Path) -> dict[str, Any]:
    root = Path(mission_dir).resolve(strict=True)
    path = _confined_path(root / STEP_JOURNAL_FILE, root)
    if not path.exists():
        return {"contract_version": "wfh_step_journal_v1", "steps": []}
    journal = _load_json(path)
    if not isinstance(journal.get("steps"), list):
        raise ValueError("step journal steps must be an array")
    return journal


def journal_step_start(
    mission_dir: Path,
    *,
    task_id: str,
    step_id: str,
    action: str,
    expected_state_change: str,
    pre_step_sha: str,
    required_capabilities: list[str],
    retry_policy: str,
    reconciliation_procedure: str,
    started_at: str | None = None,
) -> dict[str, Any]:
    root = Path(mission_dir).resolve(strict=True)
    with _mission_lock(root):
        journal = _load_journal(root)
        if any(step.get("step_id") == step_id for step in journal["steps"]):
            raise ValueError(f"duplicate step_id: {step_id}")
        record = {
            "task_id": task_id,
            "step_id": step_id,
            "action": action,
            "expected_state_change": expected_state_change,
            "pre_step_sha": pre_step_sha,
            "required_capabilities": list(required_capabilities),
            "retry_policy": retry_policy,
            "reconciliation_procedure": reconciliation_procedure,
            "status": "IN_PROGRESS",
            "started_at": started_at or _utc_now(),
            "completed_at": None,
        }
        journal["steps"].append(record)
        atomic_write_json(root / STEP_JOURNAL_FILE, journal, allowed_root=root)
        return record


def journal_step_complete(
    mission_dir: Path, step_id: str, *, completed_at: str | None = None
) -> dict[str, Any]:
    root = Path(mission_dir).resolve(strict=True)
    with _mission_lock(root):
        journal = _load_journal(root)
        for record in journal["steps"]:
            if record.get("step_id") == step_id:
                record["status"] = "COMPLETE"
                record["completed_at"] = completed_at or _utc_now()
                atomic_write_json(root / STEP_JOURNAL_FILE, journal, allowed_root=root)
                return record
        raise ValueError(f"unknown step_id: {step_id}")


def _live_state_file_changes(
    mission_dir: Path, checkpoint: dict[str, Any]
) -> tuple[list[str], list[str]]:
    root = Path(mission_dir).resolve(strict=True)
    changed: list[str] = []
    missing: list[str] = []
    state_files = checkpoint.get("state_files", {})
    if not isinstance(state_files, dict):
        return ["<state_files_invalid>"], []
    for name, expected_hash in state_files.items():
        path = _confined_path(root / str(name), root)
        if expected_hash is None:
            if path.exists():
                changed.append(str(name))
            continue
        if not path.exists():
            missing.append(str(name))
            continue
        if _sha256_bytes(path.read_bytes()) != expected_hash:
            changed.append(str(name))
    return sorted(changed), sorted(missing)


OBSERVED_CAPABILITY_STATES = {
    "AVAILABLE",
    "AUTHORIZED_READ",
    "AUTHORIZED_WRITE",
    "UNAVAILABLE",
    "BLOCKED",
}
_USABLE_CAPABILITY_STATES = {"AVAILABLE", "AUTHORIZED_READ", "AUTHORIZED_WRITE"}


def _interrupted_step_gate(root: Path, checkpoint: dict[str, Any]) -> dict[str, Any] | None:
    live_steps = _load_journal(root).get("steps", [])
    interrupted = [step for step in live_steps if step.get("status") == "IN_PROGRESS"]
    if not interrupted:
        snapshot_steps = checkpoint.get("step_journal", {}).get("steps", [])
        interrupted = [step for step in snapshot_steps if step.get("status") == "IN_PROGRESS"]
    if not interrupted:
        return None
    return {
        "disposition": "RECONCILIATION_REQUIRED",
        "reason": "interrupted_step",
        "interrupted_step": interrupted[-1],
        "retry_allowed": False,
    }


def _state_files_gate(root: Path, checkpoint: dict[str, Any]) -> dict[str, Any] | None:
    changed, missing = _live_state_file_changes(root, checkpoint)
    if missing:
        return {
            "disposition": "RESUME_BLOCKED",
            "reason": "checkpoint_state_file_missing",
            "missing_state_files": missing,
        }
    if not changed:
        return None
    return {
        "disposition": "RECONCILIATION_REQUIRED",
        "reason": "uncheckpointed_state_change",
        "changed_state_files": changed,
        "retry_allowed": False,
    }


def _observation_gate(
    state: dict[str, Any],
    *,
    observed_main_sha: str | None,
    observed_production_sha: str | None,
    observed_branch_head: str | None,
    observed_branch: str | None,
    observed_worktree: str | None,
    observed_worktree_dirty: bool | None,
) -> dict[str, Any] | None:
    observations = (
        ("repository_main", state.get("current_main_sha"), observed_main_sha),
        ("production_revision", state.get("production_sha"), observed_production_sha),
        ("branch_head", state.get("active_branch_head"), observed_branch_head),
        ("active_branch", state.get("active_branch"), observed_branch),
        ("active_worktree", state.get("active_worktree"), observed_worktree),
        ("worktree_cleanliness", state.get("active_worktree_dirty"), observed_worktree_dirty),
    )
    missing = [
        name
        for name, expected, observed in observations
        if expected is not None and observed is None
    ]
    if not missing:
        return None
    return {
        "disposition": "RESUME_BLOCKED",
        "reason": "required_observation_unavailable",
        "missing_observations": missing,
    }


def _worktree_cleanliness_gate(
    state: dict[str, Any], observed_worktree_dirty: bool | None
) -> dict[str, Any] | None:
    expected_dirty = state.get("active_worktree_dirty")
    if observed_worktree_dirty is True:
        reason = "uncommitted_worktree_changes"
    elif observed_worktree_dirty is False and expected_dirty is True:
        reason = "worktree_cleanliness_changed_since_checkpoint"
    else:
        return None
    return {
        "disposition": "RECONCILIATION_REQUIRED",
        "reason": reason,
        "retry_allowed": False,
    }


def _capability_gate(
    state: dict[str, Any], capabilities: dict[str, str] | None
) -> dict[str, Any] | None:
    states = capabilities or {}
    unavailable = sorted(
        capability
        for capability in state.get("required_capabilities", [])
        if states.get(capability) not in _USABLE_CAPABILITY_STATES
    )
    if not unavailable:
        return None
    return {
        "disposition": "RESUME_BLOCKED",
        "reason": "required_capability_unavailable",
        "unavailable_capabilities": unavailable,
    }


def _observed_drift(
    state: dict[str, Any],
    *,
    observed_main_sha: str | None,
    observed_production_sha: str | None,
    observed_branch_head: str | None,
    observed_branch: str | None,
    observed_worktree: str | None,
) -> list[dict[str, str]]:
    fields = (
        ("repository_main", state.get("current_main_sha"), observed_main_sha),
        ("production_revision", state.get("production_sha"), observed_production_sha),
        ("branch_head", state.get("active_branch_head"), observed_branch_head),
        ("active_branch", state.get("active_branch"), observed_branch),
        ("active_worktree", state.get("active_worktree"), observed_worktree),
    )
    return [
        {"scope": scope, "expected": str(expected), "observed": observed}
        for scope, expected, observed in fields
        if observed is not None and expected is not None and observed != expected
    ]


def resume_guard(
    mission_dir: Path,
    *,
    observed_main_sha: str | None = None,
    observed_production_sha: str | None = None,
    observed_branch_head: str | None = None,
    observed_branch: str | None = None,
    observed_worktree: str | None = None,
    observed_worktree_dirty: bool | None = None,
    capabilities: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = Path(mission_dir).resolve(strict=True)
    loaded = load_latest_checkpoint(root)
    if loaded.get("disposition") != "RESUME_READY":
        return loaded
    checkpoint = loaded["checkpoint"]
    state = checkpoint["mission_state"]
    gates = (
        _interrupted_step_gate(root, checkpoint),
        _state_files_gate(root, checkpoint),
        _worktree_cleanliness_gate(state, observed_worktree_dirty),
        _observation_gate(
            state,
            observed_main_sha=observed_main_sha,
            observed_production_sha=observed_production_sha,
            observed_branch_head=observed_branch_head,
            observed_branch=observed_branch,
            observed_worktree=observed_worktree,
            observed_worktree_dirty=observed_worktree_dirty,
        ),
        _capability_gate(state, capabilities),
    )
    for result in gates:
        if result is not None:
            return result
    drift = _observed_drift(
        state,
        observed_main_sha=observed_main_sha,
        observed_production_sha=observed_production_sha,
        observed_branch_head=observed_branch_head,
        observed_branch=observed_branch,
        observed_worktree=observed_worktree,
    )
    if drift:
        return {"disposition": "DRIFT_DETECTED", "reason": "revision_drift", "drift": drift}
    return loaded


CANONICAL_RESUME_INTENT = "ادامه کار گروهی"
DEFAULT_CONTROL_ROOT = Path("/srv/waterfallhunter/research/mission-control")


def normalize_resume_intent(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def resolve_active_mission(control_root: Path) -> Path:
    root = Path(control_root).resolve(strict=True)
    pointer_path = _confined_path(root / "ACTIVE_MISSION.json", root)
    pointer = _load_json(pointer_path)
    mission_id = pointer.get("mission_id")
    mission_path = pointer.get("mission_path") or mission_id
    if not isinstance(mission_id, str) or not mission_id:
        raise ValueError("active mission pointer missing mission_id")
    if not isinstance(mission_path, str) or not mission_path:
        raise ValueError("active mission pointer missing mission_path")
    target = _confined_path(root / mission_path, root)
    if not target.is_dir():
        raise ValueError("active mission directory is unavailable")
    state = _load_json(_confined_path(target / MISSION_STATE_FILE, target))
    if state.get("mission_id") != mission_id:
        raise ValueError("active mission pointer mission identity mismatch")
    return target


def _parse_capabilities(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"capability must be NAME=STATE: {item}")
        name, state = item.split("=", 1)
        if not name or not state:
            raise ValueError(f"capability must be NAME=STATE: {item}")
        if state not in OBSERVED_CAPABILITY_STATES:
            raise ValueError(f"invalid observed capability state: {state}")
        result[name] = state
    return result


def _emit_result(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return
    disposition = result.get("disposition", "RESUME_BLOCKED")
    reason = result.get("reason")
    print(f"{disposition}: {reason or 'ready'}")


def _resume_exit_code(disposition: str) -> int:
    return {
        "RESUME_READY": 0,
        "MISSION_COMPLETE": 0,
        "RESUME_BLOCKED": 2,
        "RECONCILIATION_REQUIRED": 3,
        "DRIFT_DETECTED": 4,
    }.get(disposition, 2)




def render_pointer_issue(
    *, mission_id: str, mission_issue_number: int, pointer: dict[str, Any]
) -> str:
    marker = f"<!-- wfh-mission-pointer:v1 mission={mission_id} -->"
    return "\n".join(
        [
            marker,
            "# TWFH Active Mission",
            "",
            f"Mission: `{mission_id}`",
            f"Mission issue: #{mission_issue_number}",
            f"Latest checkpoint: `{pointer['checkpoint_id']}`",
            f"Checkpoint SHA-256: `{pointer['sha256']}`",
            "Repository: `cavack/wfh`",
            f"Resume intent: `{CANONICAL_RESUME_INTENT}`",
            "",
            "This issue is a compact control-plane pointer; host checkpoint evidence remains authoritative.",
            "",
        ]
    )


def render_mission_issue(checkpoint: dict[str, Any], pointer: dict[str, Any]) -> str:
    state = checkpoint["mission_state"]
    marker = f"<!-- wfh-mission-state:v1 mission={checkpoint['mission_id']} -->"
    return "\n".join(
        [
            marker,
            f"# {checkpoint['mission_id']} — Model Excellence v3",
            "",
            f"Current phase: `{state.get('current_phase', 'UNAVAILABLE')}`",
            f"Current task: `{state.get('current_task', 'UNAVAILABLE')}`",
            f"Current main: `{state.get('current_main_sha', 'UNAVAILABLE')}`",
            f"Production: `{state.get('production_sha', 'UNAVAILABLE')}`",
            f"Active branch: `{state.get('active_branch', 'UNAVAILABLE')}`",
            f"Active worktree: `{state.get('active_worktree', 'UNAVAILABLE')}`",
            f"Active PR: `{state.get('active_pr', 'UNAVAILABLE')}`",
            f"Latest checkpoint: `{pointer['checkpoint_id']}`",
            f"Checkpoint SHA-256: `{pointer['sha256']}`",
            "",
            "## Exact next action",
            str(state.get("next_action", "UNAVAILABLE")),
            "",
            "## Resume rule",
            f"Use `{CANONICAL_RESUME_INTENT}` and validate the durable checkpoint before continuing.",
            "",
        ]
    )


def _checkpoint_marker(pointer: dict[str, Any]) -> str:
    return (
        "<!-- wfh-mission-checkpoint:v1 "
        f"mission={pointer['mission_id']} checkpoint={pointer['checkpoint_id']} "
        f"sha256={pointer['sha256']} -->"
    )


def render_checkpoint_comment(
    checkpoint: dict[str, Any], pointer: dict[str, Any]
) -> str:
    state = checkpoint["mission_state"]
    return "\n".join(
        [
            _checkpoint_marker(pointer),
            f"Checkpoint `{pointer['checkpoint_id']}` synchronized.",
            f"Task: `{state.get('current_task', 'UNAVAILABLE')}`",
            f"Main: `{state.get('current_main_sha', 'UNAVAILABLE')}`",
            f"Next action: {state.get('next_action', 'UNAVAILABLE')}",
        ]
    )


def _github_token() -> str | None:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token.strip() or None
    if shutil.which("gh") is None:
        return None
    try:
        value = subprocess.check_output(
            ["gh", "auth", "token"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.SubprocessError:
        return None
    return value or None


def _validate_github_target(repository: str, pointer_issue: int, mission_issue: int) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("repository must be owner/name")
    if pointer_issue <= 0 or mission_issue <= 0:
        raise ValueError("GitHub issue numbers must be positive")


def _github_request(
    repository: str,
    endpoint: str,
    *,
    method: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("repository must be owner/name")
    if not endpoint.startswith("/") or ".." in endpoint:
        raise ValueError("GitHub endpoint is invalid")
    url = f"https://api.github.com/repos/{repository}{endpoint}"
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    return None if not raw else json.loads(raw)


def _github_edit_issue(repository: str, issue_number: int, body: str, token: str) -> None:
    if issue_number <= 0:
        raise ValueError(GITHUB_ISSUE_NUMBER_ERROR)
    _github_request(
        repository,
        f"/issues/{issue_number}",
        method="PATCH",
        token=token,
        payload={"body": body},
    )


def _github_get_issue(repository: str, issue_number: int, token: str) -> dict[str, Any]:
    if issue_number <= 0:
        raise ValueError(GITHUB_ISSUE_NUMBER_ERROR)
    data = _github_request(repository, f"/issues/{issue_number}", method="GET", token=token)
    if not isinstance(data, dict):
        raise ValueError("GitHub issue response must be an object")
    return data


def _github_list_issue_comments(
    repository: str, issue_number: int, token: str
) -> list[dict[str, Any]]:
    if issue_number <= 0:
        raise ValueError(GITHUB_ISSUE_NUMBER_ERROR)
    comments: list[dict[str, Any]] = []
    for page in range(1, 101):
        data = _github_request(
            repository,
            f"/issues/{issue_number}/comments?per_page=100&page={page}",
            method="GET",
            token=token,
        )
        if not isinstance(data, list):
            raise ValueError("GitHub comments response must be an array")
        comments.extend(item for item in data if isinstance(item, dict))
        if len(data) < 100:
            return comments
    raise ValueError("GitHub comments exceed bounded pagination limit")


def _github_comment_issue(
    repository: str, issue_number: int, body: str, token: str
) -> None:
    if issue_number <= 0:
        raise ValueError(GITHUB_ISSUE_NUMBER_ERROR)
    _github_request(
        repository,
        f"/issues/{issue_number}/comments",
        method="POST",
        token=token,
        payload={"body": body},
    )


def _validate_issue_identity(
    issue: dict[str, Any],
    *,
    expected_title: str,
    expected_marker: str,
    initialize: bool,
) -> None:
    title = str(issue.get("title") or "")
    body = str(issue.get("body") or "")
    if title != expected_title:
        raise ValueError("GitHub mission issue identity mismatch")
    if expected_marker in body:
        return
    if initialize:
        return
    raise ValueError("GitHub mission issue identity marker missing")


def sync_github(
    mission_dir: Path,
    *,
    repository: str,
    pointer_issue: int,
    mission_issue: int,
    initialize: bool = False,
) -> dict[str, Any]:
    _validate_github_target(repository, pointer_issue, mission_issue)
    token = _github_token()
    if token is None:
        return {"status": "UNAVAILABLE", "reason": "github_auth_unavailable"}
    loaded = load_latest_checkpoint(mission_dir)
    if loaded.get("disposition") != "RESUME_READY":
        return {
            "status": "BLOCKED",
            "reason": str(loaded.get("reason") or loaded.get("disposition")),
        }
    checkpoint = loaded["checkpoint"]
    pointer = loaded["pointer"]
    pointer_body = render_pointer_issue(
        mission_id=checkpoint["mission_id"],
        mission_issue_number=mission_issue,
        pointer=pointer,
    )
    mission_body = render_mission_issue(checkpoint, pointer)
    mission_id = str(checkpoint["mission_id"])
    current_pointer = _github_get_issue(repository, pointer_issue, token)
    current_mission = _github_get_issue(repository, mission_issue, token)
    _validate_issue_identity(
        current_pointer,
        expected_title="[MISSION][POINTER] TWFH Active Mission",
        expected_marker=f"<!-- wfh-mission-pointer:v1 mission={mission_id} -->",
        initialize=initialize,
    )
    _validate_issue_identity(
        current_mission,
        expected_title=f"[MISSION] {mission_id} — Model Excellence v3",
        expected_marker=f"<!-- wfh-mission-state:v1 mission={mission_id} -->",
        initialize=initialize,
    )
    _github_edit_issue(repository, pointer_issue, pointer_body, token)
    _github_edit_issue(repository, mission_issue, mission_body, token)
    comments = _github_list_issue_comments(repository, mission_issue, token)
    marker = _checkpoint_marker(pointer)
    already_recorded = any(
        isinstance(comment, dict) and marker in str(comment.get("body") or "")
        for comment in comments
    )
    if not already_recorded:
        _github_comment_issue(
            repository,
            mission_issue,
            render_checkpoint_comment(checkpoint, pointer),
            token,
        )
    return {
        "status": "SYNCED",
        "reason": None,
        "checkpoint_id": pointer["checkpoint_id"],
        "checkpoint_comment_created": not already_recorded,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WaterfallHunter mission continuity controller")
    subparsers = parser.add_subparsers(dest="command", required=True)
    resume = subparsers.add_parser("resume", help="resume the active TWFH mission")
    resume.add_argument("--intent", required=True)
    resume.add_argument("--json", action="store_true")
    resume.add_argument("--observed-main-sha")
    resume.add_argument("--observed-production-sha")
    resume.add_argument("--observed-branch-head")
    resume.add_argument("--observed-branch")
    resume.add_argument("--observed-worktree")
    resume.add_argument("--observed-worktree-status", choices=("clean", "dirty"))
    resume.add_argument("--capability", action="append", default=[])
    sync = subparsers.add_parser("sync-github", help="mirror active mission state to existing GitHub issues")
    sync.add_argument("--repository", required=True)
    sync.add_argument("--pointer-issue", required=True, type=int)
    sync.add_argument("--mission-issue", required=True, type=int)
    sync.add_argument("--initialize", action="store_true")
    sync.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    control_root = Path(os.environ.get("WFH_MISSION_CONTROL_ROOT", DEFAULT_CONTROL_ROOT))

    if args.command == "resume":
        normalized = normalize_resume_intent(args.intent)
        if normalized != CANONICAL_RESUME_INTENT:
            result = {"disposition": "RESUME_BLOCKED", "reason": "resume_intent_mismatch"}
            _emit_result(result, as_json=args.json)
            return 2
        try:
            mission_dir = resolve_active_mission(control_root)
            capabilities = _parse_capabilities(args.capability)
            result = resume_guard(
                mission_dir,
                observed_main_sha=args.observed_main_sha,
                observed_production_sha=args.observed_production_sha,
                observed_branch_head=args.observed_branch_head,
                observed_branch=args.observed_branch,
                observed_worktree=args.observed_worktree,
                observed_worktree_dirty=(
                    None
                    if args.observed_worktree_status is None
                    else args.observed_worktree_status == "dirty"
                ),
                capabilities=capabilities,
            )
        except (OSError, ValueError, KeyError) as exc:
            result = {
                "disposition": "RESUME_BLOCKED",
                "reason": "active_mission_resolution_failed",
                "error_type": type(exc).__name__,
            }
        _emit_result(result, as_json=args.json)
        return _resume_exit_code(str(result.get("disposition")))

    try:
        mission_dir = resolve_active_mission(control_root)
        result = sync_github(
            mission_dir,
            repository=args.repository,
            pointer_issue=args.pointer_issue,
            mission_issue=args.mission_issue,
            initialize=args.initialize,
        )
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        result = {"status": "BLOCKED", "reason": type(exc).__name__}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(f"{result.get('status')}: {result.get('reason') or 'ok'}")
    return 0 if result.get("status") == "SYNCED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
