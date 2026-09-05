from pathlib import Path


def test_websocket_orphan_subscription_alert_accounts_for_shared_fanout() -> None:
    alerts = (
        Path(__file__).resolve().parents[2] / "deploy" / "prometheus" / "alerts.yml"
    ).read_text(encoding="utf-8")

    assert (
        "waterfall_websocket_ccxt_subscriptions > "
        "waterfall_websocket_active_tasks + "
        "3 * waterfall_websocket_shared_evidence_subscribers + 8"
    ) in alerts
