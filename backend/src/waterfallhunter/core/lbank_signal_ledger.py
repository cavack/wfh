import json
import logging
import math
import sqlite3
import time
from typing import Any


logger = logging.getLogger(
    "WaterfallHunter.LBankSignalLedger"
)


class LBankSignalLedger:
    """Append-only production signal snapshots.

    A signal row and its catalogue transition are committed in one SQLite
    transaction. Execution suitability is captured for later observation only;
    it does not determine signal eligibility.
    """

    def __init__(
        self,
        db_path: str = "/app/data/waterfall_registry.db",
    ):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        try:
            with sqlite3.connect(
                self.db_path,
                timeout=10.0,
            ) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS lbank_signal_ledger (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        triggered_at INTEGER NOT NULL,
                        state_before TEXT NOT NULL,
                        score REAL NOT NULL,
                        entry_price REAL,
                        stop_loss REAL,
                        take_profit_1 REAL,
                        take_profit_2 REAL,
                        position_setup_json TEXT NOT NULL,
                        trigger_metrics_json TEXT NOT NULL,
                        execution_status TEXT NOT NULL,
                        execution_evidence_status TEXT,
                        execution_observed_samples INTEGER,
                        execution_observation_span_hours REAL,
                        execution_availability_rate REAL,
                        execution_cost_100_p90_pct REAL,
                        execution_spread_p90_pct REAL,
                        execution_depth_25bps_p50_usdt REAL,
                        execution_failed_checks_json TEXT NOT NULL,
                        execution_suitability_json TEXT NOT NULL,
                        quote_volume_at_trigger REAL,
                        volume_gate_passed INTEGER
                            CHECK (volume_gate_passed IN (0, 1)),
                        proxy_execution_disagreement TEXT,
                        observational_only INTEGER NOT NULL DEFAULT 1
                            CHECK (observational_only = 1),
                        trade_eligible INTEGER
                            CHECK (trade_eligible IS NULL),
                        created_at INTEGER NOT NULL
                    )
                    """
                )
                columns = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(lbank_signal_ledger)"
                    )
                }
                migrations = {
                    "quote_volume_at_trigger": "REAL",
                    "volume_gate_passed": (
                        "INTEGER CHECK (volume_gate_passed IN (0, 1))"
                    ),
                    "proxy_execution_disagreement": "TEXT",
                }
                for column, definition in migrations.items():
                    if column not in columns:
                        conn.execute(
                            f"ALTER TABLE lbank_signal_ledger "
                            f"ADD COLUMN {column} {definition}"
                        )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                        idx_lbank_signal_ledger_symbol_triggered
                    ON lbank_signal_ledger (
                        symbol,
                        triggered_at
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS
                        lbank_signal_ledger_no_update
                    BEFORE UPDATE ON lbank_signal_ledger
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'lbank_signal_ledger is immutable'
                        );
                    END
                    """
                )
                conn.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS
                        lbank_signal_ledger_no_delete
                    BEFORE DELETE ON lbank_signal_ledger
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'lbank_signal_ledger is immutable'
                        );
                    END
                    """
                )
        except Exception as exc:
            logger.error(
                "Signal ledger initialization failed: %s",
                exc,
            )

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(
            value,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _finite(
        value: Any,
    ) -> float | None:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            return None
        number = float(value)
        return number if math.isfinite(number) else None

    def persist_trigger(
        self,
        symbol: str,
        expected_state: str,
        *,
        score: float,
        trigger_metrics: dict,
        execution_suitability: dict,
        quote_volume: float | None = None,
        volume_gate_passed: bool | None = None,
        proxy_execution_disagreement: str | None = None,
        triggered_at: int | None = None,
    ) -> int | None:
        """Compare-and-set the live state and append its signal atomically."""
        try:
            symbol = str(symbol).strip().upper()
            expected_state = str(expected_state).strip().upper()
            score_value = self._finite(score)
            metrics = (
                trigger_metrics
                if isinstance(trigger_metrics, dict)
                else {}
            )
            execution = (
                execution_suitability
                if isinstance(execution_suitability, dict)
                else {}
            )
            position = (
                metrics.get("position_setup")
                if isinstance(metrics.get("position_setup"), dict)
                else {}
            )
            event_time = int(
                time.time()
                if triggered_at is None
                else triggered_at
            )

            if not symbol or not expected_state or score_value is None:
                raise ValueError("invalid signal identity or score")

            metrics_json = self._json(metrics)
            position_json = self._json(position)
            execution_json = self._json(execution)
            failed_checks_json = self._json(
                list(execution.get("failed_checks") or [])
            )
            volume_gate_snapshot = (
                None
                if volume_gate_passed is None
                else int(bool(volume_gate_passed))
            )
            comparison_snapshot = (
                str(proxy_execution_disagreement)
                if proxy_execution_disagreement is not None
                else None
            )

            with sqlite3.connect(
                self.db_path,
                timeout=10.0,
            ) as conn:
                cursor = conn.execute(
                    """
                    UPDATE lbank_catalog
                    SET
                        status = 'TRIGGERED',
                        trigger_data = ?
                    WHERE
                        symbol = ?
                        AND scan_eligible = 1
                        AND status = ?
                    """,
                    (
                        metrics_json,
                        symbol,
                        expected_state,
                    ),
                )

                if cursor.rowcount != 1:
                    logger.warning(
                        "Signal ledger rejected stale or ineligible "
                        "transition for %s from %s",
                        symbol,
                        expected_state,
                    )
                    return None

                inserted = conn.execute(
                    """
                    INSERT INTO lbank_signal_ledger (
                        symbol,
                        triggered_at,
                        state_before,
                        score,
                        entry_price,
                        stop_loss,
                        take_profit_1,
                        take_profit_2,
                        position_setup_json,
                        trigger_metrics_json,
                        execution_status,
                        execution_evidence_status,
                        execution_observed_samples,
                        execution_observation_span_hours,
                        execution_availability_rate,
                        execution_cost_100_p90_pct,
                        execution_spread_p90_pct,
                        execution_depth_25bps_p50_usdt,
                        execution_failed_checks_json,
                        execution_suitability_json,
                        quote_volume_at_trigger,
                        volume_gate_passed,
                        proxy_execution_disagreement,
                        observational_only,
                        trade_eligible,
                        created_at
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, 1, NULL, ?
                    )
                    """,
                    (
                        symbol,
                        event_time,
                        expected_state,
                        score_value,
                        self._finite(position.get("entry_price")),
                        self._finite(position.get("stop_loss")),
                        self._finite(position.get("take_profit_1")),
                        self._finite(position.get("take_profit_2")),
                        position_json,
                        metrics_json,
                        str(execution.get("status") or "UNKNOWN"),
                        execution.get("evidence_status"),
                        execution.get("observed_samples"),
                        self._finite(
                            execution.get("observation_span_hours")
                        ),
                        self._finite(execution.get("availability_rate")),
                        self._finite(execution.get("cost_100_p90_pct")),
                        self._finite(execution.get("spread_p90_pct")),
                        self._finite(
                            execution.get("depth_25bps_p50_usdt")
                        ),
                        failed_checks_json,
                        execution_json,
                        self._finite(quote_volume),
                        volume_gate_snapshot,
                        comparison_snapshot,
                        int(time.time()),
                    ),
                )

                return int(inserted.lastrowid)

        except Exception as exc:
            logger.error(
                "Atomic signal ledger persistence failed for %s: %s",
                symbol,
                exc,
            )
            return None
