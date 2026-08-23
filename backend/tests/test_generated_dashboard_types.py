from pathlib import Path

from scripts.generate_dashboard_types import render_types


PROJECT_ROOT = Path(__file__).parents[2]
GENERATED_TYPES = PROJECT_ROOT / "frontend" / "generated" / "dashboard-contract.ts"


def test_dashboard_types_are_current_with_the_pydantic_source_of_truth() -> None:
    assert GENERATED_TYPES.read_text(encoding="utf-8") == render_types()
