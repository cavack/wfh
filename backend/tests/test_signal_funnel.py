from waterfallhunter.core.signal_funnel import SignalFunnel


def test_funnel_reports_snapshot_and_persisted_stage_chains_separately():
    report = SignalFunnel.build(
        {
            "CHAIN/USDT:USDT": {
                "status": "WATCH",
                "metrics": {
                    "strategy_stages": {
                        "hype": False,
                        "damage": False,
                        "setup": False,
                        "trigger": True,
                        "passed": False,
                    },
                    "stage_lifecycle": {
                        "available": True,
                        "confirmed": {
                            "hype": True,
                            "damage": True,
                            "setup": True,
                            "trigger": True,
                            "passed": True,
                        },
                    },
                },
            }
        }
    )

    assert report["version"] == "signal_funnel_observational_v2"
    assert report["stages"]["passed"]["passed"] == 0
    assert report["stage_lifecycle"]["stages"]["passed"]["passed"] == 1
    assert report["stage_lifecycle"]["hard_gating_allowed"] is False
