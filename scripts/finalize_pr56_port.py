#!/usr/bin/env python3
from __future__ import annotations

import subprocess
from pathlib import Path

BASE = "d6a23c1f69794aac31b1dce5e5a07ea69b614585"
EXPECTED_MERGE_HEAD = "ff462dfa186964a2180aa57611a4c6a2c0641bb3"
BRANCH = "fix/v7-runtime-hardening-port"
MESSAGE = "fix(runtime): port PR56 hardening onto current main"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("$ " + " ".join(args), flush=True)
    p = subprocess.run(args, text=True, capture_output=True)
    if p.stdout:
        print(p.stdout, end="")
    if p.stderr:
        print(p.stderr, end="")
    if check and p.returncode != 0:
        raise SystemExit(p.returncode)
    return p


def git(*args: str, check: bool = True) -> str:
    return run("git", *args, check=check).stdout.strip()


root = Path.cwd()
if not (root / "backend").is_dir():
    raise SystemExit("RUN_FROM_PORT_WORKTREE")

head = git("rev-parse", "HEAD")
if head != BASE:
    raise SystemExit(f"ABORT_WRONG_HEAD={head}")

merge_head = git("rev-parse", "MERGE_HEAD")
if merge_head != EXPECTED_MERGE_HEAD:
    raise SystemExit(f"ABORT_WRONG_MERGE_HEAD={merge_head}")

unmerged = git("diff", "--name-only", "--diff-filter=U")
if unmerged:
    raise SystemExit("ABORT_UNMERGED_FILES\n" + unmerged)

run("git", "diff", "--cached", "--check")

changed = git("diff", "--cached", "--name-only").splitlines()
if not changed:
    raise SystemExit("ABORT_EMPTY_INDEX")
if any(path.startswith("frontend/") for path in changed):
    raise SystemExit("ABORT_FRONTEND_CHANGED")

# Capture the exact tree that already passed validation, then create a single-parent
# commit on current main. This intentionally avoids carrying the 85-commit PR56
# ancestry into the replacement PR.
tree = git("write-tree")
commit = run(
    "git", "commit-tree", tree, "-p", BASE,
    input=None if False else None,
    check=False,
)
# subprocess helper above cannot feed stdin; invoke commit-tree once with input.
p = subprocess.run(
    ["git", "commit-tree", tree, "-p", BASE],
    input=MESSAGE + "\n",
    text=True,
    capture_output=True,
)
if p.returncode != 0:
    if p.stdout:
        print(p.stdout, end="")
    if p.stderr:
        print(p.stderr, end="")
    raise SystemExit(p.returncode)
commit = p.stdout.strip()
if len(commit) != 40:
    raise SystemExit(f"ABORT_INVALID_COMMIT={commit}")

run("git", "reset", "--hard", commit)

parents = git("show", "-s", "--format=%P", commit).split()
if parents != [BASE]:
    raise SystemExit(f"ABORT_NOT_SINGLE_PARENT={parents}")

if git("status", "--porcelain"):
    raise SystemExit("ABORT_DIRTY_AFTER_RESET")

run("git", "push", "-u", "origin", f"HEAD:{BRANCH}")

remote = git("ls-remote", "origin", f"refs/heads/{BRANCH}").split()
remote_sha = remote[0] if remote else ""
if remote_sha != commit:
    raise SystemExit(f"ABORT_REMOTE_MISMATCH={remote_sha}")

print("FINALIZE_STATUS=PASS")
print(f"PORT_COMMIT={commit}")
print(f"PARENT={BASE}")
print(f"REMOTE_BRANCH={BRANCH}")
print("SINGLE_PARENT=YES")
print("NO_PRODUCTION_CHANGE=YES")
