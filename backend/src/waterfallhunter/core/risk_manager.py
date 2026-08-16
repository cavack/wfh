import logging
from typing import Dict, Any, Tuple

logger = logging.getLogger("WaterfallHunter.RiskManager")

def get_leverage(symbol: str) -> int:
    base = symbol.split("/")[0].upper()
    return 2 if base in {"BTC", "ETH"} else 3

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
