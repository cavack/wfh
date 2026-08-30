import asyncio
import time
from typing import Any, Dict, List, Optional


class MicrostructureAnalyzer:
    def __init__(self, executable_notional: float = 50.0, snapshot_delay_seconds: float = 0.25):
        self.executable_notional = executable_notional
        self.snapshot_delay_seconds = max(0.0, float(snapshot_delay_seconds))
        self.snapshot_ttl_seconds = 5.0
        self.trade_ttl_seconds = 60.0

    @staticmethod
    def _vwap(levels: List[List[float]], notional: float, contract_size: float = 1.0) -> Optional[float]:
        remaining, quantity, value = notional, 0.0, 0.0
        for price, amount, *_ in levels:
            price, amount = float(price), float(amount)
            take = min(remaining, price * amount * contract_size)
            if take > 0:
                quantity += take / price
                value += take
                remaining -= take
            if remaining <= 0:
                break
        return value / quantity if remaining <= 0 and quantity else None

    @staticmethod
    def _depth(levels: List[List[float]], contract_size: float = 1.0) -> float:
        return sum(float(price) * float(amount) * contract_size for price, amount, *_ in levels)

    @staticmethod
    def _change_pct(current: float, previous: float) -> float | None:
        if previous <= 0:
            return None
        return (current - previous) / previous * 100.0

    async def analyze(self, exchange: Any, symbol: str, first: Dict[str, Any], market: Dict[str, Any]) -> Dict[str, Any]:
        if not first:
            return {"approved": False, "reason": "missing live orderbook"}
        try:
            contract_size = float(market.get("contractSize"))
        except (TypeError, ValueError):
            return {"approved": False, "reason": "invalid exchange filters: contract size unavailable"}
        if contract_size <= 0:
            return {"approved": False, "reason": "invalid exchange filters: contract size unavailable"}
        first.setdefault("_received_at", time.time())
        snapshots = [first]
        trades_task = asyncio.create_task(exchange.fetch_trades(symbol, limit=100))
        try:
            for _ in range(2):
                await asyncio.sleep(self.snapshot_delay_seconds)
                snapshot = await exchange.fetch_order_book(symbol, limit=20)
                snapshot["_received_at"] = time.time()
                snapshots.append(snapshot)
            trades = await trades_task
        except asyncio.CancelledError:
            trades_task.cancel()
            await asyncio.gather(trades_task, return_exceptions=True)
            raise
        except Exception:
            if not trades_task.done():
                trades_task.cancel()
            await asyncio.gather(trades_task, return_exceptions=True)
            return {"approved": False, "reason": "missing live orderbook snapshots or trades"}
        if any(not item.get("bids") or not item.get("asks") for item in snapshots):
            return {"approved": False, "reason": "empty live orderbook"}
        now_ms = int(time.time() * 1000)
        for snapshot in snapshots:
            timestamp = snapshot.get("timestamp")
            received_at = snapshot.get("_received_at")
            if isinstance(timestamp, (int, float)):
                if timestamp <= 0 or now_ms - int(timestamp) > int(self.snapshot_ttl_seconds * 1000):
                    return {"approved": False, "reason": "stale orderbook snapshot"}
            elif not isinstance(received_at, (int, float)) or time.time() - received_at > self.snapshot_ttl_seconds:
                return {"approved": False, "reason": "orderbook receipt timestamp unavailable"}
        trades = [
            trade for trade in trades
            if isinstance(trade.get("timestamp"), (int, float))
            and trade["timestamp"] > 0
            and now_ms - int(trade["timestamp"]) <= int(self.trade_ttl_seconds * 1000)
        ]
        if len(trades) < 20:
            return {"approved": False, "reason": "insufficient fresh trades"}
        source_trades = [
            {
                key: trade.get(key)
                for key in (
                    "id", "timestamp", "datetime", "symbol",
                    "side", "price", "amount", "cost", "takerOrMaker",
                )
                if key in trade
            }
            for trade in trades[:100]
        ]
        source_orderbook_snapshots = [
            {
                "timestamp": snapshot.get("timestamp"),
                "received_at": snapshot.get("_received_at"),
                "bids": [list(level[:3]) for level in (snapshot.get("bids") or [])],
                "asks": [list(level[:3]) for level in (snapshot.get("asks") or [])],
            }
            for snapshot in snapshots
        ]
        source_market = {
            "contractSize": market.get("contractSize"),
            "limits": market.get("limits"),
            "precision": market.get("precision"),
        }
        bids, asks = snapshots[-1]["bids"], snapshots[-1]["asks"]
        observed_at = float(snapshots[-1]["_received_at"])
        best_bid, best_ask = float(bids[0][0]), float(asks[0][0])
        if best_bid <= 0 or best_ask <= best_bid:
            return {"approved": False, "reason": "invalid spread"}
        sell_vwap = self._vwap(bids, self.executable_notional, contract_size)
        buy_vwap = self._vwap(asks, self.executable_notional, contract_size)
        bid_depth, ask_depth = self._depth(bids, contract_size), self._depth(asks, contract_size)
        initial_bid_depth = self._depth(snapshots[0]["bids"], contract_size)
        initial_ask_depth = self._depth(snapshots[0]["asks"], contract_size)
        churn = sum(
            abs(self._depth(item["bids"], contract_size) - initial_bid_depth)
            for item in snapshots[1:]
        ) / max(bid_depth, 1.0)
        spoofing = churn > 1.5
        sell_flow = sum(float(t.get("amount", 0)) * float(t.get("price", 0)) * contract_size for t in trades if t.get("side") == "sell")
        buy_flow = sum(float(t.get("amount", 0)) * float(t.get("price", 0)) * contract_size for t in trades if t.get("side") == "buy")
        flow_total = sell_flow + buy_flow
        sell_flow_ratio = sell_flow / flow_total if flow_total > 0 else None
        sell_by_price: Dict[float, float] = {}
        buy_by_price: Dict[float, float] = {}
        for trade in trades:
            try:
                price = float(trade.get("price"))
                notional = price * float(trade.get("amount")) * contract_size
            except (TypeError, ValueError):
                continue
            bucket = sell_by_price if trade.get("side") == "sell" else buy_by_price if trade.get("side") == "buy" else None
            if bucket is not None and price > 0 and notional > 0:
                bucket[price] = bucket.get(price, 0.0) + notional
        sell_imbalances = sum(value >= 2.0 * buy_by_price.get(price, 0.0) and value > 0 for price, value in sell_by_price.items())
        footprint_available = len(trades) >= 20 and flow_total > 0
        spread_pct = (best_ask - best_bid) / best_ask * 100
        entry_slippage_pct = (best_bid - sell_vwap) / best_bid * 100 if sell_vwap is not None else None
        exit_slippage_pct = (buy_vwap - best_ask) / best_ask * 100 if buy_vwap is not None else None
        limits = market.get("limits", {})
        try:
            min_amount = float(limits.get("amount", {}).get("min"))
        except (TypeError, ValueError):
            min_amount = None
        try:
            explicit_min_cost = float(limits.get("cost", {}).get("min"))
        except (TypeError, ValueError):
            explicit_min_cost = None
        if min_amount is None or min_amount <= 0:
            return {"approved": False, "reason": "invalid exchange filters: minimum amount unavailable"}
        minimum_notional = max(explicit_min_cost or 0.0, min_amount * contract_size * best_bid)
        contracts = self.executable_notional / (sell_vwap * contract_size) if sell_vwap is not None else None
        executable = bool(
            contracts is not None and buy_vwap is not None
            and self.executable_notional >= minimum_notional and contracts >= min_amount
        )
        approved = bool(
            executable and not spoofing and sell_flow > buy_flow and spread_pct <= 0.5
            and entry_slippage_pct is not None and entry_slippage_pct <= 0.3
            and exit_slippage_pct is not None and exit_slippage_pct <= 0.3
        )
        reason = (
            "insufficient executable bid depth" if sell_vwap is None
            else "insufficient executable ask depth" if buy_vwap is None
            else None
        )
        bid_change = self._change_pct(bid_depth, initial_bid_depth)
        ask_change = self._change_pct(ask_depth, initial_ask_depth)
        return {
            "approved": approved,
            "reason": reason,
            "observed_at": observed_at,
            "spread_pct": round(spread_pct, 4),
            "best_bid": best_bid,
            "best_ask": best_ask,
            "sell_vwap": sell_vwap,
            "buy_vwap": buy_vwap,
            "slippage_pct": round(entry_slippage_pct, 4) if entry_slippage_pct is not None else None,
            "entry_slippage_pct": round(entry_slippage_pct, 4) if entry_slippage_pct is not None else None,
            "exit_slippage_pct": round(exit_slippage_pct, 4) if exit_slippage_pct is not None else None,
            "round_trip_slippage_pct": round(entry_slippage_pct + exit_slippage_pct, 4)
            if entry_slippage_pct is not None and exit_slippage_pct is not None else None,
            "bid_depth_usdt": bid_depth,
            "ask_depth_usdt": ask_depth,
            "sell_flow_usdt": sell_flow,
            "buy_flow_usdt": buy_flow,
            "churn": round(churn, 4),
            "sell_flow_ratio": round(sell_flow_ratio, 4) if sell_flow_ratio is not None else None,
            "footprint": {
                "available": footprint_available,
                "trade_count": len(trades),
                "sell_delta_usdt": round(sell_flow - buy_flow, 4),
                "sell_imbalance_levels": sell_imbalances,
                "aggressive_selling": bool(footprint_available and sell_flow > buy_flow and sell_imbalances > 0),
            },
            "spoofing_detected": spoofing,
            "executable_notional": self.executable_notional,
            "executable": executable,
            "minimum_notional": minimum_notional,
            "contracts": contracts,
            "exchange_filters": {
                "precision": market.get("precision"),
                "minimum_amount": min_amount,
                "contract_size": contract_size,
            },
            "precrash_observations": {
                "contract_version": "precrash_orderbook_observation_v1",
                "observational_only": True,
                "hard_gating_allowed": False,
                "promotion_allowed": False,
                "bid_depth_change_pct": round(bid_change, 4) if bid_change is not None else None,
                "ask_depth_change_pct": round(ask_change, 4) if ask_change is not None else None,
                "depth_churn_ratio": round(churn, 4),
            },
            "source_capture": {
                "fresh_trades": source_trades,
                "raw_trades_captured": len(source_trades) >= 20,
                "trade_ttl_seconds": self.trade_ttl_seconds,
                "orderbook_snapshots": source_orderbook_snapshots,
                "orderbook_snapshots_captured": bool(
                    len(source_orderbook_snapshots) == 3
                    and all(item.get("bids") and item.get("asks") for item in source_orderbook_snapshots)
                ),
                "market": source_market,
                "market_filters_captured": bool(
                    source_market.get("contractSize") is not None
                    and isinstance(source_market.get("limits"), dict)
                ),
            },
        }
