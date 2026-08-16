from waterfallhunter import main


def test_candidate_output_contains_execution_suitability(
    monkeypatch,
):
    symbol = "TEST/USDT:USDT"

    monkeypatch.setattr(
        main.db,
        "get_all_active_candidates",
        lambda: {
            symbol: {
                "status": "WATCH",
                "trigger_data": {},
            }
        },
    )

    monkeypatch.setattr(
        main.scanner,
        "active_candidates",
        {},
    )

    expected = {
        "symbol": symbol,
        "status": "SUITABLE",
        "reason": (
            "execution quality is within "
            "the observational suitable envelope"
        ),
        "evidence_status": "SUFFICIENT",
        "observed_samples": 37,
        "observation_span_hours": 38.0,
        "availability_rate": 1.0,
        "cost_100_p90_pct": 0.08,
        "spread_p90_pct": 0.05,
        "depth_25bps_p50_usdt": 10_000.0,
        "failed_checks": [],
        "observational_only": True,
        "trade_eligible": None,
    }

    monkeypatch.setattr(
        main.execution_suitability_enricher,
        "for_symbol",
        lambda requested_symbol: (
            dict(
                expected
            )
        ),
    )

    result = (
        main.get_formatted_candidates()
    )

    candidate = (
        result[
            "candidates"
        ][
            symbol
        ]
    )

    assert (
        candidate[
            "execution_suitability"
        ]
        == expected
    )

    assert (
        "trigger_data"
        not in candidate
    )


def test_execution_suitability_does_not_change_candidate_score_or_state(
    monkeypatch,
):
    symbol = "TEST/USDT:USDT"

    monkeypatch.setattr(
        main.db,
        "get_all_active_candidates",
        lambda: {
            symbol: {
                "status": "ARMED",
                "score": 88,
                "trigger_data": {},
            }
        },
    )

    monkeypatch.setattr(
        main.scanner,
        "active_candidates",
        {},
    )

    monkeypatch.setattr(
        main.execution_suitability_enricher,
        "for_symbol",
        lambda requested_symbol: {
            "symbol": requested_symbol,
            "status": "POOR",
            "reason": "historical execution poor",
            "evidence_status": "SUFFICIENT",
            "observed_samples": 37,
            "observation_span_hours": 38.0,
            "availability_rate": 1.0,
            "cost_100_p90_pct": 2.0,
            "spread_p90_pct": 1.5,
            "depth_25bps_p50_usdt": 20.0,
            "failed_checks": [
                "cost100_p90",
                "spread_p90",
                "depth25_p50",
            ],
            "observational_only": True,
            "trade_eligible": None,
        },
    )

    result = (
        main.get_formatted_candidates()
    )

    candidate = (
        result[
            "candidates"
        ][
            symbol
        ]
    )

    assert (
        candidate[
            "status"
        ]
        == "ARMED"
    )

    assert (
        candidate[
            "execution_suitability"
        ][
            "status"
        ]
        == "POOR"
    )

    assert (
        candidate[
            "execution_suitability"
        ][
            "trade_eligible"
        ]
        is None
    )
