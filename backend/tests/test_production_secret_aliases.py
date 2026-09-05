from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-production.yml"


def test_production_workflow_accepts_existing_legacy_ssh_secret_names() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    expected_aliases = {
        "WFH_PROD_HOST": "WFH_DEPLOY_HOST",
        "WFH_PROD_PORT": "WFH_DEPLOY_PORT",
        "WFH_PROD_USER": "WFH_DEPLOY_USER",
        "WFH_PROD_SSH_KEY": "WFH_DEPLOY_SSH_KEY",
        "WFH_PROD_KNOWN_HOSTS": "WFH_DEPLOY_KNOWN_HOSTS",
    }
    for canonical, legacy in expected_aliases.items():
        assert f"secrets.{canonical}" in text
        assert f"secrets.{legacy}" in text

    assert "WFH_DEPLOY_PATH" not in text
    assert "WFH_DEPLOY_ROOT='/srv/waterfallhunter/app'" in text
