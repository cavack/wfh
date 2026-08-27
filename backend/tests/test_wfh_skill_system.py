from pathlib import Path

from scripts.validate_wfh_skills import EXPECTED_SKILLS, validate


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
    root = Path(__file__).resolve().parents[2]
    assert validate(root) == []
