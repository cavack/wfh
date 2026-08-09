import logging
import asyncio
import time
import ccxt.async_support as ccxt
from typing import Dict, Any, List

logger = logging.getLogger("WaterfallHunter.CandleAnalyzer")

class MultiTimeframeAnalyzer:
    def __init__(self):
        # بررسی دقیق روی ۴ تایم‌فریم درخواستی
        self.timeframes = ['5m', '15m', '1h', '4h']
        self.candle_limit = 10 

    def _validate_ohlcv(self, candles: List[List[float]], timeframe: str) -> bool:
        """ممیزی قطعی (Deterministic Validation): رد کندل‌های مخدوش، تکراری یا باز"""
        if not candles or len(candles) < 3:
            return False

        seen_timestamps = set()
        current_time_ms = int(time.time() * 1000)
        
        # محاسبه فاصله زمانی استاندارد بر اساس تایم‌فریم
        tf_ms_map = {'5m': 300000, '15m': 900000, '1h': 3600000, '4h': 14400000}
        expected_gap = tf_ms_map.get(timeframe, 300000)

        for i, c in enumerate(candles):
            ts, o, h, l, close_p, v = c
            
            # 1. رد تایم‌استمپ تکراری
            if ts in seen_timestamps:
                logger.debug(f"Candle Validation Failed: Duplicate timestamp {ts} in {timeframe}")
                return False
            seen_timestamps.add(ts)

            # 2. رد دیتای غیرممکن (OHLC نامعتبر)
            if h < l or h < o or h < close_p or l > o or l > close_p:
                logger.debug(f"Candle Validation Failed: Invalid OHLC math at {ts} in {timeframe}")
                return False

            # 3. رد گپ (Gap) در تایم‌استمپ‌ها (به جز کندل اول)
            if i > 0:
                prev_ts = candles[i-1][0]
                if ts - prev_ts != expected_gap:
                    logger.debug(f"Candle Validation Failed: Time gap detected between {prev_ts} and {ts} in {timeframe}")
                    return False

        # 4. رد کندل باز (آخرین کندل باید کاملاً بسته شده باشد)
        last_candle_ts = candles[-1][0]
        if current_time_ms < (last_candle_ts + expected_gap):
            # حذف کندل باز از محاسبات
            candles.pop()
            
        return True

    async def analyze_candles(self, exchange: ccxt.Exchange, symbol: str) -> Dict[str, Any]:
        """اجرای بک‌تست Walk-forward لایو روی کندل‌های بسته شده"""
        results = {
            "is_breakdown_confirmed": False,
            "breakdown_score": 0,
            "details": {}
        }
        
        try:
            tasks = [exchange.fetch_ohlcv(symbol, timeframe=tf, limit=self.candle_limit) for tf in self.timeframes]
            ohlcv_data = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, tf in enumerate(self.timeframes):
                candles = ohlcv_data[i]
                
                if isinstance(candles, Exception):
                    logger.error(f"Failed to fetch {tf} for {symbol}: {candles}")
                    results["details"][tf] = "Fetch Error"
                    continue
                    
                if not self._validate_ohlcv(candles, tf):
                    results["details"][tf] = "Validation Failed (Gaps, Open, or Bad OHLC)"
                    continue

                # منطق ورود (Entry Conditions): دو کندل بسته قرمز، سقف پایین‌تر (Lower High) و شتاب حجم
                c1, c2 = candles[-1], candles[-2] # دو کندل آخر بسته شده
                
                c1_open, c1_high, c1_close, c1_vol = c1[1], c1[2], c1[4], c1[5]
                c2_open, c2_high, c2_close, c2_vol = c2[1], c2[2], c2[4], c2[5]

                is_red_c1 = c1_close < c1_open
                is_red_c2 = c2_close < c2_open
                is_lower_high = c1_high <= c2_high
                
                avg_vol = sum(c[5] for c in candles[:-2]) / max(1, len(candles) - 2)
                volume_acceleration = c1_vol > avg_vol

                tf_bearish = is_red_c1 and is_red_c2 and is_lower_high and volume_acceleration
                
                if tf_bearish:
                    results["breakdown_score"] += 1

                results["details"][tf] = {
                    "valid": True,
                    "two_red_candles": is_red_c1 and is_red_c2,
                    "lower_high": is_lower_high,
                    "volume_accelerated": volume_acceleration,
                    "is_bearish": tf_bearish
                }

            # تایید قطعی: حداقل باید در 2 تایم‌فریم مختلف این شکست تایید شده باشد
            if results["breakdown_score"] >= 2:
                results["is_breakdown_confirmed"] = True

        except Exception as e:
            logger.error(f"Fatal error in CandleAnalyzer for {symbol}: {e}")
            results["error"] = str(e)

        return results
