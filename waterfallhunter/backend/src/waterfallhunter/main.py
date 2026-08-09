import logging
import asyncio
import traceback
import json
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
import os

from waterfallhunter.config import settings
from waterfallhunter.core.db import DBAdapter
from waterfallhunter.discovery.lbank_scanner import LBankCatalogScanner
from waterfallhunter.core.multi_exchange_validator import MultiExchangeValidator
from waterfallhunter.core.notifier import TelegramNotifier
from waterfallhunter.core.ai_veto import AIVetoEngine
from waterfallhunter.core.risk_manager import get_leverage

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("WaterfallHunter")

app = FastAPI(title="WaterfallHunter API - Production", version="7.5.0-Interactive")

db = DBAdapter()
scanner = LBankCatalogScanner(db_adapter=db, max_price=1.0, min_volume_usdt=500000.0)
validator = MultiExchangeValidator()
# تزریق اسکنر و دیتابیس به تلگرام برای پاسخگویی به دستورات
notifier = TelegramNotifier(db_adapter=db, scanner=scanner)
ai_veto = AIVetoEngine()

_hunter_running = False
_sse_clients = set()

def get_formatted_candidates():
    active_from_db = db.get_all_active_candidates()
    for symbol, data in active_from_db.items():
        live_data = scanner.active_candidates.get(symbol, {})
        data["score"] = live_data.get("score", 0)
        data["metrics"] = live_data.get("metrics", {})

    sorted_candidates = {
        k: v for k, v in sorted(
            active_from_db.items(), 
            key=lambda item: item[1].get("score", 0), 
            reverse=True
        )
    }
    return {"total": len(sorted_candidates), "candidates": sorted_candidates}

async def sse_broadcaster():
    while _hunter_running:
        if _sse_clients:
            data = get_formatted_candidates()
            msg = f"data: {json.dumps(data)}\n\n"
            for q in list(_sse_clients):
                try:
                    q.put_nowait(msg)
                except asyncio.QueueFull:
                    pass
        await asyncio.sleep(1.0)

async def evaluate_candidate(symbol: str, data: dict):
    lbank_price = data["last_price"]
    current_state = data["status"]

    result = await validator.cross_check_symbol(symbol, lbank_price)
    if not result["is_valid"]: return

    score = result["score"]
    new_state = result["suggested_status"]
    metrics = result["metrics"]
    ex_name = metrics.get("exchange")
    mapped_sym = metrics.get("mapped_symbol")
    
    if symbol not in scanner.active_candidates:
        scanner.active_candidates[symbol] = {}
    scanner.active_candidates[symbol]["score"] = score
    scanner.active_candidates[symbol]["metrics"] = metrics

    if current_state == "WATCH":
        if new_state == "ARMED":
            db.update_candidate_state(symbol, "ARMED")
            logger.info(f"🎯 [{symbol}] TARGET ARMED. Starting WS stream on {ex_name}...")
            validator.ws_manager.subscribe(ex_name, mapped_sym)

        elif new_state == "TRIGGERED":
            is_vetoed, advisory = await ai_veto.evaluate_symbol(symbol, metrics.get("orderbook", {}), metrics.get("ticker", {}))
            metrics["ai_advisory"] = advisory
            if is_vetoed:
                db.update_candidate_state(symbol, "WATCH")
            else:
                try:
                    metrics["applied_leverage"] = get_leverage(symbol)
                except Exception:
                    pass
                db.update_candidate_state(symbol, "TRIGGERED", metrics)
                logger.warning(f"🔥 [{symbol}] INSTANT TRIGGER - Score: {score}/100")
                await notifier.send_signal_alert(symbol, {"score": score, "metrics": metrics})
                
    elif current_state == "ARMED":
        if new_state == "TRIGGERED":
            is_vetoed, advisory = await ai_veto.evaluate_symbol(symbol, metrics.get("orderbook", {}), metrics.get("ticker", {}))
            metrics["ai_advisory"] = advisory
            if is_vetoed:
                db.update_candidate_state(symbol, "WATCH")
            else:
                try:
                    metrics["applied_leverage"] = get_leverage(symbol)
                except Exception:
                    pass
                db.update_candidate_state(symbol, "TRIGGERED", metrics)
                logger.warning(f"🔥 [{symbol}] ARMED TARGET TRIGGERED - Score: {score}/100")
                await notifier.send_signal_alert(symbol, {"score": score, "metrics": metrics})
            validator.ws_manager.unsubscribe(ex_name, mapped_sym)
                
        elif new_state == "WATCH":
            db.update_candidate_state(symbol, "WATCH")
            validator.ws_manager.unsubscribe(ex_name, mapped_sym)

async def hunter_loop(interval_seconds: int = 60):
    global _hunter_running
    _hunter_running = True
    await asyncio.sleep(5)
    logger.info("🛡️ [SYSTEM] Engine Online: State Machine running.")

    while _hunter_running:
        try:
            candidates = db.get_all_active_candidates()
            if len(candidates) > 0:
                for symbol, data in candidates.items():
                    if not _hunter_running: break
                    await evaluate_candidate(symbol, data)
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"⚠️ Hunter Loop Error: {e}")
            await asyncio.sleep(15)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(scanner.update_catalog())
    asyncio.create_task(scanner.start_background_scanner(14400))
    asyncio.create_task(hunter_loop(interval_seconds=60))
    asyncio.create_task(sse_broadcaster())
    # روشن کردن گوش‌به‌زنگ تلگرام
    asyncio.create_task(notifier.start_interactive_bot())

@app.on_event("shutdown")
async def shutdown_event():
    global _hunter_running
    _hunter_running = False
    scanner.stop()
    await validator.close_all()

@app.get("/api/stream")
async def stream_candidates():
    q = asyncio.Queue(maxsize=100)
    _sse_clients.add(q)
    async def event_generator():
        try:
            yield f"data: {json.dumps(get_formatted_candidates())}\n\n"
            while True:
                yield await q.get()
        except asyncio.CancelledError:
            _sse_clients.remove(q)
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/candidates")
async def get_candidates():
    return get_formatted_candidates()
