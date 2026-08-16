from waterfallhunter.core.risk_manager import get_leverage


def test_recommended_leverage_is_conservative_and_never_exceeds_channel_limit():
    assert get_leverage("BTC/USDT:USDT") == 2
    assert get_leverage("ETH/USDT:USDT") == 2
    assert get_leverage("PEPE/USDT:USDT") == 3
    assert max(get_leverage(symbol) for symbol in ("BTC/USDT:USDT", "ETH/USDT:USDT", "PEPE/USDT:USDT")) <= 4
