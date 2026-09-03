from scripts.calibrate_entry_readiness_observable import _apply_cooldown, _eligible


def _trade(timestamp=1_000, symbol="X", score=55.0, maximum=73.0, timing=10.0, direction=True):
    return {
        "timestamp": timestamp,
        "symbol": symbol,
        "historical_entry_readiness_observable": {
            "schema_version": "entry_readiness_historical_observable_v1",
            "observed_score": score,
            "observed_maximum": maximum,
            "direction_ok": direction,
            "components": {"timing": {"points": timing, "available_maximum": 15.0}},
        },
    }


def test_eligibility_requires_complete_observable_subset_direction_and_current_timing_gate():
    assert _eligible(_trade(), 55.0) is True
    assert _eligible(_trade(maximum=65.0), 55.0) is False
    assert _eligible(_trade(direction=False), 55.0) is False
    assert _eligible(_trade(timing=5.0), 55.0) is False
    assert _eligible(_trade(score=54.9), 55.0) is False


def test_cooldown_is_symbol_local_and_applied_after_threshold_selection():
    trades = [
        _trade(timestamp=0, symbol="A"),
        _trade(timestamp=1_000, symbol="A"),
        _trade(timestamp=1_000, symbol="B"),
        _trade(timestamp=3_600_000, symbol="A"),
    ]
    selected = _apply_cooldown(trades, 55.0, 1.0)
    assert [(row["symbol"], row["timestamp"]) for row in selected] == [
        ("A", 0), ("B", 1_000), ("A", 3_600_000)
    ]
