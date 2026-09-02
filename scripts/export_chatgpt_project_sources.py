#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "docs" / "chatgpt-project"
OVERLAY_FILES = (
    "00-WFH-CHATGPT-ROUTER-v2.md",
    "01-WFH-SKILL-CATALOG-v2.md",
    "02-WFH-CAPABILITY-MAP-v2.md",
    "03-WFH-SKILL-AUDIT-SUMMARY-v2.md",
    "PROJECT-INSTRUCTIONS-v2.txt",
    "INSTALL-FA-v2.md",
)


def _normalized_bytes(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")


def _skills() -> list[str]:
    root = REPO_ROOT / "skills" / "waterfallhunter"
    return sorted(path.parent.name for path in root.glob("*/SKILL.md"))


def _confined_path(path: Path, allowed_root: Path, *, label: str, strict: bool = False) -> Path:
    root = Path(allowed_root).resolve(strict=True)
    candidate = Path(path).resolve(strict=strict)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} must stay within allowed root {root}") from exc
    return candidate


def export_project_sources(destination: Path, *, allowed_root: Path) -> Path:
    destination = _confined_path(destination, allowed_root, label="destination")
    destination.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    source_root = SOURCE_DIR.resolve(strict=True)
    for name in OVERLAY_FILES:
        source = _confined_path(source_root / name, source_root, label="source", strict=True)
        target = _confined_path(destination / name, destination, label="export target")
        payload = _normalized_bytes(source)
        target.write_bytes(payload)
        hashes[name] = hashlib.sha256(payload).hexdigest()

    manifest = {
        "contract_version": "wfh_chatgpt_project_sources_v2",
        "canonical_repository": "cavack/wfh",
        "canonical_ref_policy": "resolve current target SHA in GitHub at execution time",
        "canonical_skill_root": "skills/waterfallhunter",
        "council_contract": "wfh_agent_council_v2",
        "skills": _skills(),
        "overlay_files": list(OVERLAY_FILES),
        "sha256": hashes,
    }
    manifest_path = _confined_path(
        destination / "PROJECT-SOURCE-MANIFEST.json", destination, label="manifest target"
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    export_project_sources(args.destination, allowed_root=REPO_ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
