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
    exporter.export_project_sources(out, allowed_root=tmp_path)

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
    exporter.export_project_sources(first, allowed_root=tmp_path)
    exporter.export_project_sources(second, allowed_root=tmp_path)

    for name in EXPECTED_FILES:
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_export_rejects_destination_outside_allowed_root(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"

    try:
        exporter.export_project_sources(outside, allowed_root=allowed)
    except ValueError as exc:
        assert "allowed root" in str(exc).lower()
    else:
        raise AssertionError("export must reject destinations outside the allowed root")


def test_export_rejects_symlink_target_escape(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    out = allowed / "sources"
    out.mkdir(parents=True)
    escaped = tmp_path / "escaped.md"
    (out / "00-WFH-CHATGPT-ROUTER-v2.md").symlink_to(escaped)

    try:
        exporter.export_project_sources(out, allowed_root=allowed)
    except ValueError as exc:
        assert "escape" in str(exc).lower() or "allowed" in str(exc).lower()
    else:
        raise AssertionError("export must reject symlink targets escaping the destination")
