import logging
import ccxt.async_support as ccxt
from typing import Dict, Any, Optional

logger = logging.getLogger("WaterfallHunter.MultiExchange")

class MultiExchangeGateway:
    def __init__(self):
        # قانون سخت: ترتیب اولویت دقیقاً طبق معماری Production
        self.priority_chain = ['binance', 'mexc', 'bingx', 'kucoin', 'okx']
        self._exchanges: Dict[str, ccxt.Exchange] = {}
        self._markets_loaded: Dict[str, bool] = {ex: False for ex in self.priority_chain}

    async def _get_exchange(self, ex_name: str) -> ccxt.Exchange:
        """مقداردهی اولیه و کش کردن نمونه صرافی به صورت Singleton"""
        if ex_name not in self._exchanges:
            ex_class = getattr(ccxt, ex_name)
            self._exchanges[ex_name] = ex_class({
                'enableRateLimit': True,
                'timeout': 10000,
                'options': {'defaultType': 'swap'}  # تضمین قراردادهای Perpetual
            })
        
        ex = self._exchanges[ex_name]
        
        if not self._markets_loaded[ex_name]:
            try:
                await ex.load_markets()
                self._markets_loaded[ex_name] = True
            except Exception as e:
                logger.debug(f"Failed to load markets for {ex_name}: {e}")
                
        return ex

    def _map_symbol(self, base_symbol: str, exchange_markets: dict) -> Optional[str]:
        """سیستم مپینگ هوشمند: حل مشکل پیشوندهای 1000 و 1000000 در صرافی‌های مختلف"""
        base_coin = base_symbol.split('/')[0].split('-')[0].upper()
        clean_base = base_coin.replace('1000000', '').replace('1000', '')
        
        # ترکیب‌های احتمالی در صرافی‌های مختلف برای فیوچرز
        possible_symbols = [
            f"{base_coin}/USDT:USDT",
            f"{base_coin}/USDT",
            f"1000{clean_base}/USDT:USDT",
            f"1000000{clean_base}/USDT:USDT",
            f"100{clean_base}/USDT:USDT",
            base_symbol
        ]
        
        # جستجوی سریع مستقیم
        for variant in possible_symbols:
            if variant in exchange_markets:
                market = exchange_markets[variant]
                if market.get('linear') and market.get('settle') == 'USDT' and market.get('active'):
                    return variant
                
        # جستجوی عمیق در صورتی که نام‌گذاری نامتعارف باشد
        for k, v in exchange_markets.items():
            if (k.startswith(f"{base_coin}/") or 
                k.startswith(f"1000{clean_base}/") or 
                k.startswith(f"1000000{clean_base}/")):
                if v.get('linear') and v.get('settle') == 'USDT' and v.get('active'):
                    return k
                    
        return None

    async def execute_waterfall(self, method_name: str, symbol: str, *args, **kwargs) -> Dict[str, Any]:
        """
        قانون سخت (Strict Rule): 
        هر داده‌ای که از اولین منبع موفق تأمین شد، دیگر از بقیه صرافی‌ها درخواست نمی‌شود.
        """
        for ex_name in self.priority_chain:
            try:
                ex = await self._get_exchange(ex_name)
                if not self._markets_loaded[ex_name]:
                    continue
                    
                mapped_sym = self._map_symbol(symbol, ex.markets)
                if not mapped_sym:
                    continue
                
                # فراخوانی داینامیک متد CCXT (مثل fetch_ticker یا fetch_ohlcv)
                method = getattr(ex, method_name)
                result = await method(mapped_sym, *args, **kwargs)
                
                if result:
                    logger.debug(f"[SUCCESS] {method_name} for {symbol} sourced from {ex_name.upper()} (Mapped: {mapped_sym})")
                    return {
                        "exchange": ex_name,
                        "mapped_symbol": mapped_sym,
                        "data": result,
                        "exchange_instance": ex
                    }
                    
            except Exception as e:
                # نادیده گرفتن خطا و رفتن به صرافی بعدی در زنجیره آبشار
                logger.debug(f"[WATERFALL SKIP] {ex_name} failed for {symbol} on {method_name}: {e}")
                continue
        
        # در صورت نبود داده معتبر در کل ۵ صرافی، دیکشنری خالی برمی‌گرداند تا تحلیل رد شود
        return {}

    # ---------------------------------------------------------
    # متدهای کمکی برای استفاده مستقیم در ولیدیتور و هوش مصنوعی
    # ---------------------------------------------------------
    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        return await self.execute_waterfall('fetch_ticker', symbol)

    async def fetch_order_book(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        return await self.execute_waterfall('fetch_order_book', symbol, limit=limit)

    async def fetch_ohlcv(self, symbol: str, timeframe: str = '1m', limit: int = 50) -> Dict[str, Any]:
        return await self.execute_waterfall('fetch_ohlcv', symbol, timeframe=timeframe, limit=limit)

    async def close_all(self):
        for ex in self._exchanges.values():
            await ex.close()
        self._exchanges.clear()
        self._markets_loaded.clear()
        logger.info("All Multi-Exchange connections securely closed.")
