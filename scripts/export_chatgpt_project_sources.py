#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "docs" / "chatgpt-project"
EXPORT_ROOT = REPO_ROOT / ".work"
DEFAULT_EXPORT_DIR = EXPORT_ROOT / "chatgpt-project-sources-v2"
OVERLAY_FILES = (
    "00-WFH-CHATGPT-ROUTER-v2.md",
    "01-WFH-SKILL-CATALOG-v2.md",
    "02-WFH-CAPABILITY-MAP-v2.md",
    "03-WFH-SKILL-AUDIT-SUMMARY-v2.md",
    "PROJECT-INSTRUCTIONS-v2.txt",
    "INSTALL-FA-v2.md",
    "TWFH-RESUME.md",
)
EXPECTED_EXPORT_FILES = {*OVERLAY_FILES, "PROJECT-SOURCE-MANIFEST.json"}


def _overlay_paths() -> tuple[tuple[str, Path, Path], ...]:
    return (
        ("00-WFH-CHATGPT-ROUTER-v2.md", SOURCE_DIR / "00-WFH-CHATGPT-ROUTER-v2.md", DEFAULT_EXPORT_DIR / "00-WFH-CHATGPT-ROUTER-v2.md"),
        ("01-WFH-SKILL-CATALOG-v2.md", SOURCE_DIR / "01-WFH-SKILL-CATALOG-v2.md", DEFAULT_EXPORT_DIR / "01-WFH-SKILL-CATALOG-v2.md"),
        ("02-WFH-CAPABILITY-MAP-v2.md", SOURCE_DIR / "02-WFH-CAPABILITY-MAP-v2.md", DEFAULT_EXPORT_DIR / "02-WFH-CAPABILITY-MAP-v2.md"),
        ("03-WFH-SKILL-AUDIT-SUMMARY-v2.md", SOURCE_DIR / "03-WFH-SKILL-AUDIT-SUMMARY-v2.md", DEFAULT_EXPORT_DIR / "03-WFH-SKILL-AUDIT-SUMMARY-v2.md"),
        ("PROJECT-INSTRUCTIONS-v2.txt", SOURCE_DIR / "PROJECT-INSTRUCTIONS-v2.txt", DEFAULT_EXPORT_DIR / "PROJECT-INSTRUCTIONS-v2.txt"),
        ("INSTALL-FA-v2.md", SOURCE_DIR / "INSTALL-FA-v2.md", DEFAULT_EXPORT_DIR / "INSTALL-FA-v2.md"),
        ("TWFH-RESUME.md", SOURCE_DIR / "TWFH-RESUME.md", DEFAULT_EXPORT_DIR / "TWFH-RESUME.md"),
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


def _git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
    ).strip()


def _source_provenance() -> dict[str, object]:
    commit = _git_output("rev-parse", "HEAD")
    ref = _git_output("branch", "--show-current") or "DETACHED"
    dirty = bool(_git_output("status", "--porcelain", "--untracked-files=no"))
    return {
        "source_commit_sha": commit,
        "source_ref": ref,
        "source_worktree_dirty": dirty,
    }


def _assert_no_unexpected_export_content() -> None:
    if not DEFAULT_EXPORT_DIR.exists():
        return
    entries = list(DEFAULT_EXPORT_DIR.rglob("*"))
    symlinks = sorted(
        str(path.relative_to(DEFAULT_EXPORT_DIR))
        for path in entries
        if path.is_symlink()
    )
    if symlinks:
        raise ValueError(f"symlink entries are forbidden in export destination: {symlinks}")
    unexpected = sorted(
        str(path.relative_to(DEFAULT_EXPORT_DIR))
        for path in entries
        if str(path.relative_to(DEFAULT_EXPORT_DIR)) not in EXPECTED_EXPORT_FILES
    )
    if unexpected:
        raise ValueError(f"unexpected stale export content: {unexpected}")


def export_project_sources() -> Path:
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    _confined_path(DEFAULT_EXPORT_DIR, EXPORT_ROOT, label="destination")
    _assert_no_unexpected_export_content()
    DEFAULT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    payloads: dict[str, bytes] = {}
    for name, source_path, target_path in _overlay_paths():
        source = _confined_path(source_path, SOURCE_DIR, label="source", strict=True)
        target = _confined_path(target_path, DEFAULT_EXPORT_DIR, label="export target")
        payload = _normalized_bytes(source)
        target.write_bytes(payload)
        payloads[name] = payload

    hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in payloads.items()}
    manifest = {
        "contract_version": "wfh_chatgpt_project_sources_v2",
        "canonical_repository": "cavack/wfh",
        "canonical_ref_policy": "resolve current target SHA in GitHub at execution time",
        "canonical_skill_root": "skills/waterfallhunter",
        "council_contract": "wfh_agent_council_v2",
        "skills": _skills(),
        "overlay_files": list(OVERLAY_FILES),
        "sha256": hashes,
        **_source_provenance(),
    }
    manifest_path = _confined_path(
        DEFAULT_EXPORT_DIR / "PROJECT-SOURCE-MANIFEST.json",
        DEFAULT_EXPORT_DIR,
        label="manifest target",
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export the ChatGPT Project Sources overlay to the fixed repository-local .work directory"
    )
    parser.parse_args(argv)
    export_project_sources()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
