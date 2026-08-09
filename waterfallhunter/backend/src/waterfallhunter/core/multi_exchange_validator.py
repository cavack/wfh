import logging
from typing import Dict, Any

from waterfallhunter.core.multi_exchange import MultiExchangeGateway
from waterfallhunter.core.candle_analyzer import MultiTimeframeAnalyzer
from waterfallhunter.core.position_calculator import PositionCalculator
from waterfallhunter.core.ws_streamer import WebSocketManager

logger = logging.getLogger("WaterfallHunter.Validator")

class MultiExchangeValidator:
    def __init__(self):
        # اتصال ماژول‌های مستقل به یکدیگر
        self.gateway = MultiExchangeGateway()
        self.ws_manager = WebSocketManager()
        self.candle_analyzer = MultiTimeframeAnalyzer()
        self.position_calculator = PositionCalculator()

    def calculate_pure_live_score(self, ticker: dict, reference_price: float, exchange_name: str) -> dict:
        """امتیازدهی قطعی بر اساس اختلاف قیمت و VWAP"""
        score = 0
        details = {"source_exchange": exchange_name}
        exchange_price = ticker.get('last')
        
        if not exchange_price or not reference_price:
            return {"score": 0, "suggested_status": "WATCH", "metrics": {"error": "Missing price data"}}

        # محاسبه Discount (اختلاف قیمت لایو با قیمت LBank)
        price_diff_pct = ((reference_price - exchange_price) / reference_price) * 100
        details['discount_pct'] = round(price_diff_pct, 2)
        
        if price_diff_pct >= 2.0: score += 40
        elif price_diff_pct >= 1.0: score += 25
        elif price_diff_pct >= 0.3: score += 10

        vwap = ticker.get('vwap')
        if vwap and exchange_price < vwap:
            score += 20
            details['vwap'] = vwap
        
        score = min(max(score, 0), 100)
        status = "TRIGGERED" if score >= 85 else "ARMED" if score >= 50 else "WATCH"
        details['total_score'] = score
        
        return {"score": score, "suggested_status": status, "metrics": details}

    async def cross_check_symbol(self, symbol: str, reference_price: float) -> Dict[str, Any]:
        """اجرای زنجیره اعتبارسنجی (Data -> Score -> Candles -> Position)"""
        
        # ۱. دریافت تیکر از آبشار صرافی‌ها (توقف در اولین موفقیت)
        wf_result = await self.gateway.fetch_ticker(symbol)
        if not wf_result:
            return {"is_valid": False, "score": 0, "suggested_status": "WATCH", "metrics": {}}
            
        ticker = wf_result["data"]
        ex_name = wf_result["exchange"]
        mapped_sym = wf_result["mapped_symbol"]
        ex_instance = wf_result["exchange_instance"]

        # ۲. امتیازدهی اولیه
        scoring = self.calculate_pure_live_score(ticker, reference_price, ex_name)
        base_score = scoring["score"]
        metrics = scoring["metrics"]
        
        # ۳. استخراج دفتر سفارشات (اولویت با کشِ WebSocket، در غیر این‌صورت REST Fallback)
        orderbook = self.ws_manager.get_realtime_orderbook(ex_name, mapped_sym)
        if not orderbook:
            ob_res = await self.gateway.fetch_order_book(symbol)
            if ob_res:
                orderbook = ob_res["data"]

        metrics["orderbook"] = orderbook
        metrics["ticker"] = ticker
        metrics["mapped_symbol"] = mapped_sym
        metrics["exchange"] = ex_name

        # ۴. تاییدیه کندل‌ها (فقط اگر ارز داغ شده باشد)
        if base_score >= 50:
            candle_results = await self.candle_analyzer.analyze_candles(ex_instance, mapped_sym)
            metrics["candle_analysis"] = candle_results.get("details", {})
            
            # اگر ۴ تایم فریم تایید کردند، امتیاز بوست می‌شود
            if candle_results.get("is_breakdown_confirmed"):
                base_score = min(base_score + 35, 100)
            else:
                # سقف امتیاز در صورت عدم تایید کندل‌ها ۴۹ است تا هرگز شلیک نشود
                base_score = min(base_score, 49) 
        
        status = "TRIGGERED" if base_score >= 85 else "ARMED" if base_score >= 50 else "WATCH"
        metrics["total_score"] = base_score

        # ۵. محاسبه قطعیِ پوزیشن و ریسک در لحظه شلیک
        if status == "TRIGGERED" and orderbook and ticker:
            vwap_entry = ticker.get('vwap') or ticker.get('last')
            market_info = ex_instance.markets.get(mapped_sym, {})
            pos_setup = self.position_calculator.calculate_short_position(vwap_entry, market_info=market_info)
            metrics["position_setup"] = pos_setup
            
            # وتوی ماشین حساب: اگر ریسک نامعتبر یا حجم نامناسب باشد، معامله لغو می‌شود
            if pos_setup.get("status", "").startswith("REJECTED"):
                status = "WATCH" 
                base_score = 45

        return {
            "is_valid": True,
            "score": base_score,
            "suggested_status": status,
            "metrics": metrics
        }

    async def close_all(self):
        await self.ws_manager.close_all()
        await self.gateway.close_all()
