from __future__ import annotations

import json
from pathlib import Path

from scripts import wfh_mission as mission


def _state() -> dict[str, object]:
    return {
        "contract_version": mission.MISSION_CONTRACT,
        "mission_id": "WFH-ME-V3-20260902",
        "project": "TWFH",
        "repository": "cavack/wfh",
        "baseline_main_sha": "a" * 40,
        "current_main_sha": "b" * 40,
        "current_phase": "M0",
        "current_task": "M0.6",
        "next_action": "sync GitHub control plane",
        "active_branch": "feat/mission-continuity-v1-20260902",
        "active_worktree": "/srv/wfh-worktrees/mission-continuity-v1-20260902",
        "active_pr": None,
        "required_capabilities": [],
        "telegram_bot_token": "MUST_NOT_APPEAR",
        "api_key": "MUST_NOT_APPEAR_EITHER",
    }


def _mission_dir(tmp_path: Path) -> Path:
    root = tmp_path / "WFH-ME-V3-20260902"
    root.mkdir()
    mission.atomic_write_json(root / "MISSION_STATE.json", _state(), allowed_root=root)
    mission.atomic_write_json(root / "TASK_GRAPH.json", {"tasks": []}, allowed_root=root)
    mission.atomic_write_json(root / "EVIDENCE_LEDGER.json", {"records": []}, allowed_root=root)
    mission.create_checkpoint(root, created_at="2026-09-02T15:20:00Z")
    return root


def test_pointer_issue_body_contains_durable_resume_identity(tmp_path: Path) -> None:
    root = _mission_dir(tmp_path)
    loaded = mission.load_latest_checkpoint(root)
    pointer = loaded["pointer"]

    body = mission.render_pointer_issue(
        mission_id="WFH-ME-V3-20260902",
        mission_issue_number=321,
        pointer=pointer,
    )

    assert "<!-- wfh-mission-pointer:v1" in body
    assert "WFH-ME-V3-20260902" in body
    assert "#321" in body
    assert pointer["checkpoint_id"] in body
    assert pointer["sha256"] in body


def test_mission_issue_body_is_compact_and_secret_free(tmp_path: Path) -> None:
    root = _mission_dir(tmp_path)
    loaded = mission.load_latest_checkpoint(root)

    body = mission.render_mission_issue(loaded["checkpoint"], loaded["pointer"])

    assert "<!-- wfh-mission-state:v1" in body
    assert "M0.6" in body
    assert "sync GitHub control plane" in body
    assert "feat/mission-continuity-v1-20260902" in body
    assert "b" * 40 in body
    assert "MUST_NOT_APPEAR" not in body
    assert "telegram_bot_token" not in body
    assert "api_key" not in body


def test_sync_reports_unavailable_without_invalidating_local_checkpoint(
    monkeypatch, tmp_path: Path
) -> None:
    root = _mission_dir(tmp_path)
    monkeypatch.setattr(mission.shutil, "which", lambda _: None)
    monkeypatch.setattr(mission, "_github_token", lambda: None, raising=False)

    result = mission.sync_github(
        root,
        repository="cavack/wfh",
        pointer_issue=100,
        mission_issue=101,
    )

    assert result == {"status": "UNAVAILABLE", "reason": "github_auth_unavailable"}
    assert mission.load_latest_checkpoint(root)["disposition"] == "RESUME_READY"


def test_sync_is_idempotent_and_checkpoint_comment_is_not_duplicated(
    monkeypatch, tmp_path: Path
) -> None:
    root = _mission_dir(tmp_path)
    calls: list[tuple[str, int, str]] = []
    checkpoint_comment: list[str] = []

    monkeypatch.setattr(mission, "_github_token", lambda: "test-token", raising=False)

    def fake_get(repository: str, issue_number: int, token: str) -> dict[str, str]:
        assert repository == "cavack/wfh"
        assert token == "test-token"
        if issue_number == 100:
            return {
                "title": "[MISSION][POINTER] TWFH Active Mission",
                "body": "<!-- wfh-mission-pointer:v1 mission=WFH-ME-V3-20260902 -->",
            }
        return {
            "title": "[MISSION] WFH-ME-V3-20260902 — Model Excellence v3",
            "body": "<!-- wfh-mission-state:v1 mission=WFH-ME-V3-20260902 -->",
        }

    monkeypatch.setattr(mission, "_github_get_issue", fake_get, raising=False)
    assert not hasattr(mission, "_run_gh")

    def fake_edit(repository: str, issue_number: int, body: str, token: str) -> None:
        assert repository == "cavack/wfh"
        assert token == "test-token"
        calls.append(("edit", issue_number, body))

    def fake_list(repository: str, issue_number: int, token: str) -> list[dict[str, str]]:
        assert repository == "cavack/wfh"
        assert token == "test-token"
        calls.append(("list", issue_number, ""))
        return [{"body": checkpoint_comment[0]}] if checkpoint_comment else []

    def fake_comment(repository: str, issue_number: int, body: str, token: str) -> None:
        assert repository == "cavack/wfh"
        assert token == "test-token"
        calls.append(("comment", issue_number, body))
        checkpoint_comment.append(body)

    monkeypatch.setattr(mission, "_github_edit_issue", fake_edit, raising=False)
    monkeypatch.setattr(mission, "_github_list_issue_comments", fake_list, raising=False)
    monkeypatch.setattr(mission, "_github_comment_issue", fake_comment, raising=False)

    first = mission.sync_github(
        root, repository="cavack/wfh", pointer_issue=100, mission_issue=101
    )
    second = mission.sync_github(
        root, repository="cavack/wfh", pointer_issue=100, mission_issue=101
    )

    assert first["status"] == "SYNCED"
    assert second["status"] == "SYNCED"
    assert len([call for call in calls if call[0] == "comment"]) == 1
    assert len([call for call in calls if call[0] == "edit"]) == 4
    flattened = "\n".join(str(call) for call in calls)
    assert "workflow run" not in flattened
    assert "deploy" not in flattened.lower()


def test_cli_help_includes_sync_github_command(capsys) -> None:
    try:
        mission.main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    help_text = capsys.readouterr().out
    assert "sync-github" in help_text
