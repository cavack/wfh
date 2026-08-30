from waterfallhunter.core.derivatives import DerivativesAnalyzer


def test_binance_packet_uses_market_id_and_rejects_a_missing_taker_ratio():
    result = DerivativesAnalyzer().evaluate_packet(
        exchange="binance",
        mapped_symbol="1000PEPE/USDT:USDT",
        market_id="1000PEPEUSDT",
        funding_history=[0.00005, 0.0001, 0.0002],
        current_funding=0.0002,
        current_oi=1_000_000,
        oi_one_hour_ago=1_020_000,
        taker_buy_sell_ratio=None,
        top_trader_long_short_ratio=1.3,
        retrieved_at=1_700_000_000.0,
    )

    assert result["available"] is False
    assert result["reason"] == "missing valid taker buy/sell ratio"
    assert result["market_id"] == "1000PEPEUSDT"


def test_complete_packet_contains_no_default_derivative_values():
    result = DerivativesAnalyzer().evaluate_packet(
        exchange="binance",
        mapped_symbol="1000PEPE/USDT:USDT",
        market_id="1000PEPEUSDT",
        funding_history=[0.00005, 0.0001, 0.0002],
        current_funding=0.0002,
        current_oi=1_000_000,
        oi_one_hour_ago=1_020_000,
        taker_buy_sell_ratio=0.8,
        top_trader_long_short_ratio=1.3,
        retrieved_at=1_700_000_000.0,
    )

    assert result["available"] is True
    assert result["funding_percentile"] == 1.0
    assert result["oi_change_1h_pct"] == -1.9608


def test_taker_ratio_change_is_emitted_only_when_real_history_is_supplied():
    result = DerivativesAnalyzer().evaluate_packet(
        exchange="binance",
        mapped_symbol="TEST/USDT:USDT",
        market_id="TESTUSDT",
        funding_history=[0.00005, 0.0002],
        current_funding=0.0002,
        current_oi=900_000,
        oi_one_hour_ago=1_000_000,
        taker_buy_sell_ratio=0.8,
        taker_ratio_change_1h=-0.45,
        top_trader_long_short_ratio=1.3,
        retrieved_at=1_700_000_000.0,
    )

    assert result["available"] is True
    assert result["taker_ratio_change_1h"] == -0.45


def test_binance_packet_rejects_future_timestamped_evidence_domains():
    retrieved_at = 1_700_000_000.0
    market_id = "TESTUSDT"

    def timestamp(seconds_from_retrieval: int) -> int:
        return int((retrieved_at + seconds_from_retrieval) * 1000)

    result = DerivativesAnalyzer().evaluate_binance_rows(
        mapped_symbol="TEST/USDT:USDT",
        market_id=market_id,
        funding_rows=[
            {"symbol": market_id, "fundingTime": timestamp(-16 * 3600), "fundingRate": "0.0001"},
            {"symbol": market_id, "fundingTime": timestamp(-8 * 3600), "fundingRate": "0.0002"},
            {"symbol": market_id, "fundingTime": timestamp(1), "fundingRate": "0.0003"},
        ],
        taker_rows=[
            {"symbol": market_id, "timestamp": timestamp(-3600), "buySellRatio": "1.1"},
            {"symbol": market_id, "timestamp": timestamp(1), "buySellRatio": "0.8"},
        ],
        top_trader_rows=[
            {"symbol": market_id, "timestamp": timestamp(1), "longShortRatio": "1.4"},
        ],
        open_interest_rows=[
            {"symbol": market_id, "timestamp": timestamp(-3600), "sumOpenInterestValue": "1000", "sumOpenInterest": "10"},
            {"symbol": market_id, "timestamp": timestamp(1), "sumOpenInterestValue": "1100", "sumOpenInterest": "11"},
        ],
        retrieved_at=retrieved_at,
    )

    assert result["available"] is False
