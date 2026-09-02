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

    result = mission.sync_github(
        root,
        repository="cavack/wfh",
        pointer_issue=100,
        mission_issue=101,
    )

    assert result == {"status": "UNAVAILABLE", "reason": "gh_cli_unavailable"}
    assert mission.load_latest_checkpoint(root)["disposition"] == "RESUME_READY"


def test_sync_is_idempotent_and_checkpoint_comment_is_not_duplicated(
    monkeypatch, tmp_path: Path
) -> None:
    root = _mission_dir(tmp_path)
    monkeypatch.setattr(mission.shutil, "which", lambda _: "/usr/bin/gh")
    calls: list[list[str]] = []
    checkpoint_comment: list[str] = []

    def fake_run(args: list[str]) -> str:
        calls.append(args)
        if args[0] == "api":
            return json.dumps([{"body": checkpoint_comment[0]}] if checkpoint_comment else [])
        if args[:2] == ["issue", "comment"]:
            checkpoint_comment.append(args[args.index("--body") + 1])
        return ""

    monkeypatch.setattr(mission, "_run_gh", fake_run)
    first = mission.sync_github(
        root,
        repository="cavack/wfh",
        pointer_issue=100,
        mission_issue=101,
    )
    second = mission.sync_github(
        root,
        repository="cavack/wfh",
        pointer_issue=100,
        mission_issue=101,
    )

    assert first["status"] == "SYNCED"
    assert second["status"] == "SYNCED"
    comment_calls = [call for call in calls if call[:2] == ["issue", "comment"]]
    edit_calls = [call for call in calls if call[:2] == ["issue", "edit"]]
    assert len(comment_calls) == 1
    assert len(edit_calls) == 4
    flattened = "\n".join(" ".join(call) for call in calls)
    assert "workflow run" not in flattened
    assert "deploy" not in flattened.lower()


def test_cli_help_includes_sync_github_command(capsys) -> None:
    try:
        mission.main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    help_text = capsys.readouterr().out
    assert "sync-github" in help_text
