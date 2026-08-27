from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_waterfallhunter_systemd_unit_contract() -> None:
    text = (ROOT / "deploy/systemd/waterfallhunter.service").read_text(encoding="utf-8")
    assert "After=docker.service network-online.target" in text
    assert "Requires=docker.service" in text
    assert "WorkingDirectory=/srv/waterfallhunter/app" in text
    assert "RemainAfterExit=yes" in text
    assert "--project-name waterfallhunter" in text
    assert "--env-file /etc/waterfallhunter/waterfallhunter.env" in text
    assert "up -d --remove-orphans" in text
    assert "down -v" not in text


def test_healthcheck_timer_is_bounded_and_persistent() -> None:
    service = (ROOT / "deploy/systemd/waterfallhunter-healthcheck.service").read_text(encoding="utf-8")
    timer = (ROOT / "deploy/systemd/waterfallhunter-healthcheck.timer").read_text(encoding="utf-8")
    assert "verify_production_cutover.py --health-only --recover" in service
    assert "OnUnitActiveSec=60s" in timer
    assert "Persistent=true" in timer
    assert "Restart=always" not in service


def test_nginx_template_exposes_only_frontend_loopback() -> None:
    text = (ROOT / "deploy/nginx/waterfallhunter.conf").read_text(encoding="utf-8")
    assert "proxy_pass http://127.0.0.1:3000;" in text
    assert "127.0.0.1:8000" not in text
    assert "127.0.0.1:9090" not in text
    assert "127.0.0.1:3001" not in text


def test_compose_accepts_host_owned_environment_file() -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "${WFH_ENV_FILE:-.env}" in text


def test_health_recovery_has_finite_budget_and_cooldown() -> None:
    text = (ROOT / "scripts/verify_production_cutover.py").read_text(encoding="utf-8")
    assert "FAILURES_BEFORE_RECOVERY = 3" in text
    assert "RECOVERY_COOLDOWN_SECONDS = 600" in text
    assert "MAX_RECOVERIES_PER_HOUR = 3" in text
