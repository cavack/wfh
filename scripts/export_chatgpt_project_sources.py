#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "docs" / "chatgpt-project"
EXPORT_ROOT = REPO_ROOT / ".work"
DEFAULT_EXPORT_DIR = EXPORT_ROOT / "chatgpt-project-sources-v2"
ROUTER_FILE = "00-WFH-CHATGPT-ROUTER-v2.md"
CATALOG_FILE = "01-WFH-SKILL-CATALOG-v2.md"
CAPABILITY_FILE = "02-WFH-CAPABILITY-MAP-v2.md"
AUDIT_FILE = "03-WFH-SKILL-AUDIT-SUMMARY-v2.md"
INSTRUCTIONS_FILE = "PROJECT-INSTRUCTIONS-v2.txt"
INSTALL_FILE = "INSTALL-FA-v2.md"
RESUME_FILE = "TWFH-RESUME.md"
MANIFEST_FILE = "PROJECT-SOURCE-MANIFEST.json"
SOURCE_LABEL = "source"

OVERLAY_FILES = (
    ROUTER_FILE,
    CATALOG_FILE,
    CAPABILITY_FILE,
    AUDIT_FILE,
    INSTRUCTIONS_FILE,
    INSTALL_FILE,
    RESUME_FILE,
)

EXPECTED_EXPORT_FILES = {*OVERLAY_FILES, MANIFEST_FILE}


def _normalized_bytes(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")


def _write_all(fd: int, payload: bytes) -> None:
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise OSError("failed to write export payload")
            remaining = remaining[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


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

    router = _normalized_bytes(_confined_path(SOURCE_DIR / ROUTER_FILE, SOURCE_DIR, label=SOURCE_LABEL, strict=True))
    catalog = _normalized_bytes(_confined_path(SOURCE_DIR / CATALOG_FILE, SOURCE_DIR, label=SOURCE_LABEL, strict=True))
    capability = _normalized_bytes(_confined_path(SOURCE_DIR / CAPABILITY_FILE, SOURCE_DIR, label=SOURCE_LABEL, strict=True))
    audit = _normalized_bytes(_confined_path(SOURCE_DIR / AUDIT_FILE, SOURCE_DIR, label=SOURCE_LABEL, strict=True))
    instructions = _normalized_bytes(_confined_path(SOURCE_DIR / INSTRUCTIONS_FILE, SOURCE_DIR, label=SOURCE_LABEL, strict=True))
    install = _normalized_bytes(_confined_path(SOURCE_DIR / INSTALL_FILE, SOURCE_DIR, label=SOURCE_LABEL, strict=True))
    resume = _normalized_bytes(_confined_path(SOURCE_DIR / RESUME_FILE, SOURCE_DIR, label=SOURCE_LABEL, strict=True))

    try:
        no_follow = os.O_NOFOLLOW
        directory = os.O_DIRECTORY
    except AttributeError as exc:
        raise RuntimeError("secure export requires O_NOFOLLOW and O_DIRECTORY") from exc
    file_flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | no_follow
    dir_flags = os.O_RDONLY | directory | no_follow
    export_dir_fd = os.open(DEFAULT_EXPORT_DIR, dir_flags)
    try:
        _write_all(os.open(ROUTER_FILE, file_flags, 0o600, dir_fd=export_dir_fd), router)
        _write_all(os.open(CATALOG_FILE, file_flags, 0o600, dir_fd=export_dir_fd), catalog)
        _write_all(os.open(CAPABILITY_FILE, file_flags, 0o600, dir_fd=export_dir_fd), capability)
        _write_all(os.open(AUDIT_FILE, file_flags, 0o600, dir_fd=export_dir_fd), audit)
        _write_all(os.open(INSTRUCTIONS_FILE, file_flags, 0o600, dir_fd=export_dir_fd), instructions)
        _write_all(os.open(INSTALL_FILE, file_flags, 0o600, dir_fd=export_dir_fd), install)
        _write_all(os.open(RESUME_FILE, file_flags, 0o600, dir_fd=export_dir_fd), resume)
        os.fsync(export_dir_fd)
    finally:
        os.close(export_dir_fd)

    payloads = {
        ROUTER_FILE: router,
        CATALOG_FILE: catalog,
        CAPABILITY_FILE: capability,
        AUDIT_FILE: audit,
        INSTRUCTIONS_FILE: instructions,
        INSTALL_FILE: install,
        RESUME_FILE: resume,
    }
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
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    export_dir_fd = os.open(DEFAULT_EXPORT_DIR, dir_flags)
    try:
        _write_all(os.open(MANIFEST_FILE, file_flags, 0o600, dir_fd=export_dir_fd), manifest_bytes)
        os.fsync(export_dir_fd)
    finally:
        os.close(export_dir_fd)
    return DEFAULT_EXPORT_DIR / MANIFEST_FILE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export the ChatGPT Project Sources overlay to the fixed repository-local .work directory"
    )
    parser.parse_args(argv)
    export_project_sources()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
