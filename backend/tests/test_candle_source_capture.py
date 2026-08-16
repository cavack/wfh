import asyncio
from unittest.mock import patch

from waterfallhunter.core.candle_analyzer import MultiTimeframeAnalyzer


NOW_SECONDS = 2_000_000_000.0


def _rows(gap: int):
    now_ms = int(NOW_SECONDS * 1000)
    return [
        [now_ms - (120 - index) * gap, 10.0, 10.5, 9.5, 9.8, 100.0]
        for index in range(120)
    ]


class PrimaryExchange:
    async def fetch_ohlcv(self, symbol, timeframe, limit):
        return _rows(MultiTimeframeAnalyzer.timeframe_ms[timeframe])


class ConfirmationExchange:
    async def fetch_ohlcv(self, symbol, timeframe, limit):
        assert timeframe == "15m"
        return _rows(MultiTimeframeAnalyzer.timeframe_ms["15m"])


def test_candle_analyzer_returns_exact_validated_closed_source_rows():
    analyzer = MultiTimeframeAnalyzer()
    with patch("waterfallhunter.core.candle_analyzer.time.time", return_value=NOW_SECONDS):
        result = asyncio.run(
            analyzer.analyze_candles(
                PrimaryExchange(),
                "TEST/USDT:USDT",
                ConfirmationExchange(),
                "TEST/USDT:USDT",
            )
        )

    capture = result["source_capture"]
    assert capture["raw_ohlcv_captured"] is True
    assert capture["confirmation_ohlcv_captured"] is True
    assert set(capture["primary_closed_ohlcv"]) == {"5m", "15m", "1h", "4h"}
    assert all(len(rows) == 120 for rows in capture["primary_closed_ohlcv"].values())
    assert len(capture["confirmation_closed_ohlcv_15m"]) == 120
    assert capture["primary_closed_ohlcv"]["5m"][-1][0] == int(NOW_SECONDS * 1000) - 300_000
