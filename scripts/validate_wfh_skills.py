from __future__ import annotations

import re
import sys
from pathlib import Path

EXPECTED_SKILLS = {
    "engineering-orchestrator",
    "repository-architecture-auditor",
    "runtime-reliability-performance",
    "backend-data-architecture",
    "api-contract-schema-guardian",
    "frontend-dashboard-ux",
    "strategy-score-lifecycle",
    "scientific-backtest-validation",
    "market-data-evidence-quality",
    "verification-regression",
    "security-supply-chain",
    "observability-incident-response",
    "release-production-certification",
}

REQUIRED_HEADINGS = {
    "## Overview",
    "## When to Use",
    "## Scope",
    "## Workflow",
    "## Evidence and Readiness",
    "## Verification",
    "## Handoffs",
    "## Common Mistakes",
}

NAME_RE = re.compile(r"^[a-z0-9-]+$")
PLACEHOLDER_RE = re.compile(
    r"\b(?:TBD|TODO|FIXME)\b|implement later|fill in details",
    flags=re.IGNORECASE,
)


def _parse_frontmatter(text: str, path: Path) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, [f"{path}: missing opening YAML frontmatter delimiter"]

    try:
        closing = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}, [f"{path}: missing closing YAML frontmatter delimiter"]

    raw = "\n".join(lines[: closing + 1])
    if len(raw) > 1024:
        errors.append(f"{path}: frontmatter exceeds 1024 characters")

    values: dict[str, str] = {}
    for line in lines[1:closing]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            errors.append(f"{path}: invalid frontmatter line: {stripped!r}")
            continue
        key, value = stripped.split(":", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")

    return values, errors


def _validate_skill(path: Path, expected_name: str) -> list[str]:
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: unable to read: {exc}"]

    frontmatter, frontmatter_errors = _parse_frontmatter(text, path)
    errors.extend(frontmatter_errors)

    name = frontmatter.get("name")
    description = frontmatter.get("description")

    if not name:
        errors.append(f"{path}: frontmatter field 'name' is required")
    else:
        if name != expected_name:
            errors.append(
                f"{path}: frontmatter name {name!r} must equal directory {expected_name!r}"
            )
        if not NAME_RE.fullmatch(name):
            errors.append(f"{path}: name must match ^[a-z0-9-]+$")

    if not description:
        errors.append(f"{path}: frontmatter field 'description' is required")
    else:
        if not description.startswith("Use when"):
            errors.append(f"{path}: description must start with 'Use when'")
        if len(description) > 500:
            errors.append(f"{path}: description exceeds 500 characters")

    body_lines = text.splitlines()
    title_lines = [line for line in body_lines if line.startswith("# ")]
    if not title_lines:
        errors.append(f"{path}: missing top-level '# ' title")

    for heading in sorted(REQUIRED_HEADINGS):
        if heading not in text:
            errors.append(f"{path}: missing required heading {heading!r}")

    match = PLACEHOLDER_RE.search(text)
    if match:
        errors.append(f"{path}: contains placeholder text {match.group(0)!r}")

    return errors


def validate(root: Path) -> list[str]:
    root = root.resolve()
    skill_root = root / "skills" / "waterfallhunter"
    errors: list[str] = []

    readme = skill_root / "README.md"
    if not readme.is_file():
        errors.append(f"{readme}: missing system README")

    if skill_root.is_dir():
        actual_dirs = {
            path.name
            for path in skill_root.iterdir()
            if path.is_dir() and path.name != "tests"
        }
        unexpected = sorted(actual_dirs - EXPECTED_SKILLS)
        for name in unexpected:
            errors.append(f"{skill_root / name}: unexpected skill directory")

    for name in sorted(EXPECTED_SKILLS):
        skill_file = skill_root / name / "SKILL.md"
        if not skill_file.is_file():
            errors.append(f"{skill_file}: missing skill file")
            continue
        errors.extend(_validate_skill(skill_file, name))

    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = validate(root)
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
