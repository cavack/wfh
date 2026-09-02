import asyncio
import copy
import logging
import math
import time

from waterfallhunter.core.liquidation_flow import LIQUIDATION_FLOW_FRESHNESS_SECONDS
from waterfallhunter.core.multi_exchange import MultiExchangeGateway
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
        # Keep shared FUEL-RICH subscriptions on dedicated CCXT Pro clients so
        # their dynamic unwatch operations cannot cancel PRE-TRIGGER/ARMED
        # direct subscriptions that use the same venue/message hashes.
        self.shared_evidence_exchanges: Dict[str, Any] = {}

        # ساختار کش: { 'exchange:symbol': {'data': orderbook, 'updated_at': timestamp} }
        self.live_orderbooks: Dict[str, Dict[str, Any]] = {}
        self.live_orderbook_history: Dict[str, list[Dict[str, Any]]] = {}
        self.live_tickers: Dict[str, Dict[str, Any]] = {}
        self.live_trades: Dict[str, Dict[str, Any]] = {}
        self.orderbook_history_limit = 8
        self.trade_history_limit = 500
        self.trade_ttl_seconds = 60.0
        self.live_liquidations: Dict[str, Dict[str, Any]] = {}
        self.liquidation_window_seconds = LIQUIDATION_FLOW_FRESHNESS_SECONDS
        self.liquidation_retention_seconds = 120.0
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.message_counters: Dict[str, int] = {}
        self.unsupported_liquidation_exchanges: set[str] = set()
        # Binance exposes an official all-market liquidation stream. Track
        # desired symbols separately so PRE-TRIGGER evidence uses one bounded
        # consumer instead of one WebSocket subscription per symbol.
        self.liquidation_subscribers: Dict[str, set[str]] = {}
        # Wave B: FUEL-RICH symbols may share one bounded multi-symbol
        # orderbook/trade/ticker task family per capable exchange.
        self.shared_evidence_subscribers: Dict[str, set[str]] = {}
        self.unsupported_shared_evidence_exchanges: set[str] = set()
        self.shared_evidence_symbol_limit = 64

        # قانون سخت: دیتای قدیمی‌تر از 5 ثانیه منقضی (Stale) محسوب می‌شود
        self.ttl_seconds = 5.0
        self._lock = asyncio.Lock()
        # One slot per concurrent stream consumer instead of a shared pool:
        # every stream holds its slot only around the await boundary it needs,
        # so N symbols no longer starve each other through a single semaphore.
        self._stream_slots = asyncio.Semaphore(10)

    def _ingest_orderbook(
        self,
        ex_name: str,
        symbol: str,
        orderbook: Any,
        *,
        received_at: float | None = None,
    ) -> None:
        if not isinstance(orderbook, dict):
            return
        now = time.time() if received_at is None else float(received_at)
        if not math.isfinite(now) or now < 0:
            return
        stream_id = f"{ex_name}:{symbol}"
        snapshot = copy.deepcopy(orderbook)
        snapshot["_received_at"] = now
        self.live_orderbooks[stream_id] = {
            "data": snapshot,
            "updated_at": now,
        }
        history = self.live_orderbook_history.setdefault(stream_id, [])
        history.append(snapshot)
        if len(history) > self.orderbook_history_limit:
            del history[:-self.orderbook_history_limit]

    @staticmethod
    def _trade_fingerprint(trade: Dict[str, Any]) -> tuple[Any, ...]:
        trade_id = trade.get("id")
        if trade_id not in (None, ""):
            return ("id", str(trade_id), None, None, None)
        return (
            "fields", trade.get("timestamp"), trade.get("side"),
            trade.get("price"), trade.get("amount"),
        )

    def _ingest_trades(
        self,
        ex_name: str,
        symbol: str,
        rows: Any,
        *,
        received_at: float | None = None,
    ) -> None:
        now = time.time() if received_at is None else float(received_at)
        if not math.isfinite(now) or now < 0:
            return
        stream_id = f"{ex_name}:{symbol}"
        existing = self.live_trades.get(stream_id, {}).get("data", [])
        combined = [copy.deepcopy(row) for row in existing if isinstance(row, dict)]
        iterable = rows if isinstance(rows, list) else [rows]
        combined.extend(copy.deepcopy(row) for row in iterable if isinstance(row, dict))
        cutoff_ms = (now - self.trade_ttl_seconds) * 1000.0
        deduped: dict[tuple[Any, ...], Dict[str, Any]] = {}
        for trade in combined:
            timestamp = trade.get("timestamp")
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                continue
            if timestamp <= 0 or float(timestamp) < cutoff_ms:
                continue
            deduped[self._trade_fingerprint(trade)] = trade
        fresh = sorted(
            deduped.values(),
            key=lambda trade: float(trade.get("timestamp") or 0.0),
        )[-self.trade_history_limit:]
        self.live_trades[stream_id] = {"data": fresh, "updated_at": now}

    @staticmethod
    def _new_exchange(ex_name: str) -> Any:
        if ccxt_pro is None:
            raise RuntimeError("CCXT Pro is not installed; WebSocket streaming is unavailable")
        ccxt_id = MultiExchangeGateway._ccxt_exchange_id(ex_name)
        ex_class = getattr(ccxt_pro, ccxt_id)
        return ex_class({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })

    async def _get_exchange(self, ex_name: str) -> Any:
        if ex_name not in self.exchanges:
            self.exchanges[ex_name] = self._new_exchange(ex_name)
        return self.exchanges[ex_name]

    async def _get_shared_evidence_exchange(self, ex_name: str) -> Any:
        # Three shared task kinds start together. Serialize first construction
        # so exactly one dedicated exchange client exists per venue.
        async with self._lock:
            if ex_name not in self.shared_evidence_exchanges:
                self.shared_evidence_exchanges[ex_name] = self._new_exchange(ex_name)
            return self.shared_evidence_exchanges[ex_name]

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

                # Preserve an immutable bounded history because CCXT Pro may
                # mutate its live OrderBook object in place between updates.
                self._ingest_orderbook(
                    ex_name, symbol, orderbook, received_at=time.time()
                )

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
                received_at = time.time()
                if kind == "trades":
                    self._ingest_trades(
                        ex_name, symbol, data, received_at=received_at
                    )
                else:
                    cache[f"{ex_name}:{symbol}"] = {
                        "data": copy.deepcopy(data),
                        "updated_at": received_at,
                    }
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

    @staticmethod
    def _shared_liquidation_watcher(exchange: Any):
        watch = getattr(exchange, "watch_liquidations_for_symbols", None)
        supports = getattr(exchange, "has", {}).get("watchLiquidationsForSymbols")
        return watch if callable(watch) and supports is True else None

    @staticmethod
    def _group_subscribed_liquidations(
        rows: Any, subscribers: set[str]
    ) -> Dict[str, list[Dict[str, Any]]]:
        grouped: Dict[str, list[Dict[str, Any]]] = {}
        iterable = rows if isinstance(rows, list) else [rows]
        for row in iterable:
            if not isinstance(row, dict):
                continue
            symbol = row.get("symbol")
            if isinstance(symbol, str) and symbol in subscribers:
                grouped.setdefault(symbol, []).append(row)
        return grouped

    async def _consume_shared_liquidations(
        self, ex_name: str, watch: Any
    ) -> None:
        # An empty symbol list selects Binance's official all-market
        # !forceOrder@arr feed. Route only lifecycle-requested symbols.
        rows = await watch([], limit=1000)
        subscribers = set(self.liquidation_subscribers.get(ex_name, ()))
        grouped = self._group_subscribed_liquidations(rows, subscribers)
        received_at = time.time()
        for symbol, symbol_rows in grouped.items():
            self._ingest_liquidations(
                ex_name, symbol, symbol_rows, received_at=received_at
            )

    async def _watch_shared_liquidations_stream(self, ex_name: str) -> None:
        """Consume one exchange-wide liquidation stream and route subscribed symbols."""
        task_id = f"{ex_name}:liquidations"
        try:
            exchange = await self._get_exchange(ex_name)
            watch = self._shared_liquidation_watcher(exchange)
            if watch is None:
                self.unsupported_liquidation_exchanges.add(ex_name)
                logger.info("Shared liquidation stream unavailable for %s", ex_name)
                return
            breaker = self.circuit_breakers.setdefault(task_id, CircuitBreaker())
            delay = 1.0
            while task_id in self.active_tasks:
                if not self.liquidation_subscribers.get(ex_name):
                    await asyncio.sleep(0.25)
                    continue
                if not breaker.can_try():
                    await asyncio.sleep(1.0)
                    continue
                try:
                    await self._consume_shared_liquidations(ex_name, watch)
                    self.message_counters[task_id] = self.message_counters.get(task_id, 0) + 1
                    breaker.record_success()
                    delay = 1.0
                except Exception as exc:
                    breaker.record_failure()
                    logger.debug(
                        "Shared liquidation stream unavailable for %s: %s",
                        ex_name, type(exc).__name__,
                    )
                    await asyncio.sleep(cb_recovery(breaker, delay))
                    delay = min(delay * 2, 15.0)
        finally:
            current_task = asyncio.current_task()
            if self.active_tasks.get(task_id) is current_task:
                self.active_tasks.pop(task_id, None)

    async def _watch_liquidations_stream(self, ex_name: str, symbol: str) -> None:
        task_id = f"{ex_name}:{symbol}:liquidations"
        try:
            exchange = await self._get_exchange(ex_name)
            watch = getattr(exchange, "watch_liquidations", None)
            supports = getattr(exchange, "has", {}).get("watchLiquidations")
            if not callable(watch) or supports not in {True, "emulated"}:
                self.unsupported_liquidation_exchanges.add(ex_name)
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
            current_task = asyncio.current_task()
            if self.active_tasks.get(task_id) is current_task:
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

    @staticmethod
    def _shared_evidence_capable(exchange: Any) -> bool:
        required = (
            ("watchOrderBookForSymbols", "watch_order_book_for_symbols"),
            ("unWatchOrderBookForSymbols", "un_watch_order_book_for_symbols"),
            ("watchTradesForSymbols", "watch_trades_for_symbols"),
            ("unWatchTradesForSymbols", "un_watch_trades_for_symbols"),
            ("watchTickers", "watch_tickers"),
            ("unWatchTickers", "un_watch_tickers"),
        )
        capabilities = getattr(exchange, "has", {})
        return all(
            capabilities.get(flag) is True and callable(getattr(exchange, method, None))
            for flag, method in required
        )

    @staticmethod
    def _shared_payload_rows(payload: Any) -> list[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        if isinstance(payload.get("symbol"), str):
            return [payload]
        return [row for row in payload.values() if isinstance(row, dict)]

    def _ingest_shared_orderbook_update(
        self,
        ex_name: str,
        payload: Any,
        *,
        allowed_symbols: set[str],
        received_at: float,
    ) -> None:
        symbol = payload.get("symbol") if isinstance(payload, dict) else None
        if isinstance(symbol, str) and symbol in allowed_symbols:
            self._ingest_orderbook(ex_name, symbol, payload, received_at=received_at)

    def _ingest_shared_trade_update(
        self,
        ex_name: str,
        payload: Any,
        *,
        allowed_symbols: set[str],
        received_at: float,
    ) -> None:
        grouped: Dict[str, list[Dict[str, Any]]] = {}
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            symbol = row.get("symbol") if isinstance(row, dict) else None
            if isinstance(symbol, str) and symbol in allowed_symbols:
                grouped.setdefault(symbol, []).append(row)
        for symbol, symbol_rows in grouped.items():
            self._ingest_trades(ex_name, symbol, symbol_rows, received_at=received_at)

    def _ingest_shared_ticker_update(
        self,
        ex_name: str,
        payload: Any,
        *,
        allowed_symbols: set[str],
        received_at: float,
    ) -> None:
        for row in self._shared_payload_rows(payload):
            symbol = row.get("symbol")
            if isinstance(symbol, str) and symbol in allowed_symbols:
                self.live_tickers[f"{ex_name}:{symbol}"] = {
                    "data": copy.deepcopy(row),
                    "updated_at": float(received_at),
                }

    def _ingest_shared_evidence_update(
        self,
        ex_name: str,
        kind: str,
        payload: Any,
        *,
        allowed_symbols: set[str],
        received_at: float,
    ) -> None:
        if not allowed_symbols:
            return
        handlers = {
            "orderbook": self._ingest_shared_orderbook_update,
            "trades": self._ingest_shared_trade_update,
            "ticker": self._ingest_shared_ticker_update,
        }
        handler = handlers.get(kind)
        if handler is not None:
            handler(
                ex_name,
                payload,
                allowed_symbols=allowed_symbols,
                received_at=received_at,
            )

    @staticmethod
    def _shared_evidence_methods(exchange: Any, kind: str) -> tuple[Any, Any]:
        methods = {
            "orderbook": (
                "watch_order_book_for_symbols", "un_watch_order_book_for_symbols"
            ),
            "trades": ("watch_trades_for_symbols", "un_watch_trades_for_symbols"),
            "ticker": ("watch_tickers", "un_watch_tickers"),
        }
        watch_name, unwatch_name = methods[kind]
        return getattr(exchange, watch_name), getattr(exchange, unwatch_name)

    def _shared_evidence_symbols(self, ex_name: str) -> tuple[str, ...]:
        return tuple(sorted(self.shared_evidence_subscribers.get(ex_name, ())))

    async def _unwatch_shared_evidence_symbols(
        self,
        unwatch: Any,
        symbols: tuple[str, ...],
        *,
        ex_name: str,
        kind: str,
        final: bool = False,
    ) -> bool:
        if not symbols:
            return True
        try:
            await unwatch(list(symbols))
        except Exception as exc:
            phase = "final " if final else ""
            logger.debug(
                "Shared evidence %sunwatch failed for %s:%s: %s",
                phase,
                ex_name,
                kind,
                type(exc).__name__,
            )
            return False
        return True

    @staticmethod
    async def _watch_shared_evidence_payload(
        watch: Any,
        *,
        ex_name: str,
        kind: str,
        symbols: tuple[str, ...],
    ) -> Any:
        if kind == "orderbook":
            safe_limit = 50 if ex_name in {"bybit", "kucoin"} else 20
            return await watch(list(symbols), limit=safe_limit)
        if kind == "trades":
            return await watch(list(symbols), limit=500)
        return await watch(list(symbols))

    async def _shared_evidence_iteration(
        self,
        *,
        ex_name: str,
        kind: str,
        task_id: str,
        watch: Any,
        unwatch: Any,
        breaker: CircuitBreaker,
        active_symbols: tuple[str, ...],
        delay: float,
    ) -> tuple[tuple[str, ...], float]:
        desired = self._shared_evidence_symbols(ex_name)
        if not desired:
            await asyncio.sleep(0.25)
            return active_symbols, delay
        if desired != active_symbols:
            retired = await self._unwatch_shared_evidence_symbols(
                unwatch,
                active_symbols,
                ex_name=ex_name,
                kind=kind,
            )
            if not retired:
                return active_symbols, delay
            active_symbols = desired
        if not breaker.can_try():
            await asyncio.sleep(1.0)
            return active_symbols, delay
        try:
            payload = await self._watch_shared_evidence_payload(
                watch,
                ex_name=ex_name,
                kind=kind,
                symbols=active_symbols,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            breaker.record_failure()
            logger.debug(
                "Shared evidence stream unavailable for %s:%s: %s",
                ex_name,
                kind,
                type(exc).__name__,
            )
            await asyncio.sleep(cb_recovery(breaker, delay))
            return active_symbols, min(delay * 2, 15.0)
        self._ingest_shared_evidence_update(
            ex_name,
            kind,
            payload,
            allowed_symbols=set(self.shared_evidence_subscribers.get(ex_name, ())),
            received_at=time.time(),
        )
        self.message_counters[task_id] = self.message_counters.get(task_id, 0) + 1
        breaker.record_success()
        return active_symbols, 1.0

    async def _finalize_shared_evidence_task(
        self,
        *,
        ex_name: str,
        kind: str,
        task_id: str,
        exchange: Any | None,
        active_symbols: tuple[str, ...],
    ) -> None:
        if exchange is not None and self._shared_evidence_capable(exchange):
            _, unwatch = self._shared_evidence_methods(exchange, kind)
            await self._unwatch_shared_evidence_symbols(
                unwatch,
                active_symbols,
                ex_name=ex_name,
                kind=kind,
                final=True,
            )
        current_task = asyncio.current_task()
        if self.active_tasks.get(task_id) is current_task:
            self.active_tasks.pop(task_id, None)

    async def _watch_shared_evidence_stream(self, ex_name: str, kind: str) -> None:
        task_id = f"shared-evidence:{ex_name}:{kind}"
        active_symbols: tuple[str, ...] = ()
        exchange: Any | None = None
        try:
            exchange = await self._get_shared_evidence_exchange(ex_name)
            if not self._shared_evidence_capable(exchange):
                self.unsupported_shared_evidence_exchanges.add(ex_name)
                self.shared_evidence_subscribers.pop(ex_name, None)
                logger.info("Shared evidence pool unsupported for %s", ex_name)
                return
            watch, unwatch = self._shared_evidence_methods(exchange, kind)
            breaker = self.circuit_breakers.setdefault(task_id, CircuitBreaker())
            delay = 1.0
            while task_id in self.active_tasks:
                active_symbols, delay = await self._shared_evidence_iteration(
                    ex_name=ex_name,
                    kind=kind,
                    task_id=task_id,
                    watch=watch,
                    unwatch=unwatch,
                    breaker=breaker,
                    active_symbols=active_symbols,
                    delay=delay,
                )
        finally:
            await self._finalize_shared_evidence_task(
                ex_name=ex_name,
                kind=kind,
                task_id=task_id,
                exchange=exchange,
                active_symbols=active_symbols,
            )

    def subscribe_shared_evidence(self, ex_name: str, symbol: str) -> bool:
        if ccxt_pro is None or ex_name in self.unsupported_shared_evidence_exchanges:
            return False
        subscribers = self.shared_evidence_subscribers.setdefault(ex_name, set())
        if symbol not in subscribers and len(subscribers) >= self.shared_evidence_symbol_limit:
            logger.warning(
                "Shared evidence subscriber limit reached for %s; REST fallback remains active",
                ex_name,
            )
            return False
        subscribers.add(symbol)
        for kind in ("orderbook", "trades", "ticker"):
            task_id = f"shared-evidence:{ex_name}:{kind}"
            if task_id not in self.active_tasks:
                self.active_tasks[task_id] = asyncio.create_task(
                    self._watch_shared_evidence_stream(ex_name, kind)
                )
        return True

    def unsubscribe_shared_evidence(self, ex_name: str, symbol: str) -> None:
        subscribers = self.shared_evidence_subscribers.get(ex_name)
        if subscribers is None:
            return
        subscribers.discard(symbol)
        if subscribers:
            return
        self.shared_evidence_subscribers.pop(ex_name, None)
        for kind in ("orderbook", "trades", "ticker"):
            task = self.active_tasks.pop(f"shared-evidence:{ex_name}:{kind}", None)
            if task is not None:
                task.cancel()

    def has_direct_evidence_subscription(self, ex_name: str, symbol: str) -> bool:
        stream_id = f"{ex_name}:{symbol}"
        return any(
            task_id == stream_id or task_id in {f"{stream_id}:ticker", f"{stream_id}:trades"}
            for task_id in self.active_tasks
        )

    def subscribe_liquidations(self, ex_name: str, symbol: str):
        """Start bounded liquidation evidence acquisition for early PRE-TRIGGER state."""
        if ccxt_pro is None:
            logger.warning(
                "CCXT Pro is unavailable; skipping liquidation subscription for %s:%s",
                ex_name,
                symbol,
            )
            return
        if ex_name in self.unsupported_liquidation_exchanges:
            return
        if ex_name == "binance":
            self.liquidation_subscribers.setdefault(ex_name, set()).add(symbol)
            liquidation_id = f"{ex_name}:liquidations"
            if liquidation_id not in self.active_tasks:
                self.active_tasks[liquidation_id] = asyncio.create_task(
                    self._watch_shared_liquidations_stream(ex_name)
                )
            return
        liquidation_id = f"{ex_name}:{symbol}:liquidations"
        if liquidation_id not in self.active_tasks:
            self.active_tasks[liquidation_id] = asyncio.create_task(
                self._watch_liquidations_stream(ex_name, symbol)
            )

    def refresh_liquidation_capability(self, ex_name: str | None = None) -> None:
        """Forget cached unsupported capability after an explicit refresh request."""
        if ex_name is None:
            self.unsupported_liquidation_exchanges.clear()
        else:
            self.unsupported_liquidation_exchanges.discard(ex_name)

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
        self.live_orderbook_history.pop(stream_id, None)
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

    def _detach_shared_liquidation_subscriber(self, ex_name: str, symbol: str) -> None:
        if ex_name != "binance":
            return
        subscribers = self.liquidation_subscribers.get(ex_name)
        if subscribers is None:
            return
        subscribers.discard(symbol)
        if subscribers:
            return
        self.liquidation_subscribers.pop(ex_name, None)
        shared_task = self.active_tasks.pop(f"{ex_name}:liquidations", None)
        if shared_task is not None:
            shared_task.cancel()

    def unsubscribe(self, ex_name: str, symbol: str):
        stream_id = f"{ex_name}:{symbol}"
        self._detach_shared_liquidation_subscriber(ex_name, symbol)
        for task_id in [key for key in self.active_tasks if key == stream_id or key.startswith(f"{stream_id}:")]:
            self.active_tasks.pop(task_id).cancel()
        self.live_orderbooks.pop(stream_id, None)
        self.live_orderbook_history.pop(stream_id, None)
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
        """Return only a fresh latest OrderBook snapshot."""
        stream_id = f"{ex_name}:{symbol}"
        cached = self.live_orderbooks.get(stream_id)
        if not cached:
            return None
        if time.time() - cached["updated_at"] > self.ttl_seconds:
            logger.debug(f"Cache TTL expired for {stream_id}. Triggering REST fallback.")
            return None
        return copy.deepcopy(cached["data"])

    def get_realtime_orderbook_samples(
        self,
        ex_name: str,
        symbol: str,
        *,
        count: int = 3,
        min_span_seconds: float = 0.5,
        now: float | None = None,
    ) -> list[Dict[str, Any]]:
        observed_now = time.time() if now is None else float(now)
        if not math.isfinite(observed_now) or observed_now < 0 or count <= 0:
            return []
        history = self.live_orderbook_history.get(f"{ex_name}:{symbol}", [])
        cutoff = observed_now - self.ttl_seconds
        fresh = [
            snapshot for snapshot in history
            if isinstance(snapshot.get("_received_at"), (int, float))
            and not isinstance(snapshot.get("_received_at"), bool)
            and cutoff <= float(snapshot["_received_at"]) <= observed_now
        ]
        if len(fresh) < count:
            return []
        selected = fresh[-count:]
        span = float(selected[-1]["_received_at"]) - float(selected[0]["_received_at"])
        if span < max(0.0, float(min_span_seconds)):
            return []
        return copy.deepcopy(selected)

    def _cached(self, cache: Dict[str, Dict[str, Any]], ex_name: str, symbol: str):
        entry = cache.get(f"{ex_name}:{symbol}")
        return (
            copy.deepcopy(entry["data"])
            if entry and time.time() - entry["updated_at"] <= self.ttl_seconds
            else None
        )

    def get_realtime_ticker(self, ex_name: str, symbol: str):
        return self._cached(self.live_tickers, ex_name, symbol)

    def get_realtime_trades(
        self, ex_name: str, symbol: str, *, now: float | None = None
    ) -> list[Dict[str, Any]]:
        observed_now = time.time() if now is None else float(now)
        if not math.isfinite(observed_now) or observed_now < 0:
            return []
        entry = self.live_trades.get(f"{ex_name}:{symbol}")
        rows = entry.get("data") if isinstance(entry, dict) else None
        if not isinstance(rows, list):
            return []
        cutoff_ms = (observed_now - self.trade_ttl_seconds) * 1000.0
        return [
            copy.deepcopy(row)
            for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("timestamp"), (int, float))
            and not isinstance(row.get("timestamp"), bool)
            and cutoff_ms <= float(row["timestamp"]) <= observed_now * 1000.0
        ][-self.trade_history_limit:]

    def runtime_diagnostics(self) -> Dict[str, int]:
        """Return bounded task/subscriber counts for operational fan-out telemetry."""
        task_ids = tuple(self.active_tasks)
        liquidation_task_ids = tuple(
            task_id for task_id in task_ids if task_id.endswith(":liquidations")
        )
        shared_evidence_task_ids = tuple(
            task_id for task_id in task_ids if task_id.startswith("shared-evidence:")
        )
        return {
            "active_tasks": len(task_ids),
            "liquidation_tasks": len(liquidation_task_ids),
            "shared_liquidation_tasks": sum(
                1 for task_id in liquidation_task_ids if task_id.count(":") == 1
            ),
            "shared_liquidation_subscribers": sum(
                len(symbols) for symbols in self.liquidation_subscribers.values()
            ),
            "shared_evidence_tasks": len(shared_evidence_task_ids),
            "shared_evidence_subscribers": sum(
                len(symbols) for symbols in self.shared_evidence_subscribers.values()
            ),
        }

    @staticmethod
    def _prune_latest_cache(
        cache: Dict[str, Dict[str, Any]],
        *,
        cutoff: float,
    ) -> None:
        for key, entry in tuple(cache.items()):
            if entry.get("updated_at", 0) < cutoff:
                cache.pop(key, None)

    def _prune_orderbook_history(self, *, cutoff: float) -> None:
        for key, history in tuple(self.live_orderbook_history.items()):
            fresh = [
                snapshot
                for snapshot in history
                if isinstance(snapshot.get("_received_at"), (int, float))
                and not isinstance(snapshot.get("_received_at"), bool)
                and float(snapshot["_received_at"]) >= cutoff
            ]
            if fresh:
                self.live_orderbook_history[key] = fresh[-self.orderbook_history_limit:]
            else:
                self.live_orderbook_history.pop(key, None)

    def _prune_trade_history(self, *, cutoff_ms: float, now_ms: float) -> None:
        for key, entry in tuple(self.live_trades.items()):
            rows = entry.get("data") if isinstance(entry, dict) else None
            fresh = [
                row
                for row in (rows or [])
                if isinstance(row, dict)
                and isinstance(row.get("timestamp"), (int, float))
                and not isinstance(row.get("timestamp"), bool)
                and cutoff_ms <= float(row["timestamp"]) <= now_ms
            ]
            if fresh:
                entry["data"] = fresh[-self.trade_history_limit:]
            else:
                self.live_trades.pop(key, None)

    def _prune_liquidation_history(self, *, cutoff_ms: float, now_ms: float) -> None:
        for key, entry in tuple(self.live_liquidations.items()):
            events = [
                event
                for event in entry.get("events", [])
                if isinstance(event, dict)
                and cutoff_ms <= float(event.get("timestamp", 0)) <= now_ms
            ]
            if events:
                entry["events"] = events
            else:
                self.live_liquidations.pop(key, None)

    def prune_stale_cache(self):
        """Prune all process-local evidence caches to their causal TTL windows."""
        now = time.time()
        cutoff = now - self.ttl_seconds
        for cache in (self.live_orderbooks, self.live_tickers):
            self._prune_latest_cache(cache, cutoff=cutoff)
        self._prune_orderbook_history(cutoff=cutoff)
        self._prune_trade_history(
            cutoff_ms=(now - self.trade_ttl_seconds) * 1000.0,
            now_ms=now * 1000.0,
        )
        self._prune_liquidation_history(
            cutoff_ms=(now - self.liquidation_retention_seconds) * 1000.0,
            now_ms=now * 1000.0,
        )

    async def close_all(self):
        tasks = list(self.active_tasks.values())
        for task in tasks:
            task.cancel()
        self.active_tasks.clear()
        self.liquidation_subscribers.clear()
        self.shared_evidence_subscribers.clear()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        for ex in (*self.exchanges.values(), *self.shared_evidence_exchanges.values()):
            await ex.close()
        self.exchanges.clear()
        self.shared_evidence_exchanges.clear()


def cb_recovery(breaker: CircuitBreaker, current_delay: float) -> float:
    """Pause length after a failure, honouring the breaker's OPEN timeout."""
    if breaker.state == "OPEN":
        return breaker.recovery_timeout
    return current_delay + random.uniform(0.1, 0.5)
