#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

CANONICAL_DOCS = {
    "docs/ARCHITECTURE.md", "docs/MODEL.md", "docs/DECISION_ENGINE.md",
    "docs/DASHBOARD.md", "docs/DATA_AND_DATABASE.md", "docs/OPERATIONS.md",
    "docs/DEPLOYMENT.md", "docs/BACKUP_RESTORE.md", "docs/TELEGRAM.md",
    "docs/AI_ADVISORY.md", "docs/TROUBLESHOOTING.md",
    "docs/DEVELOPER_ONBOARDING.md", "docs/PROJECT_HANDOFF.md",
}
WORKFLOW_ALLOWLIST = {"ci.yml", "deploy-production.yml"}
FORBIDDEN_PARTS = {".venv", "venv", "node_modules", ".next", ".pytest_cache", "__pycache__", ".work", "backup", "backups"}
FORBIDDEN_SUFFIXES = (".pyc", ".log", ".db", ".sqlite", ".sqlite3", ".tsbuildinfo", ".bak")
CONFLICT = re.compile(r"^(<<<<<<<|=======|>>>>>>>)", re.MULTILINE)


def tracked(root: Path) -> list[str]:
    out = subprocess.check_output(["git", "ls-files"], cwd=root, text=True)
    return [line.strip() for line in out.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate canonical WaterfallHunter repository hygiene.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    paths = tracked(root)
    errors: list[str] = []

    missing = sorted(CANONICAL_DOCS - set(paths))
    if missing:
        errors.append("missing canonical docs: " + ", ".join(missing))
    required = {"README.md", "CHANGELOG.md", "Makefile", ".env.example"}
    missing_root = sorted(required - set(paths))
    if missing_root:
        errors.append("missing root handoff files: " + ", ".join(missing_root))

    debris = [p for p in paths if FORBIDDEN_PARTS.intersection(Path(p).parts) or p.endswith(FORBIDDEN_SUFFIXES)]
    if debris:
        errors.append("tracked runtime/generated debris: " + ", ".join(sorted(debris)))

    workflows = {Path(p).name for p in paths if p.startswith(".github/workflows/")}
    if workflows != WORKFLOW_ALLOWLIST:
        errors.append(f"workflow set must be {sorted(WORKFLOW_ALLOWLIST)}, got {sorted(workflows)}")

    text_candidates = [p for p in paths if Path(p).suffix.lower() in {".md", ".py", ".ts", ".tsx", ".js", ".yml", ".yaml", ".txt", ""}]
    for rel in text_candidates:
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if CONFLICT.search(text):
            errors.append(f"conflict marker: {rel}")

    active_surface = ["README.md", *sorted(CANONICAL_DOCS)]
    for rel in active_surface:
        text = (root / rel).read_text(encoding="utf-8") if (root / rel).exists() else ""
        if "PAPER_ONLY" in text:
            errors.append(f"deprecated PAPER_ONLY terminology in canonical surface: {rel}")

    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print(f"repository_hygiene=PASS tracked_files={len(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
