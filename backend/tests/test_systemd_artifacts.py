from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_waterfallhunter_systemd_unit_contract() -> None:
    text = (ROOT / "deploy/systemd/waterfallhunter.service").read_text(encoding="utf-8")
    assert "After=docker.service network-online.target" in text
    assert "Requires=docker.service" in text
    assert "WorkingDirectory=/srv/waterfallhunter/app" in text
    assert "RemainAfterExit=yes" in text
    assert "scripts/production_compose.sh up -d --remove-orphans" in text
    assert "scripts/production_compose.sh stop --timeout 30" in text
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


def test_systemd_and_recovery_reuse_optional_host_owned_production_volume_override() -> None:
    wrapper = ROOT / "scripts/production_compose.sh"
    assert wrapper.is_file()
    assert wrapper.stat().st_mode & 0o100
    text = wrapper.read_text(encoding="utf-8")
    verifier = (ROOT / "scripts/verify_production_cutover.py").read_text(encoding="utf-8")
    override = "/srv/waterfallhunter/runtime/production-volumes.override.yml"
    assert override in text
    assert 'if [[ -f "$OVERRIDE" ]]' in text
    assert "--project-name waterfallhunter" in text
    assert "--env-file" in text
    assert "production-volumes.override.yml" in verifier


def test_release_certificate_builder_is_exact_sha_and_signal_only() -> None:
    import importlib.util
    script = ROOT / "scripts/verify_production_cutover.py"
    spec = importlib.util.spec_from_file_location("verify_production_cutover_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    snapshot = {
        "healthy": True,
        "running_revision": "a" * 40,
        "core_revisions": {
            "waterfall-backend": "a" * 40,
            "waterfall-frontend": "a" * 40,
            "waterfall-watchdog": "a" * 40,
        },
        "checkout_revision": "a" * 40,
        "live_trading_enabled": False,
        "backend_endpoints": {"/livez": True, "/readyz": True, "/healthz": True},
    }
    certificate = module.build_release_certificate(snapshot, generated_at=123)
    assert certificate["certificate_type"] == "waterfallhunter_release_v1"
    assert certificate["status"] == "PASS"
    assert certificate["release_sha"] == "a" * 40
    assert certificate["production_healthy"] is True
    assert certificate["live_trading_enabled"] is False
    assert len(certificate["certificate_sha256"]) == 64


def test_release_certificate_builder_rejects_unhealthy_or_revision_mismatch() -> None:
    import importlib.util
    script = ROOT / "scripts/verify_production_cutover.py"
    spec = importlib.util.spec_from_file_location("verify_production_cutover_invalid_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    base = {
        "healthy": True,
        "running_revision": "a" * 40,
        "core_revisions": {
            "waterfall-backend": "a" * 40,
            "waterfall-frontend": "a" * 40,
            "waterfall-watchdog": "a" * 40,
        },
        "checkout_revision": "b" * 40,
        "live_trading_enabled": False,
        "backend_endpoints": {"/livez": True, "/readyz": True, "/healthz": True},
    }
    try:
        module.build_release_certificate(base, generated_at=123)
    except ValueError:
        pass
    else:
        raise AssertionError("revision mismatch must refuse release certification")


def test_release_certificate_builder_rejects_core_container_revision_mismatch() -> None:
    import importlib.util
    script = ROOT / "scripts/verify_production_cutover.py"
    spec = importlib.util.spec_from_file_location("verify_production_cutover_core_revision_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    snapshot = {
        "healthy": True,
        "running_revision": "a" * 40,
        "core_revisions": {
            "waterfall-backend": "a" * 40,
            "waterfall-frontend": "b" * 40,
            "waterfall-watchdog": "a" * 40,
        },
        "checkout_revision": "a" * 40,
        "live_trading_enabled": False,
        "backend_endpoints": {"/livez": True, "/readyz": True, "/healthz": True},
    }
    try:
        module.build_release_certificate(snapshot, generated_at=123)
    except ValueError:
        pass
    else:
        raise AssertionError("all core runtime OCI revisions must match the certified checkout")
