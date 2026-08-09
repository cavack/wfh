import logging
import httpx
import asyncio
from waterfallhunter.config import settings

logger = logging.getLogger("WaterfallHunter.Telegram")

class TelegramNotifier:
    def __init__(self, db_adapter=None, scanner=None):
        self.token = settings.telegram_token
        self.chat_id = str(settings.telegram_chat_id)
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
        
        score = data.get("score", 0)
        metrics = data.get("metrics", {})
        pos_setup = metrics.get("position_setup", {})
        
        message = (
            f"🚨 <b>WATERFALL SIGNAL FIRED</b> 🚨\n\n"
            f"🪙 <b>Symbol:</b> #{symbol.split('/')[0]}\n"
            f"🔥 <b>Quant Score:</b> {score}/100\n"
            f"⚖️ <b>Applied Leverage:</b> {metrics.get('applied_leverage', 10)}x\n\n"
            f"<b>TRADE SETUP (Strict Risk)</b>\n"
            f"🎯 <b>Entry:</b> ${pos_setup.get('entry_price')}\n"
            f"🛑 <b>Stop Loss:</b> ${pos_setup.get('stop_loss')} ({pos_setup.get('risk_pct')}%) \n"
            f"💰 <b>Take Profit 1:</b> ${pos_setup.get('take_profit_1')}\n"
            f"💰 <b>Take Profit 2:</b> ${pos_setup.get('take_profit_2')} (R:R {pos_setup.get('reward_to_risk')})\n\n"
            f"<i>Status: TRIGGERED & LOGGED</i>"
        )
        await self.send_message(message)

    async def start_interactive_bot(self):
        """سیستم Polling برای دریافت دستورات شما از تلگرام"""
        if not self.enabled:
            return
        
        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        logger.info("📡 Interactive Telegram Command Center Online.")
        
        # نادیده گرفتن پیام‌های قدیمی هنگام راه‌اندازی
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params={"offset": -1, "timeout": 5})
                if resp.status_code == 200:
                    updates = resp.json().get("result", [])
                    if updates:
                        self.offset = updates[-1]["update_id"] + 1
        except Exception:
            pass

        while True:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(url, params={"offset": self.offset, "timeout": 20})
                    if resp.status_code == 200:
                        updates = resp.json().get("result", [])
                        for update in updates:
                            self.offset = update["update_id"] + 1
                            message = update.get("message", {})
                            chat = message.get("chat", {})
                            text = message.get("text", "")
                            
                            # کنترل امنیتی: فقط به چت‌آیدی اختصاصی شما پاسخ می‌دهد
                            if str(chat.get("id")) == self.chat_id and text.startswith("/"):
                                await self._process_command(text)
            except Exception:
                pass
            await asyncio.sleep(1)
            
    async def _process_command(self, text: str):
        cmd = text.split("@")[0].lower().strip()
        
        if cmd == "/status":
            total = len(self.scanner.active_candidates) if self.scanner else 0
            await self.send_message(f"✅ <b>Waterfall Engine:</b> ONLINE\n🌊 <b>Live Targets Tracked:</b> {total}")
            
        elif cmd == "/armed":
            if not self.db: return
            candidates = self.db.get_all_active_candidates()
            armed = [s.split(':')[0] for s, d in candidates.items() if d['status'] == 'ARMED']
            if armed:
                msg = f"🎯 <b>ARMED Targets ({len(armed)}):</b>\n" + "\n".join([f"- #{s}" for s in armed])
            else:
                msg = "🛡️ <b>No targets currently ARMED.</b>"
            await self.send_message(msg)
            
        elif cmd == "/ping":
            await self.send_message("🏓 <b>Pong!</b> Connection is stable.")
