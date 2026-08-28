from __future__ import annotations

import importlib.util
from pathlib import Path

from waterfallhunter import main


ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy_production.sh"


def _load_cutover_module():
    script = ROOT / "scripts" / "verify_production_cutover.py"
    spec = importlib.util.spec_from_file_location("verify_followup_regressions", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _main_deploy_sequence(text: str) -> str:
    return text.split('[[ "$WFH_DEPLOY_SHA"', maxsplit=1)[1]


def test_deterministic_entry_gate_runs_for_watch_and_fuel_rich_candidates(monkeypatch) -> None:
    calls = []

    def evaluate(symbol, orderbook, ticker):
        calls.append((symbol, orderbook, ticker))
        return True, {
            "deterministic_veto": True,
            "ai_observational_only": True,
            "ai_decision_critical": False,
        }

    monkeypatch.setattr(main.ai_veto, "evaluate_deterministic", evaluate)
    for state in ("WATCH", "FUEL-RICH"):
        metrics = {
            "orderbook": {"bids": [[1.0, 4.0]], "asks": [[1.1, 1.0]]},
            "ticker": {"last": 1.0},
        }
        returned_state, vetoed = main._apply_deterministic_entry_gate(
            "TESTUSDT", state, metrics
        )
        assert returned_state == state
        assert vetoed is True
        assert metrics["ai_advisory"]["deterministic_veto"] is True

    assert len(calls) == 2


def test_notification_delivery_ready_requires_top_level_healthy_state() -> None:
    module = _load_cutover_module()
    snapshot = {
        "healthy": False,
        "transport": {
            "configured": True,
            "worker_running": True,
            "probe": {
                "reachable": True,
                "bot_reachable": True,
                "chat_reachable": True,
            },
        },
    }
    assert module._notification_delivery_ready(snapshot) is False


def test_decision_terminal_renders_when_active_candidate_set_is_empty() -> None:
    page = (ROOT / "frontend/app/page.tsx").read_text(encoding="utf-8")
    assert "data !== null && rows.length > 0" not in page
    terminal_call = (
        '<DecisionTerminal terminal={data.decision_terminal} '
        'candidates={data.candidates as Record<string, Candidate>} />'
    )
    assert terminal_call in page
    prefix = page.split(terminal_call, maxsplit=1)[0][-180:]
    assert "data !== null" in prefix


def test_systemd_install_is_late_and_rollback_restores_host_integration() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "snapshot_host_integration_state()" in text
    assert "restore_host_integration_state()" in text
    main_sequence = _main_deploy_sequence(text)
    health_index = main_sequence.index("verify_running_signal_only")
    snapshot_index = main_sequence.index("snapshot_host_integration_state")
    install_index = main_sequence.index("install_systemd_units")
    assert health_index < snapshot_index < install_index

    cleanup = text.split("terminate_with_cleanup() {", maxsplit=1)[1].split(
        "on_error() {", maxsplit=1
    )[0]
    assert "restore_host_integration_state" in cleanup


def test_deploy_installs_validates_and_restores_canonical_nginx_edge() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "install_nginx_site()" in text
    assert "verify_public_edge()" in text

    helper = text.split("install_nginx_site() {", maxsplit=1)[1].split(
        "}\n", maxsplit=1
    )[0]
    assert "deploy/nginx/waterfallhunter.conf" in helper
    assert "/etc/nginx/sites-available/waterfallhunter.conf" in helper
    assert "/etc/nginx/sites-enabled/waterfallhunter.conf" in helper
    assert "nginx -t" in helper
    assert "systemctl reload nginx" in helper

    edge = text.split("verify_public_edge() {", maxsplit=1)[1].split(
        "}\n", maxsplit=1
    )[0]
    assert "waterfall.booksreadlive.online" in edge
    assert "curl" in edge

    main_sequence = _main_deploy_sequence(text)
    health_index = main_sequence.index("verify_running_signal_only")
    nginx_index = main_sequence.index("install_nginx_site")
    edge_index = main_sequence.index("verify_public_edge")
    success_index = main_sequence.index(
        'cat > "${STATE_DIR}/last-successful-deploy.txt"'
    )
    assert health_index < nginx_index < edge_index < success_index

    cleanup = text.split("terminate_with_cleanup() {", maxsplit=1)[1].split(
        "on_error() {", maxsplit=1
    )[0]
    assert "restore_host_integration_state" in cleanup
