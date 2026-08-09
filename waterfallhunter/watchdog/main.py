import time
import httpx
import os
import logging

logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_URL = "http://127.0.0.1:8000/api/health"

def send_alert(msg):
    if TOKEN and CHAT_ID:
        try:
            httpx.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg})
        except: pass

down_count = 0
while True:
    try:
        res = httpx.get(API_URL, timeout=10.0)
        res.raise_for_status()
        if down_count > 0:
            send_alert("✅ Waterfall Backend is RECOVERED and ONLINE.")
            down_count = 0
    except Exception as e:
        down_count += 1
        logging.error(f"Backend unreachable: {e}")
        if down_count == 3:
            send_alert("🚨 CRITICAL: Waterfall Backend is DOWN!")
    time.sleep(30)
