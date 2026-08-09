import logging
import httpx
import json
import os
from typing import Tuple, Dict, Any

logger = logging.getLogger("WaterfallHunter.AIVeto")

class AIVetoEngine:
    def __init__(self, *args, **kwargs):
        # دریافت کلید از فایل .env
        self.api_key = os.getenv("GEMINI_API_KEY")
        # قانون محافظه‌کارانه و قطعی (Deterministic Hard Veto)
        self.max_bid_ask_ratio = 3.0 
        
        if not self.api_key:
            logger.warning("GEMINI_API_KEY is not set. AI Veto will fall back to Deterministic Math only.")

    async def _get_gemini_opinion(self, symbol: str, orderbook: Dict, ticker: Dict) -> Dict[str, Any]:
        """درخواست نظر مشورتی از موتور فوق‌سریع Gemini"""
        if not self.api_key:
            return {"advice": "NEUTRAL", "confidence": 0, "reasoning": "No API Key provided"}

        try:
            bids = orderbook.get('bids', [])[:10]
            asks = orderbook.get('asks', [])[:10]
            bid_vol = sum(b[1] for b in bids) if bids else 0
            ask_vol = sum(a[1] for a in asks) if asks else 0
            last_price = ticker.get('last', 0)

            prompt = f"""
            You are an elite quantitative crypto trading AI. Analyze {symbol} for a SHORT position.
            Real-time Data:
            - Last Price: {last_price}
            - Top 10 Bids Volume: {bid_vol}
            - Top 10 Asks Volume: {ask_vol}
            
            Respond strictly in JSON format without markdown blocks.
            Format: {{"advice": "SHORT" | "NEUTRAL" | "AVOID", "confidence": 0-100, "reasoning": "brief reason"}}
            """
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={self.api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "response_mime_type": "application/json"
                }
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=15.0)
                
                if response.status_code == 200:
                    data = response.json()
                    result_text = data['candidates'][0]['content']['parts'][0]['text']
                    return json.loads(result_text)
                else:
                    logger.error(f"Gemini API returned error: {response.text}")
                    return {"advice": "ERROR", "confidence": 0, "reasoning": "Gemini API Error"}
                    
        except Exception as e:
            logger.error(f"Gemini request failed/timeout: {e}")
            return {"advice": "TIMEOUT", "confidence": 0, "reasoning": "Gemini unreachable"}

    async def evaluate_symbol(self, symbol: str, orderbook: Dict, ticker: Dict) -> Tuple[bool, Dict[str, Any]]:
        """ارزیابی نهایی: قطعی + مشورت هوش مصنوعی"""
        if not orderbook or not ticker:
            logger.warning(f"🛡️ HARD VETO [{symbol}]: Missing real market data.")
            return True, {"deterministic_reason": "Missing real data", "ai_advice": "ERROR"}

        bids = orderbook.get('bids', [])[:10]
        asks = orderbook.get('asks', [])[:10]
        bid_vol = sum(b[1] for b in bids) if bids else 0
        ask_vol = sum(a[1] for a in asks) if asks else 0
        
        deterministic_veto = False
        veto_reason = "Approved by Deterministic Math"
        
        if ask_vol > 0 and (bid_vol / ask_vol) > self.max_bid_ask_ratio:
            deterministic_veto = True
            veto_reason = f"Bid wall is {(bid_vol/ask_vol):.1f}x larger than Ask wall. Long Squeeze risk."
        elif ask_vol == 0:
            deterministic_veto = True
            veto_reason = "No Ask liquidity available."

        # اخذ نظر مشورتی از Gemini
        ai_opinion = await self._get_gemini_opinion(symbol, orderbook, ticker)
        
        advisory_data = {
            "deterministic_veto": deterministic_veto,
            "deterministic_reason": veto_reason,
            "ai_advice": ai_opinion.get("advice", "UNKNOWN"),
            "ai_confidence": ai_opinion.get("confidence", 0),
            "ai_reasoning": ai_opinion.get("reasoning", "No valid response")
        }

        if deterministic_veto:
            logger.warning(f"🛡️ HARD VETO APPLIED for {symbol}: {veto_reason}")
        else:
            logger.info(f"🧠 Gemini Advisory for {symbol}: {ai_opinion.get('advice')} (Conf: {ai_opinion.get('confidence')}%)")

        return deterministic_veto, advisory_data
