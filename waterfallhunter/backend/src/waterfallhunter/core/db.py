import sqlite3
import logging
from typing import Dict, Any
import json
import time

logger = logging.getLogger("WaterfallHunter.Database")

class DBAdapter:
    def __init__(self, db_path="/app/data/waterfall_registry.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                # استفاده از WAL برای جلوگیری از قفل شدن دیتابیس در HFT
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS lbank_catalog (
                        symbol TEXT PRIMARY KEY,
                        last_price REAL,
                        quote_volume REAL,
                        is_meme BOOLEAN,
                        status TEXT DEFAULT 'WATCH',  -- WATCH, ARMED, TRIGGERED, REJECTED
                        first_seen_at INTEGER,
                        last_updated_at INTEGER,
                        trigger_data TEXT
                    )
                """)
                conn.commit()
                logger.info("SQLite WAL initialized successfully.")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")

    def update_candidates(self, candidates_map: Dict[str, Any]):
        current_time = int(time.time())
        try:
            with sqlite3.connect(self.db_path) as conn:
                for symbol, data in candidates_map.items():
                    price = data["last_price"]
                    volume = data.get("quote_volume", 0.0)
                    is_meme = 1 if data["is_meme"] else 0
                    
                    conn.execute("""
                        INSERT INTO lbank_catalog (symbol, last_price, quote_volume, is_meme, first_seen_at, last_updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(symbol) DO UPDATE SET
                            last_price = excluded.last_price,
                            quote_volume = excluded.quote_volume,
                            last_updated_at = excluded.last_updated_at
                    """, (symbol, price, volume, is_meme, current_time, current_time))
                
                # اعمال انقضای 24 ساعته (ارزهایی که از لیست صرافی خارج شده یا حجمشان افت کرده است)
                expiration_threshold = current_time - 86400
                conn.execute("""
                    UPDATE lbank_catalog 
                    SET status = 'REJECTED' 
                    WHERE last_updated_at < ? AND status IN ('WATCH', 'ARMED')
                """, (expiration_threshold,))
                
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating candidates in DB: {e}")

    def get_all_active_candidates(self) -> Dict[str, Any]:
        candidates = {}
        valid_time_threshold = int(time.time()) - 86400
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM lbank_catalog 
                    WHERE status IN ('WATCH', 'ARMED', 'TRIGGERED') 
                    AND last_updated_at > ?
                """, (valid_time_threshold,))
                
                for row in cursor.fetchall():
                    candidates[row['symbol']] = dict(row)
        except Exception as e:
            logger.error(f"Error fetching candidates from DB: {e}")
            
        return candidates

    def update_candidate_state(self, symbol: str, new_state: str, trigger_data: Dict = None):
        try:
            with sqlite3.connect(self.db_path) as conn:
                data_str = json.dumps(trigger_data) if trigger_data else "{}"
                conn.execute("""
                    UPDATE lbank_catalog 
                    SET status = ?, trigger_data = ?, last_updated_at = ?
                    WHERE symbol = ?
                """, (new_state, data_str, int(time.time()), symbol))
                conn.commit()
                logger.info(f"[{symbol}] State transitioned to {new_state}")
        except Exception as e:
            logger.error(f"Error updating state for {symbol}: {e}")
