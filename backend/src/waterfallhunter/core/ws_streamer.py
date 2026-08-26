import asyncio
import logging
import time
import random
from typing import Dict, Any, Optional

try:
    import ccxt.pro as ccxt_pro
except ImportError:  # CCXT Pro is a separately licensed package.
    ccxt_pro = None

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
        self.exchanges_names = ['binance', 'bybit', 'kucoin', 'okx', 'mexc', 'bingx']
        self.exchanges: Dict[str, Any] = {}

        # ساختار کش: { 'exchange:symbol': {'data': orderbook, 'updated_at': timestamp} }
        self.live_orderbooks: Dict[str, Dict[str, Any]] = {}
        self.live_tickers: Dict[str, Dict[str, Any]] = {}
        self.live_trades: Dict[str, Dict[str, Any]] = {}
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.message_counters: Dict[str, int] = {}

        # قانون سخت: دیتای قدیمی‌تر از 5 ثانیه منقضی (Stale) محسوب می‌شود
        self.ttl_seconds = 5.0
        self._lock = asyncio.Lock()
        # One slot per concurrent stream consumer instead of a shared pool:
        # every stream holds its slot only around the await boundary it needs,
        # so N symbols no longer starve each other through a single semaphore.
        self._stream_slots = asyncio.Semaphore(10)

    async def _get_exchange(self, ex_name: str) -> Any:
        if ccxt_pro is None:
            raise RuntimeError("CCXT Pro is not installed; WebSocket streaming is unavailable")
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
                    await asyncio.sleep(cb.recovery_timeout)
                else:
                    # Exponential Backoff with Jitter (جلوگیری از حملات Throttling)
                    jitter = random.uniform(0.1, 0.5)
                    sleep_time = retry_delay + jitter
                    logger.warning(f"⚠️ [WS ERROR] {stream_id} disconnected: {str(e)[:60]}. Reconnecting in {sleep_time:.2f}s...")

                    await asyncio.sleep(sleep_time)
                    retry_delay = min(retry_delay * 2, 15.0)

        logger.info(f"🛑 [WS STOP] Stream terminated for {stream_id}")

    async def _watch_stream(self, ex_name: str, symbol: str, kind: str):
        stream_id = f"{ex_name}:{symbol}:{kind}"
        exchange = await self._get_exchange(ex_name)
        breaker = self.circuit_breakers.setdefault(stream_id, CircuitBreaker())
        delay = 1.0
        cache = self.live_tickers if kind == "ticker" else self.live_trades
        while stream_id in self.active_tasks:
            if not breaker.can_try():
                await asyncio.sleep(1.0)
                continue
            try:
                data = await getattr(exchange, f"watch_{kind}")(symbol)
                cache[f"{ex_name}:{symbol}"] = {"data": data, "updated_at": time.time()}
                self.message_counters[stream_id] = self.message_counters.get(stream_id, 0) + 1
                breaker.record_success()
                delay = 1.0
            except Exception:
                breaker.record_failure()
                pause = cb_recovery(breaker, delay)
                await asyncio.sleep(pause)
                delay = min(delay * 2, 15.0)

    def subscribe(self, ex_name: str, symbol: str):
        """الگوی Single-flight: اطمینان از عدم ایجاد Task تکراری برای یک نماد"""
        if ccxt_pro is None:
            # The validator will automatically use its REST order-book fallback.
            logger.warning("CCXT Pro is unavailable; skipping WebSocket subscription for %s:%s", ex_name, symbol)
            return
        stream_id = f"{ex_name}:{symbol}"
        if stream_id not in self.active_tasks:
            task = asyncio.create_task(self.watch_orderbook_stream(ex_name, symbol))
            self.active_tasks[stream_id] = task
            for kind in ("ticker", "trades"):
                child_id = f"{stream_id}:{kind}"
                self.active_tasks[child_id] = asyncio.create_task(self._watch_stream(ex_name, symbol, kind))

    def unsubscribe(self, ex_name: str, symbol: str):
        stream_id = f"{ex_name}:{symbol}"
        for task_id in [key for key in self.active_tasks if key == stream_id or key.startswith(f"{stream_id}:")]:
            self.active_tasks.pop(task_id).cancel()
        self.live_orderbooks.pop(stream_id, None)
        self.live_tickers.pop(stream_id, None)
        self.live_trades.pop(stream_id, None)
        # Drop per-stream bookkeeping so symbol churn cannot grow these maps
        # without bound (previously circuit_breakers/message_counters leaked).
        for key in [key for key in list(self.circuit_breakers) if key == stream_id or key.startswith(f"{stream_id}:")]:
            self.circuit_breakers.pop(key, None)
        for key in [key for key in list(self.message_counters) if key == stream_id or key.startswith(f"{stream_id}:")]:
            self.message_counters.pop(key, None)

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

    def _cached(self, cache: Dict[str, Dict[str, Any]], ex_name: str, symbol: str):
        entry = cache.get(f"{ex_name}:{symbol}")
        return entry["data"] if entry and time.time() - entry["updated_at"] <= self.ttl_seconds else None

    def get_realtime_ticker(self, ex_name: str, symbol: str):
        return self._cached(self.live_tickers, ex_name, symbol)

    def get_realtime_trades(self, ex_name: str, symbol: str):
        return self._cached(self.live_trades, ex_name, symbol)

    def prune_stale_cache(self):
        cutoff = time.time() - self.ttl_seconds
        for cache in (self.live_orderbooks, self.live_tickers, self.live_trades):
            for key, entry in list(cache.items()):
                if entry.get("updated_at", 0) < cutoff:
                    cache.pop(key, None)

    async def close_all(self):
        for task in list(self.active_tasks.values()):
            task.cancel()
        self.active_tasks.clear()

        for ex in self.exchanges.values():
            await ex.close()
        self.exchanges.clear()


def cb_recovery(breaker: CircuitBreaker, current_delay: float) -> float:
    """Pause length after a failure, honouring the breaker's OPEN timeout."""
    if breaker.state == "OPEN":
        return breaker.recovery_timeout
    return current_delay + random.uniform(0.1, 0.5)
