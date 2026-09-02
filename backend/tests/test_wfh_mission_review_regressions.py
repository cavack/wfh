from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from scripts import wfh_mission as mission


def _state(**overrides: object) -> dict[str, object]:
    state: dict[str, object] = {
        "contract_version": mission.MISSION_CONTRACT,
        "mission_id": "WFH-ME-V3-20260902",
        "project": "TWFH",
        "repository": "cavack/wfh",
        "baseline_main_sha": "a" * 40,
        "current_main_sha": "b" * 40,
        "production_sha": "c" * 40,
        "current_phase": "M-1",
        "current_task": "M-1.9",
        "next_action": "continue continuity hardening",
        "active_branch_head": "d" * 40,
        "active_branch": "feat/mission-continuity-v1-20260902",
        "active_worktree": "/srv/wfh-worktrees/mission-continuity-v1-20260902",
        "active_worktree_dirty": False,
        "required_capabilities": [],
    }
    state.update(overrides)
    return state


def _root(tmp_path: Path, **overrides: object) -> Path:
    root = tmp_path / "WFH-ME-V3-20260902"
    root.mkdir()
    mission.atomic_write_json(root / "MISSION_STATE.json", _state(**overrides), allowed_root=root)
    mission.atomic_write_json(root / "TASK_GRAPH.json", {"tasks": []}, allowed_root=root)
    mission.atomic_write_json(root / "EVIDENCE_LEDGER.json", {"records": []}, allowed_root=root)
    return root


def _observations() -> dict[str, object]:
    return {
        "observed_main_sha": "b" * 40,
        "observed_production_sha": "c" * 40,
        "observed_branch_head": "d" * 40,
        "observed_branch": "feat/mission-continuity-v1-20260902",
        "observed_worktree": "/srv/wfh-worktrees/mission-continuity-v1-20260902",
        "observed_worktree_dirty": False,
    }


def test_atomic_write_fsyncs_parent_after_replace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "mission"
    root.mkdir()
    events: list[str] = []
    original_replace = mission.os.replace
    monkeypatch.setattr(mission.os, "replace", lambda src, dst: (original_replace(src, dst), events.append("replace"))[0])
    monkeypatch.setattr(mission, "_fsync_directory", lambda path: events.append(f"fsync:{Path(path).name}"), raising=False)
    mission.atomic_write_json(root / "state.json", {"ok": True}, allowed_root=root)
    assert events == ["replace", "fsync:mission"]


def test_absent_durable_file_appearing_requires_reconciliation(tmp_path: Path) -> None:
    root = _root(tmp_path)
    mission.create_checkpoint(root, created_at="2026-09-02T16:30:00Z")
    mission.atomic_write_json(root / "BRANCH_REGISTRY.json", {"records": []}, allowed_root=root)
    result = mission.resume_guard(root, **_observations(), capabilities={})
    assert result["disposition"] == "RECONCILIATION_REQUIRED"
    assert result["reason"] == "uncheckpointed_state_change"
    assert "BRANCH_REGISTRY.json" in result["changed_state_files"]


def test_checkpoint_rejects_invalid_graph_and_evidence(tmp_path: Path) -> None:
    root = _root(tmp_path)
    tasks = [{"task_id": f"T{i}", "state": "IN_PROGRESS", "parents": []} for i in range(4)]
    mission.atomic_write_json(root / "TASK_GRAPH.json", {"tasks": tasks}, allowed_root=root)
    mission.atomic_write_json(
        root / "EVIDENCE_LEDGER.json",
        {"records": [{"evidence_id": "E-1", "classification": "MAYBE"}]},
        allowed_root=root,
    )
    with pytest.raises(ValueError):
        mission.create_checkpoint(root)
    assert not (root / "LATEST_CHECKPOINT.json").exists()


def test_active_pointer_mission_mismatch_is_rejected(tmp_path: Path) -> None:
    control = tmp_path / "control"
    mission_dir = control / "mission-b"
    mission_dir.mkdir(parents=True)
    mission.atomic_write_json(mission_dir / "MISSION_STATE.json", _state(mission_id="MISSION-B"), allowed_root=mission_dir)
    mission.atomic_write_json(control / "ACTIVE_MISSION.json", {"mission_id": "MISSION-A", "mission_path": "mission-b"}, allowed_root=control)
    with pytest.raises(ValueError, match="mission identity"):
        mission.resolve_active_mission(control)


def test_github_comment_listing_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_request(repository: str, endpoint: str, **kwargs):
        calls.append(endpoint)
        if "&page=1" in endpoint:
            return [{"body": str(i)} for i in range(100)]
        if "&page=2" in endpoint:
            return [{"body": "last"}]
        raise AssertionError(endpoint)

    monkeypatch.setattr(mission, "_github_request", fake_request)
    comments = mission._github_list_issue_comments("cavack/wfh", 113, "token")
    assert len(comments) == 101
    assert any("&page=1" in call for call in calls)
    assert any("&page=2" in call for call in calls)


def test_sync_rejects_swapped_issue_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    mission.create_checkpoint(root)
    monkeypatch.setattr(mission, "_github_token", lambda: "token")
    monkeypatch.setattr(
        mission,
        "_github_get_issue",
        lambda repository, issue_number, token: {"title": "[MISSION] wrong", "body": "<!-- wfh-mission-state:v1 mission=WFH-ME-V3-20260902 -->"},
        raising=False,
    )
    with pytest.raises(ValueError, match="identity"):
        mission.sync_github(root, repository="cavack/wfh", pointer_issue=114, mission_issue=113)


def test_declared_authority_is_not_an_observed_capability_state() -> None:
    with pytest.raises(ValueError, match="capability state"):
        mission._parse_capabilities(["github_connector=READ_WRITE_REPO"])


def test_ready_resume_requires_checkpointed_observations(tmp_path: Path) -> None:
    root = _root(tmp_path)
    mission.create_checkpoint(root)
    result = mission.resume_guard(root, capabilities={})
    assert result["disposition"] == "RESUME_BLOCKED"
    assert result["reason"] == "required_observation_unavailable"
    assert set(result["missing_observations"]) >= {
        "repository_main",
        "production_revision",
        "branch_head",
        "active_branch",
        "active_worktree",
        "worktree_cleanliness",
    }


def test_resume_projection_uses_checkpointed_journal_operation(tmp_path: Path) -> None:
    root = _root(tmp_path)
    mission.journal_step_start(
        root,
        task_id="M-1.9",
        step_id="STEP-42",
        action="run exact-head verification",
        expected_state_change="evidence only",
        pre_step_sha="d" * 40,
        required_capabilities=["pytest"],
        retry_policy="reconcile_before_retry",
        reconciliation_procedure="inspect process and artifacts",
    )
    mission.create_checkpoint(root)
    text = (root / "RESUME.md").read_text(encoding="utf-8")
    assert "STEP-42" in text
    assert "run exact-head verification" in text


def test_journal_mutations_enter_mission_lock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    events: list[str] = []

    @contextmanager
    def fake_lock(_root: Path):
        events.append("enter")
        yield
        events.append("exit")

    monkeypatch.setattr(mission, "_mission_lock", fake_lock, raising=False)
    mission.journal_step_start(
        root,
        task_id="M-1.9",
        step_id="LOCK-1",
        action="test lock",
        expected_state_change="journal",
        pre_step_sha="d" * 40,
        required_capabilities=[],
        retry_policy="reconcile_before_retry",
        reconciliation_procedure="inspect journal",
    )
    mission.journal_step_complete(root, "LOCK-1")
    assert events == ["enter", "exit", "enter", "exit"]
