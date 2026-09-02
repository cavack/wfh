from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from scripts import wfh_mission as mission


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/wfh_mission.py"


def _state() -> dict[str, object]:
    return {
        "contract_version": mission.MISSION_CONTRACT,
        "mission_id": "WFH-ME-V3-20260902",
        "project": "TWFH",
        "repository": "cavack/wfh",
        "baseline_main_sha": "a" * 40,
        "current_main_sha": "b" * 40,
        "current_phase": "M0",
        "current_task": "M0.5",
        "next_action": "continue Task 5",
        "required_capabilities": [],
    }


def _control_root(tmp_path: Path) -> Path:
    control = tmp_path / "mission-control"
    mission_dir = control / "WFH-ME-V3-20260902"
    mission_dir.mkdir(parents=True)
    mission.atomic_write_json(mission_dir / "MISSION_STATE.json", _state(), allowed_root=mission_dir)
    mission.create_checkpoint(mission_dir, created_at="2026-09-02T15:10:00Z")
    mission.atomic_write_json(
        control / "ACTIVE_MISSION.json",
        {
            "contract_version": "wfh_active_mission_v1",
            "mission_id": "WFH-ME-V3-20260902",
            "mission_path": "WFH-ME-V3-20260902",
        },
        allowed_root=control,
    )
    return control


def _run(control: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["WFH_MISSION_CONTROL_ROOT"] = str(control)
    return subprocess.run(
        ["python3", str(SCRIPT), *args],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_rejects_noncanonical_resume_phrase(tmp_path: Path) -> None:
    control = _control_root(tmp_path)
    proc = _run(control, "resume", "--intent", "ادامه پروژه", "--json")

    assert proc.returncode != 0
    output = json.loads(proc.stdout)
    assert output["reason"] == "resume_intent_mismatch"


def test_cli_canonical_phrase_returns_json_from_active_mission(tmp_path: Path) -> None:
    control = _control_root(tmp_path)
    proc = _run(control, "resume", "--intent", "ادامه کار گروهی", "--json")

    assert proc.returncode == 0, proc.stderr
    output = json.loads(proc.stdout)
    assert output["disposition"] == "RESUME_READY"
    assert output["checkpoint"]["mission_id"] == "WFH-ME-V3-20260902"
    assert output["checkpoint"]["mission_state"]["next_action"] == "continue Task 5"


def test_cli_normalizes_unicode_whitespace_for_canonical_phrase(tmp_path: Path) -> None:
    control = _control_root(tmp_path)
    proc = _run(control, "resume", "--intent", "  ادامه   کار\tگروهی  ", "--json")

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["disposition"] == "RESUME_READY"


def test_cli_corrupt_checkpoint_pointer_returns_nonzero(tmp_path: Path) -> None:
    control = _control_root(tmp_path)
    (control / "WFH-ME-V3-20260902" / "LATEST_CHECKPOINT.json").write_text(
        "{not-json}\n", encoding="utf-8"
    )

    proc = _run(control, "resume", "--intent", "ادامه کار گروهی", "--json")

    assert proc.returncode != 0
    output = json.loads(proc.stdout)
    assert output["disposition"] == "RESUME_BLOCKED"
