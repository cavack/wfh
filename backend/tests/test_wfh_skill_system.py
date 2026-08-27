import re
from pathlib import Path

from scripts.validate_wfh_skills import EXPECTED_SKILLS, _parse_frontmatter, validate

ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "waterfallhunter"
ADAPTER_ROOT = ROOT / ".agents" / "skills"
PRODUCTION_STATES = ("DEPLOY_READY", "DEPLOYED_UNVERIFIED", "PRODUCTION_VERIFIED")
AUTHORIZATION_RE = re.compile(
    r"\b(?:may|can|shall|is authorized to|has authority to)\s+"
    r"(?:declare|certify|set|grant)\b",
    re.IGNORECASE,
)


def _skill_text(name: str) -> str:
    return (SKILL_ROOT / name / "SKILL.md").read_text(encoding="utf-8")


def _description(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("missing description")


def test_expected_skill_set_is_exact() -> None:
    assert EXPECTED_SKILLS == {
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


def test_skill_tree_passes_static_validation() -> None:
    assert validate(ROOT) == []


def test_discovery_adapters_delegate_to_canonical_skills() -> None:
    for name in EXPECTED_SKILLS:
        text = (ADAPTER_ROOT / name / "SKILL.md").read_text(encoding="utf-8")
        assert "../../../skills/waterfallhunter/README.md" in text
        assert f"../../../skills/waterfallhunter/{name}/SKILL.md" in text
        assert "contains no independent workflow" in text


def test_malformed_frontmatter_is_rejected() -> None:
    text = '---\nname: broken\ndescription: "Use when broken\n---\n# Broken\n'
    _, errors = _parse_frontmatter(text, Path("broken/SKILL.md"))
    assert any("quoted frontmatter values are not supported" in error for error in errors)


def test_cross_skill_authority_and_handoffs() -> None:
    texts = {name: _skill_text(name) for name in EXPECTED_SKILLS}
    release = texts["release-production-certification"]

    for state in PRODUCTION_STATES:
        assert state in release
    assert "sole authority" in release.lower()

    for name, text in texts.items():
        if name == "release-production-certification":
            continue
        for state in PRODUCTION_STATES:
            for match in re.finditer(re.escape(state), text):
                window = text[max(0, match.start() - 180) : match.end() + 40]
                assert AUTHORIZATION_RE.search(window) is None, (
                    f"{name}: grants production-state authority near {state}: {window!r}"
                )

    assert "scientific-backtest-validation" in texts["strategy-score-lifecycle"]
    assert "api-contract-schema-guardian" in texts["frontend-dashboard-ux"]

    runtime = texts["runtime-reliability-performance"]
    for keyword in ("OOM", "single-flight", "SSE", "backpressure", "soak"):
        assert keyword in runtime


def test_skills_do_not_authorize_live_execution() -> None:
    for name in EXPECTED_SKILLS:
        text = _skill_text(name)
        lowered = text.lower()
        assert "LIVE_TRADING_ENABLED=true" not in text
        assert "Live order placement is outside this skill system" in text
        assert "may place live orders" not in lowered
        assert "place live orders" not in lowered


def test_skill_descriptions_are_trigger_only() -> None:
    sequencing = re.compile(r"\b(then|step|first|after)\b", re.IGNORECASE)
    for name in EXPECTED_SKILLS:
        description = _description(_skill_text(name))
        assert sequencing.search(description) is None, (
            f"{name}: description contains workflow sequencing: {description}"
        )
