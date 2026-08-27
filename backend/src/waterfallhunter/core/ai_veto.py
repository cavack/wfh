import asyncio
import json
import logging
import re
from typing import Any, Dict, Tuple

import httpx

from waterfallhunter.config import settings

logger = logging.getLogger("WaterfallHunter.AIVeto")


class AIVetoEngine:
    """Deterministic veto plus optional Gemini advisory.

    AI output is observational only. If Gemini is unavailable, deterministic
    logic continues and the advisory is reported as unavailable; there is no
    local-model fallback.
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

    @staticmethod
    def _canonical_prompt(symbol: str, metrics: Dict[str, Any], decision: Dict[str, Any]) -> str:
        derivatives = metrics.get("derivatives") if isinstance(metrics.get("derivatives"), dict) else {}
        micro = metrics.get("microstructure") if isinstance(metrics.get("microstructure"), dict) else {}
        cascade = metrics.get("cascade_intelligence") if isinstance(metrics.get("cascade_intelligence"), dict) else {}
        breakdown = metrics.get("breakdown_confirmation") if isinstance(metrics.get("breakdown_confirmation"), dict) else {}
        return (
            "You are a crypto waterfall SHORT advisory model. You are advisory only and must not change the deterministic decision.\n"
            f"Symbol: {symbol}\n"
            f"Canonical decision: {decision.get('decision')}\n"
            f"Entry readiness: {decision.get('entry_readiness')}\n"
            f"Open interest 1h: {derivatives.get('oi_change_1h_pct')}%\n"
            f"Funding: {derivatives.get('funding_rate')}\n"
            f"Funding percentile: {derivatives.get('funding_percentile')}\n"
            f"Taker buy/sell: {derivatives.get('taker_buy_sell_ratio')}\n"
            f"Top trader long/short: {derivatives.get('top_trader_long_short_ratio')}\n"
            f"Sell flow: {micro.get('sell_flow_usdt')} USD\n"
            f"Buy flow: {micro.get('buy_flow_usdt')} USD\n"
            f"Spread: {micro.get('spread_pct')}%\n"
            f"Slippage: {micro.get('slippage_pct')}%\n"
            f"Cascade: {cascade.get('status')} {cascade.get('readiness_points')}/10\n"
            f"Cross-exchange: {breakdown.get('confirmation_exchange_15m')}\n"
            "Return strict JSON: {\"advice\":\"SHORT|NEUTRAL|AVOID\",\"confidence\":0-100,\"reasoning\":\"brief evidence-based reason\"}."
        )

    async def _request_canonical_advisory(self, prompt: str) -> Dict[str, Any]:
        if not self.api_key:
            return self._unavailable_advisory("Missing Gemini API key.")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "response_mime_type": "application/json"},
        }
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            return self._unavailable_advisory(f"Gemini API HTTP error {response.status_code}.")
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        text = re.sub(r"^```json", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
        parsed = json.loads(text)
        return {
            "advice": str(parsed.get("advice", "UNKNOWN")),
            "confidence": int(parsed.get("confidence", 0)),
            "reasoning": str(parsed.get("reasoning", "No reasoning provided.")),
            "provider": "gemini",
        }

    async def advisory_for_decision(
        self, symbol: str, metrics: Dict[str, Any], decision: Dict[str, Any]
    ) -> Dict[str, Any]:
        prompt = self._canonical_prompt(symbol, metrics, decision)
        try:
            opinion = await asyncio.wait_for(self._request_canonical_advisory(prompt), timeout=8.0)
        except Exception as exc:
            logger.warning("Canonical AI advisory unavailable for %s: %s", symbol, type(exc).__name__)
            opinion = self._unavailable_advisory(f"Gemini unavailable ({type(exc).__name__}).")
        return {
            "observational_only": True,
            "decision_mutated": False,
            "ai_advice": opinion.get("advice", "UNAVAILABLE"),
            "ai_confidence": opinion.get("confidence", 0),
            "ai_reasoning": opinion.get("reasoning", "No advisory available"),
            "ai_provider": opinion.get("provider", "none"),
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

    async def evaluate_symbol(
        self,
        symbol: str,
        orderbook: Dict,
        ticker: Dict,
    ) -> Tuple[bool, Dict[str, Any]]:
        if not orderbook or not ticker:
            logger.warning("HARD VETO [%s]: Missing real market data.", symbol)
            return True, {
                "deterministic_reason": "Missing real data",
                "ai_advice": "ERROR",
                "ai_confidence": 0,
                "ai_reasoning": "Insufficient data",
                "ai_provider": "none",
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

        # The advisory is informational only and must never gate or delay the
        # deterministic veto decision; run it off the critical path.
        try:
            ai_opinion = await asyncio.wait_for(
                self._get_gemini_opinion(symbol, orderbook, ticker),
                timeout=8.0,
            )
        except Exception:
            ai_opinion = self._unavailable_advisory("Gemini advisory timed out.")
        advisory_data = {
            "deterministic_veto": deterministic_veto,
            "deterministic_reason": veto_reason,
            "ai_advice": ai_opinion.get("advice", "UNKNOWN"),
            "ai_confidence": ai_opinion.get("confidence", 0),
            "ai_reasoning": ai_opinion.get("reasoning", "None"),
            "ai_provider": ai_opinion.get("provider", "none"),
        }

        if deterministic_veto:
            logger.warning("HARD VETO APPLIED for %s: %s", symbol, veto_reason)

        logger.info(
            "Gemini Advisory [%s]: %s (Conf: %s%%) | Reason: %s",
            symbol,
            advisory_data["ai_advice"],
            advisory_data["ai_confidence"],
            advisory_data["ai_reasoning"],
        )
        return deterministic_veto, advisory_data
