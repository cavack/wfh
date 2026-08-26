import logging
import math
from typing import Dict, Any, Tuple

logger = logging.getLogger("WaterfallHunter.RiskManager")

def get_leverage(symbol: str) -> int:
    """Legacy symbol-only leverage retained for deterministic replay compatibility."""
    base = symbol.split("/")[0].upper()
    return 2 if base in {"BTC", "ETH"} else 3


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def recommend_signal_leverage(
    metrics: Dict[str, Any],
    execution_suitability: Dict[str, Any] | None = None,
) -> int:
    """Return an evidence-bound PAPER_ONLY leverage recommendation from 4x to 18x.

    The recommendation is the minimum of independent score, structural-stop,
    volatility, execution-friction, and execution-suitability ceilings.  It is
    intentionally symbol-agnostic.  If any independent bound requires less
    than 4x, the signal is rejected instead of being unsafely clamped upward.
    """
    if not isinstance(metrics, dict):
        raise ValueError("signal metrics unavailable for leverage")

    score = _finite_number(metrics.get("score"))
    position = metrics.get("position_setup") if isinstance(metrics.get("position_setup"), dict) else {}
    entry = _finite_number(position.get("entry_price"))
    stop = _finite_number(position.get("stop_loss"))
    micro = metrics.get("microstructure") if isinstance(metrics.get("microstructure"), dict) else {}
    spread = _finite_number(micro.get("spread_pct"))
    slippage = _finite_number(micro.get("slippage_pct"))
    exit_slippage = _finite_number(micro.get("exit_slippage_pct"))

    if score is None or score < 85.0 or score > 100.0:
        raise ValueError("strict finite score required for leverage")
    if entry is None or stop is None or entry <= 0 or stop <= entry:
        raise ValueError("valid short entry and structural stop required for leverage")
    if spread is None or slippage is None or spread < 0 or slippage < 0:
        raise ValueError("finite execution friction required for leverage")

    features = metrics.get("candle_features") if isinstance(metrics.get("candle_features"), dict) else {}
    atr_values = []
    for timeframe in ("5m", "15m", "1h"):
        packet = features.get(timeframe) if isinstance(features.get(timeframe), dict) else {}
        value = _finite_number(packet.get("atr_pct"))
        if value is not None and value > 0:
            atr_values.append(value)
    if not atr_values:
        raise ValueError("finite ATR evidence required for leverage")

    stop_distance_pct = (stop - entry) / entry * 100.0
    atr_pct = max(atr_values)
    friction_pct = max(spread, slippage, exit_slippage or slippage)

    score_bound = math.floor(4.0 + ((score - 85.0) / 15.0) * 14.0)
    stop_bound = math.floor(36.0 / stop_distance_pct)
    volatility_bound = math.floor(18.0 / (1.0 + max(atr_pct - 0.5, 0.0) / 2.5))

    if friction_pct <= 0.05:
        execution_bound = 18
    elif friction_pct <= 0.10:
        execution_bound = 15
    elif friction_pct <= 0.15:
        execution_bound = 12
    elif friction_pct <= 0.22:
        execution_bound = 9
    elif friction_pct <= 0.30:
        execution_bound = 6
    else:
        execution_bound = 3

    suitability = execution_suitability if isinstance(execution_suitability, dict) else {}
    suitability_bound = {
        "SUITABLE": 18,
        "MARGINAL": 10,
        "UNKNOWN": 8,
        "POOR": 4,
    }.get(str(suitability.get("status") or "UNKNOWN").upper(), 8)

    constraints = (
        metrics.get("market_constraints")
        if isinstance(metrics.get("market_constraints"), dict)
        else {}
    )
    exchange_max = _finite_number(
        constraints.get("maximum_leverage", suitability.get("maximum_leverage"))
    )
    exchange_bound = math.floor(exchange_max) if exchange_max is not None and exchange_max > 0 else 18

    raw = min(18, score_bound, stop_bound, volatility_bound, execution_bound, suitability_bound, exchange_bound)
    if raw < 4:
        raise ValueError("independent risk bound requires leverage below 4x")
    return int(raw)

class LiquidityRiskManager:
    def __init__(self):
        # تنظیمات بر اساس مستندات Production
        self.notional_trade_size_usdt = 100.0  # حجم فرضی معامله برای محاسبه Slippage
        self.max_allowed_spread_pct = 0.5      # حداکثر اسپرد مجاز: نیم درصد
        self.max_allowed_slippage_pct = 0.3    # حداکثر لغزش قیمت برای ورود: ۰.۳ درصد

    def analyze_orderbook_liquidity(self, orderbook: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        بررسی اسپرد، محاسبه VWAP برای یک حجم خاص و تخمین لغزش قیمت (Slippage)
        برمی‌گرداند: (آیا تایید شد؟, جزئیات محاسبات)
        """
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        # اگر اوردربوک خالی باشد، رد می‌شود
        if not bids or not asks:
            return False, {"error": "Empty orderbook"}

        best_bid = bids[0][0]
        best_ask = asks[0][0]

        # 1. محاسبه Spread
        spread = best_ask - best_bid
        spread_pct = (spread / best_ask) * 100

        # اگر اسپرد از حد مجاز بیشتر بود، فوراً رد می‌شود
        if spread_pct > self.max_allowed_spread_pct:
            return False, {
                "rejected_reason": "high_spread",
                "spread_pct": round(spread_pct, 4)
            }

        # 2. محاسبه VWAP سمت Bid (چون ما می‌خواهیم SHORT کنیم، مارکت ما روی بیدها پر می‌شود)
        # هدف: فروختن حجم self.notional_trade_size_usdt به مارکت
        remaining_usdt_to_sell = self.notional_trade_size_usdt
        total_coins_sold = 0.0
        weighted_sum = 0.0

        for price, amount_coins in bids:
            if remaining_usdt_to_sell <= 0:
                break
                
            level_usdt_capacity = price * amount_coins
            
            if level_usdt_capacity >= remaining_usdt_to_sell:
                # این سطح می‌تواند تمام حجم باقی‌مانده ما را پر کند
                coins_to_sell_here = remaining_usdt_to_sell / price
                weighted_sum += price * coins_to_sell_here
                total_coins_sold += coins_to_sell_here
                remaining_usdt_to_sell = 0
            else:
                # این سطح تمام حجم را مصرف می‌کند اما هنوز باید پایین‌تر برویم
                weighted_sum += price * amount_coins
                total_coins_sold += amount_coins
                remaining_usdt_to_sell -= level_usdt_capacity

        # اگر تمام اوردربوک (۲۰ لول) را گشتیم و هنوز حجم ۱۰۰ دلار ما پر نشد:
        if remaining_usdt_to_sell > 0:
            return False, {"rejected_reason": "insufficient_liquidity", "spread_pct": round(spread_pct, 4)}

        # محاسبه نهایی میانگین قیمت (VWAP)
        vwap_execution_price = weighted_sum / total_coins_sold
        
        # 3. محاسبه لغزش (Slippage)
        # لغزش یعنی چقدر قیمت واقعیِ پر شدنِ ما، از بهترین قیمتِ روی تابلو (Best Bid) بدتر است
        slippage_pct = ((best_bid - vwap_execution_price) / best_bid) * 100

        is_approved = slippage_pct <= self.max_allowed_slippage_pct

        details = {
            "spread_pct": round(spread_pct, 4),
            "estimated_vwap": vwap_execution_price,
            "estimated_slippage_pct": round(slippage_pct, 4),
            "notional_size_usdt": self.notional_trade_size_usdt,
            "liquidity_approved": is_approved
        }
        
        if not is_approved:
            details["rejected_reason"] = "high_slippage"

        return is_approved, details
