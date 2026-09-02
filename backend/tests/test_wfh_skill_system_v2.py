from __future__ import annotations

from pathlib import Path

from scripts import validate_wfh_skills as validator


REPO = Path(__file__).resolve().parents[2]


def test_v2_inventory_includes_skill_system_curator() -> None:
    assert "skill-system-curator" in validator.EXPECTED_SKILLS
    assert (REPO / "skills/waterfallhunter/skill-system-curator/SKILL.md").is_file()
    assert (REPO / ".agents/skills/skill-system-curator/SKILL.md").is_file()


def test_all_canonical_skills_expose_v2_operating_contract() -> None:
    headings = (
        "## Input Contract",
        "## Required Evidence",
        "## Tool Preference",
        "## Output Contract",
        "## Stop and Escalation Conditions",
    )
    for name in sorted(validator.EXPECTED_SKILLS):
        text = (REPO / "skills/waterfallhunter" / name / "SKILL.md").read_text(encoding="utf-8")
        for heading in headings:
            assert heading in text, f"{name} missing {heading}"


def test_static_validator_rejects_oversized_skill_body(tmp_path: Path) -> None:
    path = tmp_path / "SKILL.md"
    text = "# Skill\n" + "line\n" * 501
    errors = validator._validate_body(path, text)
    assert any("500 lines" in error for error in errors)
