import logging
import httpx
import asyncio
import math
import json
from html import escape
from waterfallhunter.config import settings
from waterfallhunter.core.notification_delivery import (
    DeliveryDisposition,
    DeliveryResult,
)

logger = logging.getLogger("WaterfallHunter.Telegram")

class TelegramNotifier:
    def __init__(self, db_adapter=None, scanner=None):
        self.token = settings.telegram_token
        self.chat_id = str(settings.telegram_chat_id) if settings.telegram_chat_id is not None else None
        self.enabled = bool(self.token and self.chat_id)
        self.db = db_adapter
        self.scanner = scanner
        self.offset = 0

    async def send_message(self, text: str):
        if not self.enabled:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"})
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

    async def send_signal_alert(self, symbol: str, data: dict):
        if not self.enabled:
            return

        await self.send_message(self.build_signal_message(symbol, data))

    @staticmethod
    def _number(value, digits: int = 4) -> str:
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return "—"
        return f"{value:.{digits}f}"

    @classmethod
    def build_signal_message(cls, symbol: str, data: dict) -> str:
        metrics = data.get("metrics") or {}
        pos_setup = metrics.get("position_setup") or {}
        ai_data = metrics.get("ai_advisory") or {}
        dex_context = metrics.get("dex_context") or {}
        onchain_context = metrics.get("onchain_context") or {}
        microstructure = metrics.get("microstructure") or {}
        base_symbol = escape(symbol.split('/')[0])
        leverage = cls._number(metrics.get("applied_leverage"), 0)
        ai_advice = escape(str(ai_data.get("ai_advice", "UNKNOWN")))
        ai_confidence = cls._number(ai_data.get("ai_confidence"), 0)
        ai_reason = escape(str(ai_data.get("ai_reasoning", "No advisory available")))

        lines = [
            "🚨 <b>WATERFALL SIGNAL — PAPER ALERT</b>",
            f"🪙 <b>Symbol:</b> #{base_symbol}",
            f"📊 <b>Score:</b> {cls._number(data.get('score'), 2)}/100",
            f"⚖️ <b>Recommended leverage:</b> {leverage}×",
            "",
            f"🧠 <b>AI advisory ({escape(str(ai_data.get('ai_provider', 'none')))}):</b>",
            f"├ <b>Advice:</b> {ai_advice} ({ai_confidence}%)",
            f"└ <i>{ai_reason}</i>",
            "",
            "<b>Risk-managed setup</b>",
            f"🎯 Entry: <b>${cls._number(pos_setup.get('entry_price'), 8)}</b>",
            f"🛑 Stop: <b>${cls._number(pos_setup.get('stop_loss'), 8)}</b> ({cls._number(pos_setup.get('risk_pct'), 2)}%)",
            f"💰 TP1 / TP2: <b>${cls._number(pos_setup.get('take_profit_1'), 8)}</b> / <b>${cls._number(pos_setup.get('take_profit_2'), 8)}</b>",
            f"📐 Reward:risk: <b>{cls._number(pos_setup.get('reward_to_risk'), 2)}</b>",
            f"📚 Spread / slippage: <b>{cls._number(microstructure.get('spread_pct'), 3)}%</b> / <b>{cls._number(microstructure.get('slippage_pct'), 3)}%</b>",
        ]
        if dex_context:
            lines.append(f"🔗 DEX: {escape(str(dex_context.get('chain_id', '—')))} · liquidity ${cls._number(dex_context.get('liquidity_usd'), 0)}")
        if onchain_context:
            lines.append(f"🐋 On-chain sample: {cls._number(onchain_context.get('large_transfer_sample_count'), 0)} large transfers · max ${cls._number(onchain_context.get('largest_transfer_usd'), 0)}")
        lines.extend(["", "<i>Triggered and logged. No live order is placed.</i>"])
        return "\n".join(lines)

    @classmethod
    def build_entry_ready_message(cls, payload: dict) -> str:
        symbol = escape(str(payload.get("symbol") or "UNKNOWN").split("/")[0])
        packet = payload.get("decision_packet") if isinstance(payload.get("decision_packet"), dict) else {}
        plan = packet.get("trade_plan") if isinstance(packet.get("trade_plan"), dict) else {}
        evidence = packet.get("evidence_summary") if isinstance(packet.get("evidence_summary"), dict) else {}
        derivatives = evidence.get("derivatives") if isinstance(evidence.get("derivatives"), dict) else {}
        flow = evidence.get("order_flow") if isinstance(evidence.get("order_flow"), dict) else {}
        cascade = evidence.get("cascade") if isinstance(evidence.get("cascade"), dict) else {}
        reasons = [escape(str(item)) for item in packet.get("reason_codes", [])][:6]
        lines = [
            "🌊 <b>WATERFALL SHORT — ENTRY READY</b>",
            f"🪙 <b>#{symbol}</b> · readiness <b>{cls._number(packet.get('entry_readiness'), 1)}/100</b>",
            f"📦 Evidence coverage: <b>{cls._number(packet.get('evidence_coverage_pct'), 1)}%</b>",
            "",
            f"🎯 Entry: <b>${cls._number(plan.get('entry_price'), 8)}</b>",
            f"🛑 SL: <b>${cls._number(plan.get('stop_loss'), 8)}</b>",
            f"💰 TP1 / TP2 / TP3: <b>${cls._number(plan.get('take_profit_1'), 8)}</b> / <b>${cls._number(plan.get('take_profit_2'), 8)}</b> / <b>${cls._number(plan.get('take_profit_3'), 8)}</b>",
            f"⚖️ Leverage: <b>{cls._number(plan.get('leverage'), 0)}×</b>",
            "",
            f"📉 OI 1h: <b>{cls._number(derivatives.get('oi_change_1h_pct'), 3)}%</b> · Funding: <b>{cls._number(derivatives.get('funding_rate_pct'), 4)}%</b>",
            f"🔻 Taker B/S: <b>{cls._number(flow.get('taker_buy_sell_ratio'), 3)}</b> · Sell share: <b>{cls._number(flow.get('sell_share_pct'), 1)}%</b>",
            f"💥 Cascade: <b>{escape(str(cascade.get('status') or 'UNAVAILABLE'))}</b> · {cls._number(cascade.get('readiness_points'), 1)}/10",
        ]
        if reasons:
            lines.append("🧾 " + " · ".join(reasons))
        lines.extend(["", "<i>Signal only. No live order is placed.</i>"])
        return "\n".join(lines)

    async def start_interactive_bot(self):
        if not self.enabled:
            return

        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        logger.info("📡 Interactive Telegram Command Center Online.")

        # One long-lived client for the whole polling loop; a fresh client per
        # second previously churned connections and hid every error behind a
        # bare except, so an invalid token looped forever with no log output.
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.get(url, params={"offset": -1, "timeout": 5})
                if resp.status_code == 200:
                    updates = resp.json().get("result", [])
                    if updates:
                        self.offset = updates[-1]["update_id"] + 1
            except Exception as exc:
                logger.warning("Telegram getUpdates bootstrap failed: %s", exc)

            while True:
                try:
                    resp = await client.get(url, params={"offset": self.offset, "timeout": 20})
                    if resp.status_code == 429:
                        retry_after = float(resp.headers.get("Retry-After", "30"))
                        logger.warning("Telegram poll rate-limited; backing off %ss.", retry_after)
                        await asyncio.sleep(retry_after)
                        continue
                    if resp.status_code == 200:
                        updates = resp.json().get("result", [])
                        for update in updates:
                            self.offset = update["update_id"] + 1
                            message = update.get("message", {})
                            chat = message.get("chat", {})
                            text = message.get("text", "")

                            if str(chat.get("id")) == self.chat_id and text.startswith("/"):
                                await self._process_command(text)
                    elif resp.status_code in (401, 403):
                        logger.error(
                            "Telegram polling rejected (HTTP %s): check TELEGRAM_TOKEN/CHAT_ID.",
                            resp.status_code,
                        )
                        await asyncio.sleep(60)
                except Exception as exc:
                    logger.warning("Telegram poll failed: %s", type(exc).__name__)
                await asyncio.sleep(1)

    async def _process_command(self, text: str):
        cmd = text.split("@")[0].lower().strip()

        if cmd == "/status":
            total = len(self.scanner.active_candidates) if self.scanner else 0
            await self.send_message(f"✅ <b>Waterfall Engine:</b> ONLINE\n🌊 <b>Live Targets Tracked:</b> {total}")

        elif cmd == "/armed":
            if self.db is None:
                return
            candidates = self.db.get_all_active_candidates()
            armed = [s.split(':')[0] for s, d in candidates.items() if d['status'] == 'ARMED']
            if armed:
                msg = f"🎯 <b>ARMED Targets ({len(armed)}):</b>\n" + "\n".join([f"- #{s}" for s in armed])
            else:
                msg = "🛡️ <b>No targets currently ARMED.</b>"
            await self.send_message(msg)

        elif cmd == "/ping":
            await self.send_message("🏓 <b>Pong!</b> Connection is stable.")


class TelegramSignalTransport:
    """Durable Telegram transport with explicit HTTP outcome classification."""

    def __init__(self, token: str, chat_id: str, *, http_transport=None):
        self.token = str(token or "").strip()
        self.chat_id = str(chat_id or "").strip()
        if not self.token or not self.chat_id:
            raise ValueError("Telegram token and chat id are required")
        self.http_transport = http_transport

    async def deliver(self, event: dict) -> DeliveryResult:
        try:
            payload = json.loads(str(event.get("payload_json") or "{}"))
        except json.JSONDecodeError:
            return DeliveryResult(DeliveryDisposition.PERMANENT_FAILURE, "INVALID_PAYLOAD_JSON")
        if payload.get("contract_version") != "entry_ready_notification_v1":
            return DeliveryResult(DeliveryDisposition.PERMANENT_FAILURE, "UNSUPPORTED_PAYLOAD")
        text = TelegramNotifier.build_entry_ready_message(payload)
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10.0, transport=self.http_transport) as client:
                response = await client.post(url, json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"})
        except (httpx.TimeoutException, TimeoutError):
            return DeliveryResult(DeliveryDisposition.TRANSIENT_FAILURE, "TELEGRAM_TIMEOUT")
        except httpx.HTTPError:
            return DeliveryResult(DeliveryDisposition.TRANSIENT_FAILURE, "TELEGRAM_HTTP_ERROR")
        if 200 <= response.status_code < 300:
            return DeliveryResult(DeliveryDisposition.DELIVERED)
        if response.status_code == 429:
            retry_after = None
            try:
                retry_after = int((response.json().get("parameters") or {}).get("retry_after"))
            except (TypeError, ValueError, json.JSONDecodeError):
                retry_after = None
            return DeliveryResult(DeliveryDisposition.RATE_LIMITED, "HTTP_429", retry_after)
        if response.status_code in {400, 401, 403, 404}:
            return DeliveryResult(DeliveryDisposition.PERMANENT_FAILURE, f"HTTP_{response.status_code}")
        return DeliveryResult(DeliveryDisposition.TRANSIENT_FAILURE, f"HTTP_{response.status_code}")

    async def probe(self) -> dict:
        url = f"https://api.telegram.org/bot{self.token}/getMe"
        try:
            async with httpx.AsyncClient(timeout=10.0, transport=self.http_transport) as client:
                response = await client.get(url)
            return {"configured": True, "reachable": response.status_code == 200, "status_code": response.status_code}
        except httpx.HTTPError:
            return {"configured": True, "reachable": False, "status_code": None}
