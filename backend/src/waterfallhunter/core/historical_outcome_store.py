import hashlib
import json
import math
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class HistoricalOutcomeStore:
    """Operational, immutable store for provenance-labelled historical outcomes."""

    SCHEMA_VERSION = "operational_historical_outcomes_v1"

    def __init__(
        self,
        db_path: str = "/app/data/waterfall_registry.db",
        *,
        cache_ttl_seconds: float = 60.0,
    ):
        self.db_path = db_path
        self.cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self._lock = threading.Lock()
        self._cache_at = 0.0
        self._cache: dict | None = None
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path, timeout=10.0) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS operational_historical_outcome_datasets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_sha256 TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    generated_at TEXT,
                    window_start_ms INTEGER NOT NULL,
                    window_end_ms INTEGER NOT NULL,
                    days INTEGER NOT NULL,
                    strategy TEXT NOT NULL,
                    cost_basis TEXT NOT NULL,
                    strategy_equivalent INTEGER NOT NULL CHECK(strategy_equivalent IN (0, 1)),
                    source_provenance_json TEXT NOT NULL,
                    imported_at INTEGER NOT NULL,
                    observational_only INTEGER NOT NULL DEFAULT 1 CHECK(observational_only = 1),
                    hard_gating_allowed INTEGER NOT NULL DEFAULT 0 CHECK(hard_gating_allowed = 0)
                );

                CREATE TABLE IF NOT EXISTS operational_historical_signal_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset_id INTEGER NOT NULL,
                    event_key TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    signal_timestamp_ms INTEGER NOT NULL,
                    exit_timestamp_ms INTEGER,
                    outcome TEXT NOT NULL,
                    gross_realized_r REAL,
                    net_realized_r REAL NOT NULL,
                    exit_reason TEXT,
                    cost_basis TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    observational_only INTEGER NOT NULL DEFAULT 1 CHECK(observational_only = 1),
                    trade_eligible INTEGER CHECK(trade_eligible IS NULL),
                    FOREIGN KEY(dataset_id) REFERENCES operational_historical_outcome_datasets(id)
                );

                CREATE INDEX IF NOT EXISTS idx_operational_historical_symbol
                ON operational_historical_signal_outcomes(dataset_id, symbol, signal_timestamp_ms);

                CREATE TRIGGER IF NOT EXISTS operational_historical_datasets_no_update
                BEFORE UPDATE ON operational_historical_outcome_datasets
                BEGIN SELECT RAISE(ABORT, 'operational historical datasets are immutable'); END;

                CREATE TRIGGER IF NOT EXISTS operational_historical_datasets_no_delete
                BEFORE DELETE ON operational_historical_outcome_datasets
                BEGIN SELECT RAISE(ABORT, 'operational historical datasets are immutable'); END;

                CREATE TRIGGER IF NOT EXISTS operational_historical_outcomes_no_update
                BEFORE UPDATE ON operational_historical_signal_outcomes
                BEGIN SELECT RAISE(ABORT, 'operational historical outcomes are immutable'); END;

                CREATE TRIGGER IF NOT EXISTS operational_historical_outcomes_no_delete
                BEFORE DELETE ON operational_historical_signal_outcomes
                BEGIN SELECT RAISE(ABORT, 'operational historical outcomes are immutable'); END;
                """
            )

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        value = str(symbol).strip().upper()
        if "/" in value:
            return value
        if value.endswith("USDT") and len(value) > 4:
            return f"{value[:-4]}/USDT:USDT"
        return value

    @staticmethod
    def _finite(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        result = float(value)
        return result if math.isfinite(result) else None

    @classmethod
    def _validate_report(cls, report: dict) -> tuple[dict, list[dict]]:
        if not isinstance(report, dict):
            raise ValueError("historical report must be an object")
        window = report.get("window")
        trades = report.get("trades")
        contract = report.get("net_ev_contract")
        if not isinstance(window, dict) or not isinstance(trades, list):
            raise ValueError("historical report is missing window or trades")
        if not isinstance(contract, dict):
            raise ValueError("historical report is missing net EV contract")
        if contract.get("promotion_permitted") is not False:
            raise ValueError("historical report must prohibit promotion")
        if not report.get("source") or not report.get("strategy"):
            raise ValueError("historical report is missing source or strategy")
        if not isinstance(window.get("start_ms"), int) or not isinstance(window.get("end_ms"), int):
            raise ValueError("historical report window is invalid")
        normalized: list[dict] = []
        for trade in trades:
            if not isinstance(trade, dict):
                raise ValueError("historical trade must be an object")
            net_r = cls._finite(trade.get("net_realized_r"))
            costs = trade.get("execution_costs")
            if (
                not trade.get("symbol")
                or not isinstance(trade.get("timestamp"), int)
                or net_r is None
                or not isinstance(costs, dict)
                or costs.get("complete") is not True
            ):
                raise ValueError("historical trade lacks complete modeled outcome evidence")
            normalized.append({**trade, "net_realized_r": net_r})
        return window, normalized

    def import_report_file(self, report_path: str) -> dict:
        raw = Path(report_path).read_bytes()
        report = json.loads(raw)
        return self.import_report(report, report_sha256=hashlib.sha256(raw).hexdigest())

    def import_report(self, report: dict, *, report_sha256: str) -> dict:
        window, trades = self._validate_report(report)
        cost_basis = str((report.get("net_ev_contract") or {}).get("cost_basis") or "modeled")
        provenance = json.dumps(
            report.get("source_provenance") or {},
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT id FROM operational_historical_outcome_datasets WHERE report_sha256 = ?",
                (str(report_sha256),),
            ).fetchone()
            if existing:
                count = conn.execute(
                    "SELECT COUNT(*) FROM operational_historical_signal_outcomes WHERE dataset_id = ?",
                    (existing[0],),
                ).fetchone()[0]
                return {"imported": False, "dataset_id": existing[0], "event_count": count, "idempotent": True}

            cursor = conn.execute(
                """
                INSERT INTO operational_historical_outcome_datasets (
                    report_sha256, source, generated_at, window_start_ms, window_end_ms,
                    days, strategy, cost_basis, strategy_equivalent,
                    source_provenance_json, imported_at, observational_only,
                    hard_gating_allowed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                """,
                (
                    str(report_sha256), str(report["source"]), report.get("generated_at"),
                    int(window["start_ms"]), int(window["end_ms"]), int(report.get("days") or 0),
                    str(report["strategy"]), cost_basis, 1 if report.get("strategy_equivalent") is True else 0,
                    provenance, int(time.time()),
                ),
            )
            dataset_id = int(cursor.lastrowid)
            for trade in trades:
                symbol = self.normalize_symbol(trade["symbol"])
                event_key = hashlib.sha256(
                    f"{report_sha256}:{symbol}:{trade['timestamp']}".encode()
                ).hexdigest()
                details = {
                    "score": trade.get("score"),
                    "setup_type": trade.get("setup_type"),
                    "execution_costs": trade.get("execution_costs"),
                    "historical_score_v2": trade.get("historical_score_v2"),
                }
                conn.execute(
                    """
                    INSERT INTO operational_historical_signal_outcomes (
                        dataset_id, event_key, symbol, signal_timestamp_ms,
                        exit_timestamp_ms, outcome, gross_realized_r,
                        net_realized_r, exit_reason, cost_basis, details_json,
                        observational_only, trade_eligible
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NULL)
                    """,
                    (
                        dataset_id, event_key, symbol, int(trade["timestamp"]),
                        trade.get("exit_timestamp"), str(trade.get("outcome") or "unknown"),
                        self._finite(trade.get("realized_r")), trade["net_realized_r"],
                        trade.get("exit_reason"), str((trade.get("execution_costs") or {}).get("basis") or cost_basis),
                        json.dumps(details, allow_nan=False, sort_keys=True, separators=(",", ":")),
                    ),
                )
        with self._lock:
            self._cache = None
            self._cache_at = 0.0
        return {"imported": True, "dataset_id": dataset_id, "event_count": len(trades), "idempotent": False}

    def build_report(self) -> dict:
        now = time.time()
        with self._lock:
            if self._cache is not None and now - self._cache_at <= self.cache_ttl_seconds:
                return json.loads(json.dumps(self._cache))
        with sqlite3.connect(self.db_path, timeout=10.0) as conn:
            conn.row_factory = sqlite3.Row
            dataset = conn.execute(
                "SELECT * FROM operational_historical_outcome_datasets ORDER BY window_end_ms DESC, id DESC LIMIT 1"
            ).fetchone()
            if dataset is None:
                report = self._empty_report()
            else:
                rows = conn.execute(
                    """
                    SELECT symbol, COUNT(*) event_count,
                           SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) wins,
                           SUM(CASE WHEN outcome IN ('win', 'loss') THEN 1 ELSE 0 END) settled,
                           AVG(net_realized_r) net_expectancy_r
                    FROM operational_historical_signal_outcomes
                    WHERE dataset_id = ? GROUP BY symbol ORDER BY symbol
                    """,
                    (dataset["id"],),
                ).fetchall()
                by_symbol = {}
                for row in rows:
                    settled = int(row["settled"] or 0)
                    wins = int(row["wins"] or 0)
                    by_symbol[row["symbol"]] = {
                        "available": True,
                        "event_count": int(row["event_count"]),
                        "settled_count": settled,
                        "wins": wins,
                        "win_rate": round(wins / settled, 6) if settled else None,
                        "net_expectancy_r": round(float(row["net_expectancy_r"]), 6),
                        "evidence_source": "historical_backfill",
                        "ranking_eligible": False,
                    }
                totals = conn.execute(
                    """
                    SELECT COUNT(*) event_count,
                           SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) wins,
                           SUM(CASE WHEN outcome IN ('win', 'loss') THEN 1 ELSE 0 END) settled,
                           AVG(net_realized_r) net_expectancy_r
                    FROM operational_historical_signal_outcomes WHERE dataset_id = ?
                    """,
                    (dataset["id"],),
                ).fetchone()
                settled = int(totals["settled"] or 0)
                wins = int(totals["wins"] or 0)
                report = {
                    "schema_version": self.SCHEMA_VERSION,
                    "available": True,
                    "operational": True,
                    "observational_only": True,
                    "hard_gating_allowed": False,
                    "threshold_calibration_allowed": False,
                    "evidence_source": "historical_backfill",
                    "dataset": {
                        "id": int(dataset["id"]),
                        "report_sha256": dataset["report_sha256"],
                        "source": dataset["source"],
                        "generated_at": dataset["generated_at"],
                        "window_start_ms": int(dataset["window_start_ms"]),
                        "window_end_ms": int(dataset["window_end_ms"]),
                        "days": int(dataset["days"]),
                        "strategy": dataset["strategy"],
                        "cost_basis": dataset["cost_basis"],
                        "strategy_equivalent": bool(dataset["strategy_equivalent"]),
                        "imported_at": int(dataset["imported_at"]),
                    },
                    "summary": {
                        "event_count": int(totals["event_count"] or 0),
                        "settled_count": settled,
                        "wins": wins,
                        "win_rate": round(wins / settled, 6) if settled else None,
                        "net_expectancy_r": round(float(totals["net_expectancy_r"]), 6) if totals["net_expectancy_r"] is not None else None,
                    },
                    "by_symbol": by_symbol,
                }
        with self._lock:
            self._cache = report
            self._cache_at = now
        return json.loads(json.dumps(report))

    def _empty_report(self) -> dict:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "available": False,
            "operational": True,
            "observational_only": True,
            "hard_gating_allowed": False,
            "threshold_calibration_allowed": False,
            "evidence_source": "historical_backfill",
            "dataset": None,
            "summary": {"event_count": 0, "settled_count": 0, "wins": 0, "win_rate": None, "net_expectancy_r": None},
            "by_symbol": {},
        }

    def symbol_summaries(self) -> dict[str, dict]:
        return self.build_report().get("by_symbol") or {}
