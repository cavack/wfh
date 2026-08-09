import asyncio
import logging
import ccxt.async_support as ccxt
from typing import List, Dict, Any, Set
import time

logger = logging.getLogger("WaterfallHunter.LBankScanner")

class LBankCatalogScanner:
    def __init__(self, db_adapter, max_price: float = 1.0, min_volume_usdt: float = 500000.0):
        self.max_price = max_price
        # فیلتر سخت‌گیرانه برای اطمینان از نقدینگی اسکلپ (نیم میلیون دلار)
        self.min_volume_usdt = min_volume_usdt 
        self.active_candidates: Dict[str, Dict[str, Any]] = {}
        self.db = db_adapter
        self._is_running = False

    async def fetch_lbank_futures_symbols(self) -> List[Dict[str, Any]]:
        """اسکنر لایو: استخراج قراردادهای دائمی USDT با فیلتر قیمت، حجم و اولویت‌بندی میم‌کوین‌ها"""
        valid_symbols = []
        exchange = None
        try:
            exchange = ccxt.lbank({
                'enableRateLimit': True,
                'timeout': 15000,
                'options': {'defaultType': 'swap'}
            })
            
            await exchange.load_markets()
            tickers = await exchange.fetch_tickers()

            for symbol, market in exchange.markets.items():
                # قانون سخت: فقط قراردادهای خطی، بر پایه USDT و کاملاً فعال
                if not market.get('linear') or market.get('settle') != 'USDT' or not market.get('active'):
                    continue

                ticker = tickers.get(symbol, {})
                last_price = float(ticker.get('last', 0.0) or 0.0)
                quote_volume = float(ticker.get('quoteVolume', 0.0) or 0.0)

                if 0.0 < last_price <= self.max_price and quote_volume >= self.min_volume_usdt:
                    meme_keywords = ["PEPE", "SHIB", "DOGE", "FLOKI", "BONK", "WIF", "BOME", "NEIRO", "PNUT", "GOAT", "MOODENG", "CHILLGUY", "MEME", "CAT", "TURBO", "SLERF"]
                    is_meme = any(meme in symbol.upper() for meme in meme_keywords)
                    
                    valid_symbols.append({
                        "symbol": symbol,
                        "last_price": last_price,
                        "quote_volume": quote_volume,
                        "is_meme": is_meme,
                        "contract_size": float(market.get('contractSize', 1.0)),
                    })

            # مرتب‌سازی قطعی (Deterministic): میم‌کوین‌ها در صدر، سپس بر اساس بالاترین نقدینگی
            valid_symbols.sort(key=lambda x: (not x["is_meme"], -x["quote_volume"]))
            
            logger.info(f"LBank Scanner: Identified {len(valid_symbols)} highly liquid targets under ${self.max_price}.")
            return valid_symbols

        except Exception as e:
            logger.error(f"LBank catalog fetch failed: {e}")
            return []
        finally:
            if exchange:
                await exchange.close()

    async def update_catalog(self):
        logger.info("Starting deterministic LBank Catalog sync...")
        new_symbols_raw = await self.fetch_lbank_futures_symbols()
        
        # اگر در شبکه خطایی رخ داد، لیست قبلی را پاک نمی‌کنیم (رد تحلیل جعلی)
        if not new_symbols_raw:
            logger.warning("No valid targets retrieved. Sync aborted to preserve current state.")
            return

        new_symbols_map = {item["symbol"]: item for item in new_symbols_raw}
        
        current_symbols: Set[str] = set(self.active_candidates.keys())
        fetched_symbols: Set[str] = set(new_symbols_map.keys())

        added = fetched_symbols - current_symbols
        removed = current_symbols - fetched_symbols

        for sym in added:
            self.active_candidates[sym] = new_symbols_map[sym]
            logger.info(f"[NEW TARGET] {sym} | Meme: {new_symbols_map[sym]['is_meme']} | Vol: ${new_symbols_map[sym]['quote_volume']:,.0f}")

        for sym in removed:
            del self.active_candidates[sym]
            logger.info(f"[DROPPED] {sym} (Failed liquidity/price checks).")

        for sym in fetched_symbols.intersection(current_symbols):
            self.active_candidates[sym].update(new_symbols_map[sym])

        if self.db:
            self.db.update_candidates(self.active_candidates)

    async def start_background_scanner(self, interval_seconds: int = 14400):
        """اجرای سیکل به‌روزرسانی (طبق قانون: دقیقاً هر 4 ساعت = 14400 ثانیه)"""
        self._is_running = True
        while self._is_running:
            try:
                await self.update_catalog()
            except Exception as e:
                logger.error(f"Background scanner error: {e}")
            
            await asyncio.sleep(interval_seconds)

    def stop(self):
        self._is_running = False
