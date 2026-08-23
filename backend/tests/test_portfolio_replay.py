from __future__ import annotations

import pytest

from waterfallhunter.core.execution_planning import (
    ExecutionCostPolicy,
    MaintenanceMarginTier,
    PortfolioCapacity,
    PriceBand,
    RiskPolicy,
    SafeLeverageBounds,
    ValidatedMarketConstraints,
    build_short_paper_execution_plan,
)
from waterfallhunter.core.portfolio_replay import (
    PortfolioEvent,
    build_signal_level_research_report,
    replay_paper_portfolio,
)


MANIFEST_HASH = "d" * 64


def _plan(signal_id: str) -> dict:
    constraints = ValidatedMarketConstraints.create(
        canonical_symbol="TEST-USDT-PERP",
        venue_symbol="TEST/USDT:USDT",
        tick_size=0.1,
        quantity_step=0.001,
        contract_size=1.0,
        min_quantity=0.001,
        min_notional=5.0,
        maximum_leverage=20.0,
        price_band=PriceBand(minimum=1.0, maximum=1_000.0),
        maintenance_margin_tiers=(
            MaintenanceMarginTier(
                notional_floor=0.0,
                maintenance_margin_rate=0.005,
            ),
        ),
        liquidation_fee_rate=0.002,
        funding_semantics="timestamped_8h",
        constraints_observed_at=100,
        expires_at=200,
    )
    costs = ExecutionCostPolicy.create(
        taker_fee_rate=0.0006,
        maker_fee_rate=0.0002,
        entry_slippage_p95_rate=0.0005,
        exit_slippage_p95_rate=0.0007,
        expected_funding_rate=0.0001,
        liquidation_buffer_rate=0.02,
    )
    return build_short_paper_execution_plan(
        signal_id=signal_id,
        cluster_id="MEME_HIGH_BETA",
        evaluation_time=150,
        constraints=constraints,
        expected_constraints_hash=constraints.constraints_hash,
        cost_policy=costs,
        risk_policy=RiskPolicy.v1(),
        portfolio=PortfolioCapacity(cash_equity=200.0, unrealized_pnl=0.0),
        leverage_bounds=SafeLeverageBounds.create(
            exchange_max=20.0,
            maintenance_liquidation=10.0,
            volatility=6.0,
            liquidity_slippage=5.0,
            evidence_uncertainty=4.0,
            portfolio_open_risk=3.8,
        ),
        requested_risk_rate=0.0075,
        raw_entry=100.09,
        raw_tp1=98.01,
        raw_tp2=96.01,
        raw_stop=101.51,
    )


def _open(event_id: str, position_id: str, signal_id: str, occurred_at: int = 100) -> PortfolioEvent:
    return PortfolioEvent(
        event_id=event_id,
        occurred_at=occurred_at,
        event_type="OPEN",
        position_id=position_id,
        signal_id=signal_id,
        cluster_id="MEME_HIGH_BETA",
        execution_plan=_plan(signal_id),
    )


def test_replay_has_total_deterministic_order_and_does_not_reuse_unrealized_gain() -> None:
    events = [
        PortfolioEvent(
            event_id="close",
            occurred_at=120,
            event_type="CLOSE",
            position_id="position-1",
            price=96.0,
            exit_cost=0.1,
        ),
        _open("open-2", "position-2", "signal-2", occurred_at=110),
        PortfolioEvent(
            event_id="mark",
            occurred_at=105,
            event_type="MARK",
            position_id="position-1",
            price=96.0,
        ),
        PortfolioEvent(
            event_id="funding",
            occurred_at=120,
            event_type="FUNDING",
            position_id="position-1",
            amount=-0.2,
        ),
        _open("open-1", "position-1", "signal-1"),
    ]

    first = replay_paper_portfolio(
        events,
        initial_equity=200.0,
        risk_policy=RiskPolicy.v1(),
        dataset_manifest_hash=MANIFEST_HASH,
    )
    second = replay_paper_portfolio(
        list(reversed(events)),
        initial_equity=200.0,
        risk_policy=RiskPolicy.v1(),
        dataset_manifest_hash=MANIFEST_HASH,
    )

    assert first == second
    assert first["replay_sha256"] == second["replay_sha256"]
    assert first["event_order"] == ["open-1", "mark", "open-2", "funding", "close"]
    assert first["skipped_signals"] == [
        {
            "signal_id": "signal-2",
            "position_id": "position-2",
            "reason": "PORTFOLIO_CLUSTER_RISK_CAP_EXCEEDED",
        }
    ]
    assert first["final_cash_equity"] > 200.0
    assert first["report_type"] == "PORTFOLIO_REALIZABLE"


def test_mark_at_liquidation_closes_only_the_isolated_position() -> None:
    plan = _plan("signal-liquidated")
    events = [
        PortfolioEvent(
            event_id="open",
            occurred_at=100,
            event_type="OPEN",
            position_id="position-liquidated",
            signal_id="signal-liquidated",
            cluster_id="MEME_HIGH_BETA",
            execution_plan=plan,
        ),
        PortfolioEvent(
            event_id="liquidating-mark",
            occurred_at=110,
            event_type="MARK",
            position_id="position-liquidated",
            price=plan["liquidation_price"] + 1.0,
            exit_cost=0.2,
        ),
    ]

    replay = replay_paper_portfolio(
        events,
        initial_equity=200.0,
        risk_policy=RiskPolicy.v1(),
        dataset_manifest_hash=MANIFEST_HASH,
    )

    assert replay["open_positions"] == []
    assert replay["closed_positions"][0]["exit_reason"] == "ISOLATED_LIQUIDATION"
    assert replay["final_cash_equity"] < 200.0


def test_signal_level_and_portfolio_realizable_reports_remain_separate() -> None:
    signal_report = build_signal_level_research_report(
        [
            {
                "signal_id": "signal-1",
                "signal_triggered_at": 100,
                "outcome": "TP2_FIRST",
            }
        ],
        dataset_manifest_hash=MANIFEST_HASH,
    )
    portfolio_report = replay_paper_portfolio(
        [],
        initial_equity=200.0,
        risk_policy=RiskPolicy.v1(),
        dataset_manifest_hash=MANIFEST_HASH,
    )

    assert signal_report["report_type"] == "SIGNAL_LEVEL_RESEARCH"
    assert signal_report["portfolio_realizability_applied"] is False
    assert portfolio_report["report_type"] == "PORTFOLIO_REALIZABLE"
    assert "rows" not in portfolio_report
    assert "event_log" not in signal_report


def test_partial_fill_scales_isolated_exposure_and_rejection_is_attributed() -> None:
    partial = PortfolioEvent(
        event_id="partial",
        occurred_at=100,
        event_type="OPEN",
        position_id="partial-position",
        signal_id="partial-signal",
        cluster_id="MEME_HIGH_BETA",
        execution_plan=_plan("partial-signal"),
        fill_fraction=0.25,
    )
    rejected = PortfolioEvent(
        event_id="rejected",
        occurred_at=101,
        event_type="OPEN",
        position_id="rejected-position",
        signal_id="rejected-signal",
        cluster_id="OTHER",
        execution_plan=_plan("rejected-signal"),
        fill_fraction=0,
        rejection_reason="VENUE_MIN_NOTIONAL",
    )
    replay = replay_paper_portfolio(
        [rejected, partial],
        initial_equity=200.0,
        risk_policy=RiskPolicy.v1(),
        dataset_manifest_hash=MANIFEST_HASH,
    )

    assert replay["event_order"] == ["partial", "rejected"]
    assert replay["event_log"][0]["status"] == "PARTIALLY_FILLED"
    assert replay["partial_fills"][0]["fill_fraction"] == 0.25
    assert replay["open_positions"][0]["risk_at_stop"] == pytest.approx(
        _plan("partial-signal")["risk_at_stop"] * 0.25,
    )
    assert replay["rejected_orders"] == [
        {
            "signal_id": "rejected-signal",
            "position_id": "rejected-position",
            "reason": "VENUE_MIN_NOTIONAL",
        }
    ]
