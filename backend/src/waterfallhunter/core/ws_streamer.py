import asyncio
import logging
import math
import time

from waterfallhunter.core.liquidation_flow import LIQUIDATION_FLOW_FRESHNESS_SECONDS
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
        self.live_liquidations: Dict[str, Dict[str, Any]] = {}
        self.liquidation_window_seconds = LIQUIDATION_FLOW_FRESHNESS_SECONDS
        self.liquidation_retention_seconds = 120.0
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

    @staticmethod
    def _positive_number(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) and number > 0 else None

    @classmethod
    def _normalized_liquidation(cls, row: Any) -> Dict[str, Any] | None:
        if not isinstance(row, dict):
            return None
        timestamp = cls._positive_number(row.get("timestamp"))
        side = str(row.get("side") or "").lower()
        if timestamp is None or side not in {"buy", "sell"}:
            return None
        quote_value = cls._positive_number(row.get("quoteValue"))
        if quote_value is None:
            contracts = cls._positive_number(row.get("contracts"))
            contract_size = cls._positive_number(row.get("contractSize"))
            price = cls._positive_number(row.get("price"))
            if contracts is None or contract_size is None or price is None:
                return None
            quote_value = contracts * contract_size * price
        if not math.isfinite(quote_value) or quote_value <= 0:
            return None
        return {
            "timestamp": int(timestamp),
            "side": side,
            "notional_usd": float(quote_value),
        }

    def _ingest_liquidations(
        self, ex_name: str, symbol: str, rows: Any, *, received_at: float | None = None
    ) -> None:
        now = time.time() if received_at is None else float(received_at)
        if not math.isfinite(now) or now < 0:
            return
        stream_id = f"{ex_name}:{symbol}"
        existing = self.live_liquidations.get(stream_id, {}).get("events", [])
        cutoff_ms = (now - self.liquidation_retention_seconds) * 1000.0
        events = [
            event for event in existing
            if isinstance(event, dict) and float(event.get("timestamp", 0)) >= cutoff_ms
        ]
        seen = {
            (int(event["timestamp"]), str(event["side"]), float(event["notional_usd"]))
            for event in events
            if {"timestamp", "side", "notional_usd"} <= set(event)
        }
        iterable = rows if isinstance(rows, list) else [rows]
        for row in iterable:
            event = self._normalized_liquidation(row)
            if event is None or event["timestamp"] < cutoff_ms:
                continue
            fingerprint = (
                int(event["timestamp"]), str(event["side"]), float(event["notional_usd"])
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            events.append(event)
        events.sort(key=lambda item: int(item["timestamp"]))
        self.live_liquidations[stream_id] = {
            "events": events[-2000:],
            "updated_at": now,
        }

    async def _watch_liquidations_stream(self, ex_name: str, symbol: str) -> None:
        task_id = f"{ex_name}:{symbol}:liquidations"
        try:
            exchange = await self._get_exchange(ex_name)
            watch = getattr(exchange, "watch_liquidations", None)
            supports = getattr(exchange, "has", {}).get("watchLiquidations")
            if not callable(watch) or supports not in {True, "emulated"}:
                logger.info("Liquidation stream unavailable for %s:%s", ex_name, symbol)
                return
            breaker = self.circuit_breakers.setdefault(task_id, CircuitBreaker())
            delay = 1.0
            while task_id in self.active_tasks:
                if not breaker.can_try():
                    await asyncio.sleep(1.0)
                    continue
                try:
                    rows = await watch(symbol, limit=1000)
                    self._ingest_liquidations(ex_name, symbol, rows, received_at=time.time())
                    self.message_counters[task_id] = self.message_counters.get(task_id, 0) + 1
                    breaker.record_success()
                    delay = 1.0
                except Exception as exc:
                    breaker.record_failure()
                    logger.debug(
                        "Liquidation stream unavailable for %s:%s: %s",
                        ex_name, symbol, type(exc).__name__,
                    )
                    await asyncio.sleep(cb_recovery(breaker, delay))
                    delay = min(delay * 2, 15.0)
        finally:
            self.active_tasks.pop(task_id, None)

    def get_realtime_liquidation_flow(
        self, ex_name: str, symbol: str, *, now: float | None = None
    ) -> Optional[Dict[str, Any]]:
        observed_now = time.time() if now is None else float(now)
        if not math.isfinite(observed_now) or observed_now < 0:
            return None
        entry = self.live_liquidations.get(f"{ex_name}:{symbol}")
        events = entry.get("events") if isinstance(entry, dict) else None
        if not isinstance(events, list):
            return None
        current: list[Dict[str, Any]] = []
        baseline: list[Dict[str, Any]] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            timestamp = self._positive_number(event.get("timestamp"))
            notional = self._positive_number(event.get("notional_usd"))
            side = str(event.get("side") or "").lower()
            if timestamp is None or notional is None or side not in {"buy", "sell"}:
                continue
            age_seconds = observed_now - timestamp / 1000.0
            if 0 <= age_seconds < self.liquidation_window_seconds:
                current.append(event)
            elif self.liquidation_window_seconds <= age_seconds < self.liquidation_retention_seconds:
                baseline.append(event)
        if not current:
            return None
        long_notional = sum(float(event["notional_usd"]) for event in current if event["side"] == "sell")
        short_notional = sum(float(event["notional_usd"]) for event in current if event["side"] == "buy")
        current_total = long_notional + short_notional
        baseline_total = sum(float(event["notional_usd"]) for event in baseline)
        burst_ratio = current_total / baseline_total if baseline_total > 0 else 1.0
        latest_timestamp = max(int(event["timestamp"]) for event in current)
        return {
            "available": True,
            "source_exchange": ex_name,
            "mapped_symbol": symbol,
            "observed_at": latest_timestamp / 1000.0,
            "long_liquidation_notional_1m": round(long_notional, 6),
            "short_liquidation_notional_1m": round(short_notional, 6),
            "liquidation_velocity_usd_per_min": round(current_total, 6),
            "burst_ratio": round(burst_ratio, 6),
            "sample_count_1m": len(current),
            "baseline_notional_1m": round(baseline_total, 6),
        }

    def subscribe_liquidations(self, ex_name: str, symbol: str):
        """Start only the liquidation consumer for early PRE-TRIGGER evidence."""
        if ccxt_pro is None:
            logger.warning(
                "CCXT Pro is unavailable; skipping liquidation subscription for %s:%s",
                ex_name,
                symbol,
            )
            return
        liquidation_id = f"{ex_name}:{symbol}:liquidations"
        if liquidation_id not in self.active_tasks:
            self.active_tasks[liquidation_id] = asyncio.create_task(
                self._watch_liquidations_stream(ex_name, symbol)
            )

    def retain_liquidations_only(self, ex_name: str, symbol: str):
        """Keep the liquidation consumer while retiring heavier streams."""
        stream_id = f"{ex_name}:{symbol}"
        liquidation_id = f"{stream_id}:liquidations"
        for task_id in [
            key
            for key in list(self.active_tasks)
            if (key == stream_id or key.startswith(f"{stream_id}:"))
            and key != liquidation_id
        ]:
            task = self.active_tasks.pop(task_id, None)
            if task is not None:
                task.cancel()
        self.live_orderbooks.pop(stream_id, None)
        self.live_tickers.pop(stream_id, None)
        self.live_trades.pop(stream_id, None)
        for key in [
            key
            for key in list(self.circuit_breakers)
            if (key == stream_id or key.startswith(f"{stream_id}:"))
            and key != liquidation_id
        ]:
            self.circuit_breakers.pop(key, None)
        for key in [
            key
            for key in list(self.message_counters)
            if (key == stream_id or key.startswith(f"{stream_id}:"))
            and key != liquidation_id
        ]:
            self.message_counters.pop(key, None)
        self.subscribe_liquidations(ex_name, symbol)

    def subscribe(self, ex_name: str, symbol: str):
        """الگوی Single-flight: اطمینان از عدم ایجاد Task تکراری برای یک نماد"""
        if ccxt_pro is None:
            # The validator will automatically use its REST order-book fallback.
            logger.warning("CCXT Pro is unavailable; skipping WebSocket subscription for %s:%s", ex_name, symbol)
            return
        stream_id = f"{ex_name}:{symbol}"
        if stream_id not in self.active_tasks:
            self.active_tasks[stream_id] = asyncio.create_task(
                self.watch_orderbook_stream(ex_name, symbol)
            )
        for kind in ("ticker", "trades"):
            child_id = f"{stream_id}:{kind}"
            if child_id not in self.active_tasks:
                self.active_tasks[child_id] = asyncio.create_task(
                    self._watch_stream(ex_name, symbol, kind)
                )
        self.subscribe_liquidations(ex_name, symbol)

    def unsubscribe(self, ex_name: str, symbol: str):
        stream_id = f"{ex_name}:{symbol}"
        for task_id in [key for key in self.active_tasks if key == stream_id or key.startswith(f"{stream_id}:")]:
            self.active_tasks.pop(task_id).cancel()
        self.live_orderbooks.pop(stream_id, None)
        self.live_tickers.pop(stream_id, None)
        self.live_trades.pop(stream_id, None)
        self.live_liquidations.pop(stream_id, None)
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
        now = time.time()
        cutoff = now - self.ttl_seconds
        for cache in (self.live_orderbooks, self.live_tickers, self.live_trades):
            for key, entry in list(cache.items()):
                if entry.get("updated_at", 0) < cutoff:
                    cache.pop(key, None)
        liquidation_cutoff_ms = (now - self.liquidation_retention_seconds) * 1000.0
        for key, entry in list(self.live_liquidations.items()):
            events = [
                event for event in entry.get("events", [])
                if isinstance(event, dict) and float(event.get("timestamp", 0)) >= liquidation_cutoff_ms
            ]
            if events:
                entry["events"] = events
            else:
                self.live_liquidations.pop(key, None)

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
