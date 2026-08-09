import asyncio
import logging
import time
import random
from typing import Dict, Any, Optional
import ccxt.pro as ccxt_pro

logger = logging.getLogger("WaterfallHunter.WebSockets")

class CircuitBreaker:
    """قطع‌کننده مدار 3-حالته برای مدیریت هوشمند قطعی‌های صرافی"""
    def __init__(self, failure_threshold=3, recovery_timeout=30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = 0.0
        self.state = "CLOSED"  # حالت‌ها: CLOSED (سالم), OPEN (قطع), HALF_OPEN (در حال تست)

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.failure_threshold:
            self.state = "OPEN"

    def record_success(self):
        self.failures = 0
        self.state = "CLOSED"

    def can_try(self) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                return True
            return False
        return True  # در حالت HALF_OPEN یک شانس مجدد می‌دهیم

class WebSocketManager:
    def __init__(self):
        self.exchanges_names = ['binance', 'mexc', 'bingx', 'kucoin', 'okx']
        self.exchanges: Dict[str, ccxt_pro.Exchange] = {}
        
        # ساختار کش: { 'exchange:symbol': {'data': orderbook, 'updated_at': timestamp} }
        self.live_orderbooks: Dict[str, Dict[str, Any]] = {}
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.message_counters: Dict[str, int] = {}
        
        # قانون سخت: دیتای قدیمی‌تر از 5 ثانیه منقضی (Stale) محسوب می‌شود
        self.ttl_seconds = 5.0 
        self._lock = asyncio.Lock()

    async def _get_exchange(self, ex_name: str) -> ccxt_pro.Exchange:
        if ex_name not in self.exchanges:
            ex_class = getattr(ccxt_pro, ex_name)
            self.exchanges[ex_name] = ex_class({
                'enableRateLimit': True,
                'options': {'defaultType': 'swap'}
            })
        return self.exchanges[ex_name]

    async def watch_orderbook_stream(self, ex_name: str, symbol: str, limit: int = 20):
        """مصرف‌کننده (Consumer) دائمی با پایداری سطح نهادی (Institutional)"""
        stream_id = f"{ex_name}:{symbol}"
        
        async with self._lock:
            if stream_id not in self.circuit_breakers:
                self.circuit_breakers[stream_id] = CircuitBreaker()
            self.message_counters[stream_id] = 0

        exchange = await self._get_exchange(ex_name)
        cb = self.circuit_breakers[stream_id]
        retry_delay = 1.0

        logger.info(f"🟢 [WS START] Subscribed to {stream_id}")

        while stream_id in self.active_tasks:
            if not cb.can_try():
                await asyncio.sleep(1.0)
                continue

            try:
                # برای کوکوین و بای‌بیت محدودیت‌های اوردربوک متفاوت است
                safe_limit = 50 if ex_name in ['bybit', 'kucoin'] else limit
                orderbook = await exchange.watch_order_book(symbol, limit=safe_limit)
                
                # Single-flight Cache Update
                self.live_orderbooks[stream_id] = {
                    "data": orderbook,
                    "updated_at": time.time()
                }
                
                self.message_counters[stream_id] += 1
                cb.record_success()
                retry_delay = 1.0  # ریست کردن بک‌آف در صورت موفقیت

            except Exception as e:
                cb.record_failure()
                
                if cb.state == "OPEN":
                    logger.error(f"🛑 [CIRCUIT BREAKER OPEN] for {stream_id}. Network unstable. Pausing for {cb.recovery_timeout}s.")
                else:
                    # Exponential Backoff with Jitter (جلوگیری از حملات Throttling)
                    jitter = random.uniform(0.1, 0.5)
                    sleep_time = retry_delay + jitter
                    logger.warning(f"⚠️ [WS ERROR] {stream_id} disconnected: {str(e)[:60]}. Reconnecting in {sleep_time:.2f}s...")
                    
                    await asyncio.sleep(sleep_time)
                    retry_delay = min(retry_delay * 2, 15.0)

        logger.info(f"🛑 [WS STOP] Stream terminated for {stream_id}")

    def subscribe(self, ex_name: str, symbol: str):
        """الگوی Single-flight: اطمینان از عدم ایجاد Task تکراری برای یک نماد"""
        stream_id = f"{ex_name}:{symbol}"
        if stream_id not in self.active_tasks:
            task = asyncio.create_task(self.watch_orderbook_stream(ex_name, symbol))
            self.active_tasks[stream_id] = task

    def unsubscribe(self, ex_name: str, symbol: str):
        stream_id = f"{ex_name}:{symbol}"
        task = self.active_tasks.pop(stream_id, None)
        if task:
            task.cancel()
        self.live_orderbooks.pop(stream_id, None)

    def get_realtime_orderbook(self, ex_name: str, symbol: str) -> Optional[Dict]:
        """فراخوانی دیتا با اعمال Cache TTL برای REST Fallback"""
        stream_id = f"{ex_name}:{symbol}"
        cached = self.live_orderbooks.get(stream_id)
        
        if not cached:
            return None
            
        # اگر دیتا قدیمی‌تر از 5 ثانیه باشد (مثلا قطعیِ سوکت رخ داده)، None برمی‌گرداند 
        # تا سیستم مرکزی به صورت خودکار به REST API سوییچ (Fallback) کند.
        if time.time() - cached["updated_at"] > self.ttl_seconds:
            logger.debug(f"Cache TTL expired for {stream_id}. Triggering REST fallback.")
            return None
            
        return cached["data"]

    async def close_all(self):
        for stream_id, task in self.active_tasks.items():
            task.cancel()
        self.active_tasks.clear()
        
        for ex in self.exchanges.values():
            await ex.close()
        self.exchanges.clear()
