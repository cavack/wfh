import re
from pathlib import Path

from scripts.validate_wfh_skills import EXPECTED_SKILLS, validate

ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "waterfallhunter"


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


def test_cross_skill_authority_and_handoffs() -> None:
    texts = {name: _skill_text(name) for name in EXPECTED_SKILLS}
    release = texts["release-production-certification"]

    for state in ("DEPLOY_READY", "DEPLOYED_UNVERIFIED", "PRODUCTION_VERIFIED"):
        assert state in release
    assert "sole authority" in release.lower()

    for name, text in texts.items():
        if name == "release-production-certification":
            continue
        assert "this skill is the sole authority" not in text.lower()
        assert "this skill may declare" not in text.lower()

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
        assert "authorize order placement" not in lowered
        assert "may place live orders" not in lowered
        assert "place live orders" not in lowered


def test_skill_descriptions_are_trigger_only() -> None:
    sequencing = re.compile(r"\b(then|step|first|after)\b", re.IGNORECASE)
    for name in EXPECTED_SKILLS:
        description = _description(_skill_text(name))
        assert sequencing.search(description) is None, (
            f"{name}: description contains workflow sequencing: {description}"
        )
