import json
import logging
import re
from typing import Any, Dict, Tuple

import httpx

from waterfallhunter.config import settings

logger = logging.getLogger("WaterfallHunter.AIVeto")


class AIVetoEngine:
    """Deterministic veto plus optional Gemini advisory.

    Deterministic market-data checks may participate in the critical decision
    path. Gemini output is observational only and must not be required before
    signal persistence. There is no local-model fallback.
    """

    def __init__(self, *args, **kwargs):
        self.api_key = settings.gemini_api_key
        self.model = settings.gemini_model
        self.max_bid_ask_ratio = 3.0

        if not self.api_key:
            logger.warning(
                "GEMINI_API_KEY is missing. AI advisory will be bypassed; "
                "deterministic logic will continue."
            )

    @staticmethod
    def _unavailable_advisory(reason: str) -> Dict[str, Any]:
        return {
            "advice": "UNAVAILABLE",
            "confidence": 0,
            "reasoning": reason,
            "provider": "none",
        }

    async def _get_gemini_opinion(
        self,
        symbol: str,
        orderbook: Dict,
        ticker: Dict,
    ) -> Dict[str, Any]:
        if not self.api_key:
            return self._unavailable_advisory("Missing Gemini API key.")

        try:
            bids = orderbook.get("bids", [])[:10]
            asks = orderbook.get("asks", [])[:10]
            bid_vol = sum(row[1] for row in bids) if bids else 0
            ask_vol = sum(row[1] for row in asks) if asks else 0
            last_price = ticker.get("last", 0)

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

            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.model}:generateContent"
            )
            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            }
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "response_mime_type": "application/json",
                },
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=15.0,
                )

            if response.status_code != 200:
                logger.error(
                    "Gemini API error for model %s (HTTP %s): %s",
                    self.model,
                    response.status_code,
                    response.text,
                )
                if response.status_code == 404:
                    reason = (
                        f"Gemini model '{self.model}' is unavailable to the "
                        "configured API project."
                    )
                else:
                    reason = f"Gemini API HTTP error {response.status_code}."
                return self._unavailable_advisory(reason)

            data = response.json()
            result_text = data["candidates"][0]["content"]["parts"][0]["text"]
            result_text = re.sub(r"^```json", "", result_text).strip()
            result_text = re.sub(r"```$", "", result_text).strip()
            parsed = json.loads(result_text)

            return {
                "advice": parsed.get("advice", "UNKNOWN"),
                "confidence": int(parsed.get("confidence", 0)),
                "reasoning": parsed.get("reasoning", "No reasoning provided."),
                "provider": "gemini",
            }
        except Exception as exc:
            logger.error("Gemini request failed: %s", exc)
            return self._unavailable_advisory(
                f"Gemini unavailable ({type(exc).__name__})."
            )

    def evaluate_deterministic(
        self,
        symbol: str,
        orderbook: Dict,
        ticker: Dict,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Return provider-free veto state plus observational-AI placeholder."""

        if not orderbook or not ticker:
            logger.warning("HARD VETO [%s]: Missing real market data.", symbol)
            return True, {
                "deterministic_veto": True,
                "deterministic_reason": "Missing real data",
                "ai_advice": "ERROR",
                "ai_confidence": 0,
                "ai_reasoning": "Insufficient data",
                "ai_provider": "none",
                "ai_observational_only": True,
                "ai_decision_critical": False,
            }

        bids = orderbook.get("bids", [])[:10]
        asks = orderbook.get("asks", [])[:10]
        bid_vol = sum(row[1] for row in bids) if bids else 0
        ask_vol = sum(row[1] for row in asks) if asks else 0

        deterministic_veto = False
        veto_reason = "Approved by Deterministic Math"

        if ask_vol == 0:
            deterministic_veto = True
            veto_reason = "No Ask liquidity available."
        elif (bid_vol / ask_vol) > self.max_bid_ask_ratio:
            deterministic_veto = True
            veto_reason = (
                f"Bid wall is {(bid_vol / ask_vol):.1f}x larger than Ask wall. "
                "Long squeeze risk."
            )

        if deterministic_veto:
            logger.warning("HARD VETO APPLIED for %s: %s", symbol, veto_reason)

        if self.api_key:
            ai_advice = "PENDING"
            ai_reasoning = (
                "Gemini advisory runs asynchronously after immutable trigger "
                "persistence and is not decision-critical."
            )
        else:
            ai_advice = "UNAVAILABLE"
            ai_reasoning = "Missing Gemini API key."

        return deterministic_veto, {
            "deterministic_veto": deterministic_veto,
            "deterministic_reason": veto_reason,
            "ai_advice": ai_advice,
            "ai_confidence": 0,
            "ai_reasoning": ai_reasoning,
            "ai_provider": "none",
            "ai_observational_only": True,
            "ai_decision_critical": False,
        }

    async def get_observational_advisory(
        self,
        symbol: str,
        orderbook: Dict,
        ticker: Dict,
    ) -> Dict[str, Any]:
        """Fetch optional Gemini output without granting it veto authority."""

        opinion = await self._get_gemini_opinion(symbol, orderbook, ticker)
        advisory = {
            "ai_advice": opinion.get("advice", "UNKNOWN"),
            "ai_confidence": opinion.get("confidence", 0),
            "ai_reasoning": opinion.get("reasoning", "None"),
            "ai_provider": opinion.get("provider", "none"),
            "ai_observational_only": True,
            "ai_decision_critical": False,
        }
        logger.info(
            "Gemini Advisory [%s]: %s (Conf: %s%%) | Reason: %s",
            symbol,
            advisory["ai_advice"],
            advisory["ai_confidence"],
            advisory["ai_reasoning"],
        )
        return advisory

    async def evaluate_symbol(
        self,
        symbol: str,
        orderbook: Dict,
        ticker: Dict,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Compatibility API for non-critical callers that want full advisory."""

        deterministic_veto, advisory_data = self.evaluate_deterministic(
            symbol,
            orderbook,
            ticker,
        )
        if not orderbook or not ticker:
            return deterministic_veto, advisory_data

        advisory_data.update(
            await self.get_observational_advisory(
                symbol,
                orderbook,
                ticker,
            )
        )
        return deterministic_veto, advisory_data
