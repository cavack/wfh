import httpx
import logging
import json
from typing import Optional
from waterfallhunter.core.models import SignalScore, OrderBook

logger = logging.getLogger("WaterfallHunter.AI")

class SignalAnalyzer:
    def __init__(self, ollama_url: str = "http://localhost:11434"):
        self.ollama_url = ollama_url
        self.model_name = "gemma" 

    def _build_prompt(self, symbol: str, orderbook: OrderBook) -> str:
        bids_summary = sum([b[1] for b in orderbook.bids[:10]])
        asks_summary = sum([a[1] for a in orderbook.asks[:10]])
        
        return f"""
        Analyze the shorting potential for {symbol} based on orderbook dynamics.
        Top 10 Bids Volume: {bids_summary}
        Top 10 Asks Volume: {asks_summary}
        
        If Ask volume is significantly higher than Bid volume, it indicates a strong sell wall.
        Respond ONLY with a JSON object in this exact format, with no extra text or markdown:
        {{"action": "SHORT", "confidence_score": 0.8, "reasoning": "short explanation"}}
        If the logic is neutral, use "NEUTRAL" for action.
        """

    async def analyze_short_opportunity(self, symbol: str, orderbook: OrderBook) -> Optional[SignalScore]:
        prompt = self._build_prompt(symbol, orderbook)
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model_name,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json"
                    },
                    timeout=120.0  # افزایش تایم‌اوت به 15 ثانیه برای مدل‌های سنگین‌تر
                )
                response.raise_for_status()
                data = response.json()
                
                # پاک‌سازی خروجی مدل (گاهی مدل‌ها خروجی را در تگ مارک‌داون می‌گذارند)
                raw_response = data["response"].strip()
                if raw_response.startswith("```json"):
                    raw_response = raw_response[7:]
                if raw_response.endswith("```"):
                    raw_response = raw_response[:-3]
                    
                result_json = json.loads(raw_response.strip())
                
                score = SignalScore(
                    symbol=symbol,
                    action=result_json.get("action", "NEUTRAL"),
                    confidence_score=result_json.get("confidence_score", 0.0),
                    reasoning=result_json.get("reasoning", "No reasoning provided.")
                )
                
                if score.action == "SHORT" and score.confidence_score > 0.8:
                    logger.warning(f"High-confidence SHORT signal for {symbol}: {score.confidence_score}")
                    
                return score

        except Exception as e:
            logger.error(f"AI Analysis failed for {symbol}: {e}")
            return None
