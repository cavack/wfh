import logging
import httpx
import json
import re
from typing import Tuple, Dict, Any

from waterfallhunter.config import settings

logger = logging.getLogger("WaterfallHunter.AIVeto")

class AIVetoEngine:
    def __init__(self, *args, **kwargs):
        self.api_key = settings.gemini_api_key
        self.model = settings.gemini_model
        self.ollama_url = settings.ollama_url.rstrip("/")
        self.ollama_model = settings.ollama_model
        # قانون قطعی و ریاضی (Deterministic Hard Veto):
        # تنها عاملی که حق دارد معامله را وتو و لغو کند.
        self.max_bid_ask_ratio = 3.0

        if not self.api_key:
            logger.warning("⚠️ GEMINI_API_KEY is missing. AI advisory will be bypassed, deterministic math logic will proceed.")

    async def _get_gemini_opinion(self, symbol: str, orderbook: Dict, ticker: Dict) -> Dict[str, Any]:
        """ارتباط واقعی با موتور Gemini برای اخذ نظر مشورتی (Advisory) با روش Auth Key جدید"""
        if not self.api_key:
            return {"advice": "NEUTRAL", "confidence": 0, "reasoning": "Missing Gemini API Key.", "provider": "none"}

        try:
            bids = orderbook.get('bids', [])[:10]
            asks = orderbook.get('asks', [])[:10]
            bid_vol = sum(b[1] for b in bids) if bids else 0
            ask_vol = sum(a[1] for a in asks) if asks else 0
            last_price = ticker.get('last', 0)

            prompt = f"""
            You are an elite quantitative crypto trading AI. Analyze {symbol} for a SHORT position.
            Real-time Market Data:
            - Last Price: {last_price}
            - Top 10 Bids Volume: {bid_vol}
            - Top 10 Asks Volume: {ask_vol}

            Respond strictly in JSON format without any markdown wrappers.
            You MUST return exactly this structure:
            {{"advice": "SHORT" or "NEUTRAL" or "AVOID", "confidence": <number 0-100>, "reasoning": "<short precise explanation>"}}
            """

            # استفاده از URL تمیز بدون پارامتر ?key=
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

            # احراز هویت طبق مستندات جدید از طریق هدر اختصاصی گوگل
            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key
            }

            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "response_mime_type": "application/json"
                }
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, headers=headers, timeout=15.0)

                if response.status_code == 200:
                    data = response.json()
                    result_text = data['candidates'][0]['content']['parts'][0]['text']

                    # پاک‌سازی markdown در صورتی که Gemini تگ‌های ```json ارسال کند
                    result_text = re.sub(r'^```json', '', result_text).strip()
                    result_text = re.sub(r'```$', '', result_text).strip()

                    parsed = json.loads(result_text)
                    return {
                        "advice": parsed.get("advice", "UNKNOWN"),
                        "confidence": int(parsed.get("confidence", 0)),
                        "reasoning": parsed.get("reasoning", "No exact reasoning provided."),
                        "provider": "gemini",
                    }
                else:
                    logger.error(
                        "Gemini API error for model %s (HTTP %s): %s",
                        self.model,
                        response.status_code,
                        response.text,
                    )
                    if response.status_code == 404:
                        reason = (
                            f"Model '{self.model}' is unavailable to the configured Gemini API project. "
                            "Check GEMINI_API_KEY access or set GEMINI_MODEL to a model returned by models.list."
                        )
                    else:
                        reason = f"Gemini API HTTP error {response.status_code}"
                    return await self._get_ollama_opinion(symbol, orderbook, ticker, reason)

        except Exception as e:
            logger.error(f"Gemini request failed/timeout: {e}")
            # Fail-Safe: در صورت تایم‌اوت یا خطای شبکه، سیستم کرش نمی‌کند
            return await self._get_ollama_opinion(symbol, orderbook, ticker, "Gemini connection failed or timed out")

    async def _get_ollama_opinion(self, symbol: str, orderbook: Dict, ticker: Dict, gemini_reason: str) -> Dict[str, Any]:
        bids, asks = orderbook.get("bids", [])[:10], orderbook.get("asks", [])[:10]
        prompt = (f"Analyze {symbol} short setup using only this live data. last={ticker.get('last')}; "
                  f"bid_volume={sum(row[1] for row in bids)}; ask_volume={sum(row[1] for row in asks)}. "
                  'Return JSON: {"advice":"SHORT|NEUTRAL|AVOID","confidence":0-100,"reasoning":"short"}.')
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(f"{self.ollama_url}/api/generate", json={"model": self.ollama_model, "prompt": prompt, "stream": False, "format": "json"})
                response.raise_for_status()
                result = json.loads(response.json()["response"])
                return {"advice": result.get("advice", "NEUTRAL"), "confidence": int(result.get("confidence", 0)),
                        "reasoning": result.get("reasoning", "Ollama advisory"), "provider": "ollama", "gemini_error": gemini_reason}
        except Exception as exc:
            return {"advice": "UNAVAILABLE", "confidence": 0, "reasoning": f"Gemini unavailable; Ollama unavailable ({type(exc).__name__})", "provider": "none"}

    async def evaluate_symbol(self, symbol: str, orderbook: Dict, ticker: Dict) -> Tuple[bool, Dict[str, Any]]:
        """
        ارزیابی نهایی:
        ۱. ارزیابی قطعی (Deterministic) -> خروجی Boolean برای وتو کردن
        ۲. نظر مشورتی (Gemini) -> فقط برای ثبت در لاگ، داشبورد و تلگرام
        """
        if not orderbook or not ticker:
            logger.warning(f"🛡️ HARD VETO [{symbol}]: Missing real market data.")
            return True, {
                "deterministic_reason": "Missing real data",
                "ai_advice": "ERROR", "ai_confidence": 0, "ai_reasoning": "Insufficient data"
            }

        bids = orderbook.get('bids', [])[:10]
        asks = orderbook.get('asks', [])[:10]
        bid_vol = sum(b[1] for b in bids) if bids else 0
        ask_vol = sum(a[1] for a in asks) if asks else 0

        # --- قانون وتوی قطعی (Deterministic Logic) ---
        deterministic_veto = False
        veto_reason = "Approved by Deterministic Math"

        if ask_vol == 0:
            deterministic_veto = True
            veto_reason = "No Ask liquidity available."
        elif (bid_vol / ask_vol) > self.max_bid_ask_ratio:
            deterministic_veto = True
            veto_reason = f"Bid wall is {(bid_vol/ask_vol):.1f}x larger than Ask wall. Long Squeeze risk."

        # --- اخذ نظر مشورتی و اجباری از Gemini ---
        ai_opinion = await self._get_gemini_opinion(symbol, orderbook, ticker)

        advisory_data = {
            "deterministic_veto": deterministic_veto,
            "deterministic_reason": veto_reason,
            "ai_advice": ai_opinion.get("advice", "UNKNOWN"),
            "ai_confidence": ai_opinion.get("confidence", 0),
            "ai_reasoning": ai_opinion.get("reasoning", "None"),
            "ai_provider": ai_opinion.get("provider", "none"),
        }
        if ai_opinion.get("gemini_error"):
            advisory_data["gemini_error"] = ai_opinion["gemini_error"]

        # ثبت لاگ دقیق
        if deterministic_veto:
            logger.warning(f"🛡️ HARD VETO APPLIED for {symbol}: {veto_reason}")

        logger.info(f"🧠 Gemini Advisory [{symbol}]: {advisory_data['ai_advice']} (Conf: {advisory_data['ai_confidence']}%) | Reason: {advisory_data['ai_reasoning']}")

        return deterministic_veto, advisory_data
