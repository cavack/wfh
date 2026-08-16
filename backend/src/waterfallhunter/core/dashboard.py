from typing import Any


def compact_metrics(
    metrics: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(metrics, dict):
        return None

    top_level = (
        "error",
        "analysis_reason",
        "source_exchange",
        "mapped_symbol",
        "exchange",
        "score_version",
        "score",
        "total_score",
        "score_components",
        "valid_candle_timeframes",
        "quality_gates",
        "strategy_stages",
        "snapshot_stage_chain",
        "stage_lifecycle",
        "ai_advisory",
        "applied_leverage",
        "dex_context",
        "onchain_context",
        "data_sources",
        "source_failures",
        "watch_score",
        "selected_quote_volume_usdt",
        "trade_eligible",
        "observation_score",
        "observation_status",
        "observation_score_version",
        "observation_components",
        "candle_features",
        "breakdown_confirmation",
        "benchmark_context",
        "relative_weakness_features",
    )

    result = {
        key: metrics[key]
        for key in top_level
        if key in metrics
    }

    derivatives = metrics.get(
        "derivatives"
    )

    if isinstance(
        derivatives,
        dict,
    ):
        derivative_fields = (
            "available",
            "reason",
            "source_exchange",
            "mapped_symbol",
            "retrieved_at",
            "funding_rate",
            "funding_percentile",
            "oi_change_1h_pct",
            "taker_buy_sell_ratio",
            "taker_ratio_change_1h",
            "top_trader_long_short_ratio",
            "market_id",
            "freshness_reason",
            "fallback_attempts",
        )

        result["derivatives"] = {
            key: derivatives[key]
            for key in derivative_fields
            if key in derivatives
        }
        if isinstance(result["derivatives"].get("fallback_attempts"), list):
            fallback_fields = (
                "exchange", "mapped_symbol", "market_id", "retrieved_at", "reason",
            )
            result["derivatives"]["fallback_attempts"] = [
                {
                    key: attempt[key]
                    for key in fallback_fields
                    if key in attempt
                }
                for attempt in result["derivatives"]["fallback_attempts"]
                if isinstance(attempt, dict)
            ]

    microstructure = metrics.get(
        "microstructure"
    )

    if isinstance(
        microstructure,
        dict,
    ):
        microstructure_fields = (
            "approved",
            "reason",
            "observed_at",
            "spread_pct",
            "best_bid",
            "best_ask",
            "sell_vwap",
            "buy_vwap",
            "slippage_pct",
            "entry_slippage_pct",
            "exit_slippage_pct",
            "round_trip_slippage_pct",
            "bid_depth_usdt",
            "ask_depth_usdt",
            "sell_flow_usdt",
            "buy_flow_usdt",
            "churn",
            "sell_flow_ratio",
            "spoofing_detected",
            "executable",
            "executable_notional",
            "minimum_notional",
            "contracts",
            "footprint",
        )

        result["microstructure"] = {
            key: microstructure[key]
            for key in microstructure_fields
            if key in microstructure
        }

    position_setup = metrics.get(
        "position_setup"
    )

    if isinstance(
        position_setup,
        dict,
    ):
        position_fields = (
            "entry_price",
            "stop_loss",
            "take_profit_1",
            "take_profit_2",
            "position_size_contracts",
            "position_value_usdt",
            "is_api_ready",
            "risk_pct",
            "reward_to_risk",
            "tp_24h_probability",
            "monitoring",
            "slippage",
            "status",
        )

        result["position_setup"] = {
            key: position_setup[key]
            for key in position_fields
            if key in position_setup
        }

    return result
