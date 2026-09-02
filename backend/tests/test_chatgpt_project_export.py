from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import export_chatgpt_project_sources as exporter


EXPECTED_FILES = {
    "00-WFH-CHATGPT-ROUTER-v2.md",
    "01-WFH-SKILL-CATALOG-v2.md",
    "02-WFH-CAPABILITY-MAP-v2.md",
    "03-WFH-SKILL-AUDIT-SUMMARY-v2.md",
    "PROJECT-INSTRUCTIONS-v2.txt",
    "INSTALL-FA-v2.md",
    "PROJECT-SOURCE-MANIFEST.json",
}


def test_export_is_lightweight_complete_and_hash_verified(tmp_path: Path) -> None:
    out = tmp_path / "sources"
    exporter.export_project_sources(out)

    assert {path.name for path in out.iterdir()} == EXPECTED_FILES
    assert not list(out.rglob("SKILL.md"))

    manifest = json.loads((out / "PROJECT-SOURCE-MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["contract_version"] == "wfh_chatgpt_project_sources_v2"
    assert manifest["canonical_repository"] == "cavack/wfh"
    assert manifest["canonical_skill_root"] == "skills/waterfallhunter"
    assert len(manifest["skills"]) == 14
    assert "skill-system-curator" in manifest["skills"]

    for name, expected_hash in manifest["sha256"].items():
        payload = (out / name).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == expected_hash


def test_export_is_deterministic_for_same_repository_state(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    exporter.export_project_sources(first)
    exporter.export_project_sources(second)

    for name in EXPECTED_FILES:
        assert (first / name).read_bytes() == (second / name).read_bytes()
