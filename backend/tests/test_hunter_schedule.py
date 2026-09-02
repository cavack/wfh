from waterfallhunter.core.hunter_schedule import (
    DEFAULT_EVALUATION_CONCURRENCY,
    ordered_hunter_candidates,
    remaining_cycle_delay,
)


def test_hunter_cycle_delay_targets_start_to_start_period() -> None:
    assert remaining_cycle_delay(100.0, 150.0, 60.0) == 10.0
    assert remaining_cycle_delay(100.0, 175.0, 60.0) == 0.0


def test_hunter_concurrency_has_capacity_for_180_second_freshness_budget() -> None:
    assert DEFAULT_EVALUATION_CONCURRENCY >= 10


def test_hunter_orders_near_trigger_and_oldest_analysis_first() -> None:
    candidates = {
        "WATCH_NEW": {"status": "WATCH"},
        "FUEL_OLD": {"status": "FUEL-RICH"},
        "PRE_NEW": {"status": "PRE-TRIGGER"},
        "PRE_OLD": {"status": "PRE-TRIGGER"},
        "ARMED": {"status": "ARMED"},
        "TRIGGERED": {"status": "TRIGGERED"},
    }
    live = {
        "WATCH_NEW": {"analysis_observed_at": 190.0},
        "FUEL_OLD": {"analysis_observed_at": 50.0},
        "PRE_NEW": {"analysis_observed_at": 180.0},
        "PRE_OLD": {"analysis_observed_at": 40.0},
        "ARMED": {"analysis_observed_at": 170.0},
        "TRIGGERED": {"analysis_observed_at": 160.0},
    }

    ordered = ordered_hunter_candidates(candidates, live)

    assert [symbol for symbol, _ in ordered] == [
        "TRIGGERED",
        "ARMED",
        "PRE_OLD",
        "PRE_NEW",
        "FUEL_OLD",
        "WATCH_NEW",
    ]
