import logging
import httpx
import asyncio
import math
from html import escape
from waterfallhunter.config import settings

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
