import json
import logging
import math
import sqlite3
import time
from typing import Any

from waterfallhunter.core.schema_contract import require_managed_schema
from waterfallhunter.core.signal_metadata import SignalMetadataInput


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
        *,
        verify_schema: bool = True,
    ):
        self.db_path = db_path
        if verify_schema:
            require_managed_schema(
                self.db_path,
                required_tables=frozenset({"lbank_signal_ledger"}),
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
        metadata: SignalMetadataInput,
        metadata_created_at: int | None = None,
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
            metadata_value = SignalMetadataInput.model_validate(metadata)
            metadata_time = (
                int(time.time())
                if metadata_created_at is None
                else metadata_created_at
            )
            if (
                isinstance(metadata_time, bool)
                or not isinstance(metadata_time, int)
                or metadata_time < 0
            ):
                raise ValueError(
                    "invalid signal identity, score, or metadata time"
                )
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

            if (
                not symbol
                or not expected_state
                or score_value is None
            ):
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
                raw_signal_id = inserted.lastrowid
                if raw_signal_id is None:
                    raise RuntimeError("signal ledger insert did not return a row id")
                signal_id = int(raw_signal_id)

                conn.execute(
                    """
                    INSERT INTO signal_metadata (
                        signal_id,
                        signal_class,
                        strategy_profile,
                        score_version,
                        model_generation,
                        decision_contract_hash,
                        analysis_observed_at,
                        reference_observed_at,
                        metadata_contract_version,
                        classification_method,
                        classification_evidence_hash,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        signal_id,
                        metadata_value.signal_class.value,
                        metadata_value.strategy_profile,
                        metadata_value.score_version,
                        metadata_value.model_generation,
                        metadata_value.decision_contract_hash,
                        metadata_value.analysis_observed_at,
                        metadata_value.reference_observed_at,
                        metadata_value.metadata_contract_version,
                        metadata_value.classification_method.value,
                        metadata_value.classification_evidence_hash,
                        metadata_time,
                    ),
                )

                return signal_id

        except Exception as exc:
            logger.error(
                "Atomic signal ledger persistence failed for %s: %s",
                symbol,
                exc,
            )
            return None
