from __future__ import annotations

from collections import Counter
import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from waterfallhunter.core.schema_unique_constraints import (
    verify_unique_constraints_connection,
)


CURRENT_RUNTIME_SCHEMA_VERSION = 2


class SchemaContractError(RuntimeError):
    """Raised when a managed SQLite schema does not match the canonical contract."""


@dataclass(frozen=True, slots=True)
class SchemaIssue:
    code: str
    object_name: str
    detail: str


@dataclass(frozen=True, slots=True)
class SchemaVerificationResult:
    valid: bool
    user_version: int | None
    issues: tuple[SchemaIssue, ...]
    unknown_user_objects: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    name: str
    declared_type: str
    not_null: bool = False
    default: str | None = None
    primary_key_position: int = 0


@dataclass(frozen=True, slots=True)
class IndexSpec:
    name: str
    columns: tuple[str, ...]
    unique: bool = False


@dataclass(frozen=True, slots=True)
class ForeignKeySpec:
    column: str
    target_table: str
    target_column: str
    on_update: str = "NO ACTION"
    on_delete: str = "NO ACTION"
    match: str = "NONE"


@dataclass(frozen=True, slots=True)
class TriggerSpec:
    name: str
    event: str
    abort_message: str


@dataclass(frozen=True, slots=True)
class ManagedTableSpec:
    name: str
    columns: tuple[ColumnSpec, ...]
    indexes: tuple[IndexSpec, ...] = ()
    foreign_keys: tuple[ForeignKeySpec, ...] = ()
    check_fragments: tuple[str, ...] = ()
    triggers: tuple[TriggerSpec, ...] = ()


def _c(
    name: str,
    declared_type: str,
    *,
    not_null: bool = False,
    default: str | None = None,
    pk: int = 0,
) -> ColumnSpec:
    return ColumnSpec(name, declared_type, not_null, default, pk)


def _immutable(table: str, *, message: str) -> tuple[TriggerSpec, TriggerSpec]:
    return (
        TriggerSpec(f"{table}_no_update", "UPDATE", message),
        TriggerSpec(f"{table}_no_delete", "DELETE", message),
    )


_RUNTIME_SCHEMA: dict[str, ManagedTableSpec] = {
    "lbank_catalog": ManagedTableSpec(
        name="lbank_catalog",
        columns=(
            _c("symbol", "TEXT", pk=1),
            _c("last_price", "REAL"),
            _c("quote_volume", "REAL"),
            _c("is_meme", "BOOLEAN"),
            _c("scan_eligible", "BOOLEAN", default="0"),
            _c("status", "TEXT", default="'WATCH'"),
            _c("first_seen_at", "INTEGER"),
            _c("last_added_at", "INTEGER"),
            _c("last_seen_at", "INTEGER"),
            _c("removed_at", "INTEGER"),
            _c("consecutive_missing_snapshots", "INTEGER", default="0"),
            _c("lifecycle_id", "INTEGER", not_null=True, default="1"),
            _c("trigger_data", "TEXT"),
        ),
    ),
    "catalog_events": ManagedTableSpec(
        name="catalog_events",
        columns=(
            _c("id", "INTEGER", pk=1),
            _c("symbol", "TEXT"),
            _c("event_type", "TEXT"),
            _c("timestamp", "INTEGER"),
        ),
    ),
    "lbank_signal_ledger": ManagedTableSpec(
        name="lbank_signal_ledger",
        columns=(
            _c("id", "INTEGER", pk=1),
            _c("symbol", "TEXT", not_null=True),
            _c("triggered_at", "INTEGER", not_null=True),
            _c("state_before", "TEXT", not_null=True),
            _c("score", "REAL", not_null=True),
            _c("entry_price", "REAL"),
            _c("stop_loss", "REAL"),
            _c("take_profit_1", "REAL"),
            _c("take_profit_2", "REAL"),
            _c("position_setup_json", "TEXT", not_null=True),
            _c("trigger_metrics_json", "TEXT", not_null=True),
            _c("execution_status", "TEXT", not_null=True),
            _c("execution_evidence_status", "TEXT"),
            _c("execution_observed_samples", "INTEGER"),
            _c("execution_observation_span_hours", "REAL"),
            _c("execution_availability_rate", "REAL"),
            _c("execution_cost_100_p90_pct", "REAL"),
            _c("execution_spread_p90_pct", "REAL"),
            _c("execution_depth_25bps_p50_usdt", "REAL"),
            _c("execution_failed_checks_json", "TEXT", not_null=True),
            _c("execution_suitability_json", "TEXT", not_null=True),
            _c("quote_volume_at_trigger", "REAL"),
            _c("volume_gate_passed", "INTEGER"),
            _c("proxy_execution_disagreement", "TEXT"),
            _c("observational_only", "INTEGER", not_null=True, default="1"),
            _c("trade_eligible", "INTEGER"),
            _c("created_at", "INTEGER", not_null=True),
        ),
        indexes=(
            IndexSpec(
                "idx_lbank_signal_ledger_symbol_triggered",
                ("symbol", "triggered_at"),
            ),
        ),
        check_fragments=(
            "check(volume_gate_passed in (0, 1))",
            "check(observational_only = 1)",
            "check(trade_eligible is null)",
        ),
        triggers=_immutable(
            "lbank_signal_ledger",
            message="lbank_signal_ledger is immutable",
        ),
    ),
    "lbank_signal_outcomes": ManagedTableSpec(
        name="lbank_signal_outcomes",
        columns=(
            _c("id", "INTEGER", pk=1),
            _c("signal_id", "INTEGER", not_null=True),
            _c("symbol", "TEXT", not_null=True),
            _c("outcome_status", "TEXT", not_null=True),
            _c("signal_triggered_at", "INTEGER", not_null=True),
            _c("observation_started_at", "INTEGER"),
            _c("observation_ended_at", "INTEGER"),
            _c("horizon_seconds", "INTEGER", not_null=True),
            _c("price_source", "TEXT", not_null=True),
            _c("source_exchange", "TEXT"),
            _c("source_mapped_symbol", "TEXT"),
            _c("first_tp1_at", "INTEGER"),
            _c("first_tp2_at", "INTEGER"),
            _c("first_stop_at", "INTEGER"),
            _c("min_price", "REAL"),
            _c("max_price", "REAL"),
            _c("mfe_pct", "REAL"),
            _c("mae_pct", "REAL"),
            _c("observed_candles", "INTEGER", not_null=True),
            _c("expected_candles", "INTEGER", not_null=True),
            _c("details_json", "TEXT", not_null=True),
            _c("observational_only", "INTEGER", not_null=True, default="1"),
            _c("trade_eligible", "INTEGER"),
            _c("resolved_at", "INTEGER", not_null=True),
        ),
        indexes=(
            IndexSpec(
                "idx_lbank_signal_outcomes_status",
                ("outcome_status", "resolved_at"),
            ),
        ),
        foreign_keys=(
            ForeignKeySpec("signal_id", "lbank_signal_ledger", "id"),
        ),
        check_fragments=(
            "check(observational_only = 1)",
            "check(trade_eligible is null)",
        ),
        triggers=_immutable(
            "lbank_signal_outcomes",
            message="lbank_signal_outcomes is immutable",
        ),
    ),
    "lbank_stage_lifecycle": ManagedTableSpec(
        name="lbank_stage_lifecycle",
        columns=(
            _c("symbol", "TEXT", not_null=True, pk=1),
            _c("lifecycle_id", "INTEGER", not_null=True, pk=2),
            _c("hype_seen_at", "INTEGER"),
            _c("damage_seen_at", "INTEGER"),
            _c("setup_seen_at", "INTEGER"),
            _c("setup_type", "TEXT"),
            _c("trigger_seen_at", "INTEGER"),
            _c("updated_at", "INTEGER", not_null=True),
        ),
        indexes=(
            IndexSpec("idx_lbank_stage_lifecycle_updated", ("updated_at",)),
        ),
    ),
    "production_evidence_snapshots": ManagedTableSpec(
        name="production_evidence_snapshots",
        columns=(
            _c("id", "INTEGER", pk=1),
            _c("bucket_started_at", "INTEGER", not_null=True),
            _c("symbol", "TEXT", not_null=True),
            _c("observed_at", "REAL", not_null=True),
            _c("candidate_state", "TEXT"),
            _c("reference_source", "TEXT"),
            _c("reference_price", "REAL"),
            _c("result_valid", "INTEGER", not_null=True),
            _c("suggested_status", "TEXT"),
            _c("score", "REAL"),
            _c("evidence_sha256", "TEXT", not_null=True),
            _c("evidence_zlib", "BLOB", not_null=True),
            _c("uncompressed_bytes", "INTEGER", not_null=True),
            _c("compressed_bytes", "INTEGER", not_null=True),
            _c("has_orderbook", "INTEGER", not_null=True),
            _c("orderbook_bid_levels", "INTEGER", not_null=True),
            _c("orderbook_ask_levels", "INTEGER", not_null=True),
            _c("has_candle_analysis", "INTEGER", not_null=True),
            _c("valid_candle_timeframes", "INTEGER", not_null=True),
            _c("has_derivatives", "INTEGER", not_null=True),
            _c("has_confirmation_source", "INTEGER", not_null=True),
            _c("raw_ohlcv_captured", "INTEGER", not_null=True, default="0"),
            _c("raw_trades_captured", "INTEGER", not_null=True, default="0"),
            _c("source_replay_ready", "INTEGER", not_null=True, default="0"),
            _c("decision_packet_complete", "INTEGER", not_null=True),
            _c("schema_version", "TEXT", not_null=True),
            _c("capture_mode", "TEXT", not_null=True),
            _c("observational_only", "INTEGER", not_null=True, default="1"),
            _c("hard_gating_allowed", "INTEGER", not_null=True, default="0"),
            _c("trade_eligible", "INTEGER"),
            _c("source_ohlcv_captured", "INTEGER", not_null=True, default="0"),
            _c("source_trades_captured", "INTEGER", not_null=True, default="0"),
            _c("source_replay_ready_v2", "INTEGER", not_null=True, default="0"),
            _c("feature_replay_ready_v3", "INTEGER", not_null=True, default="0"),
            _c("triggered_path_replay_ready_v4", "INTEGER", not_null=True, default="0"),
            _c("decision_provenance_ready_v5", "INTEGER", not_null=True, default="0"),
            _c("raw_derivatives_captured_v5", "INTEGER", not_null=True, default="0"),
            _c("production_evidence_complete_v5", "INTEGER", not_null=True, default="0"),
            _c("confirmation_ohlcv_captured_v5", "INTEGER", not_null=True, default="0"),
            _c("code_sha256_v5", "TEXT", not_null=True, default="''"),
        ),
        indexes=(
            IndexSpec("idx_production_evidence_time", ("observed_at",)),
            IndexSpec("idx_production_evidence_symbol", ("symbol", "observed_at")),
        ),
        check_fragments=(
            "check(raw_ohlcv_captured = 0)",
            "check(raw_trades_captured = 0)",
            "check(source_replay_ready = 0)",
            "check(observational_only = 1)",
            "check(hard_gating_allowed = 0)",
            "check(trade_eligible is null)",
            "check(source_ohlcv_captured in (0, 1))",
            "check(source_trades_captured in (0, 1))",
            "check(source_replay_ready_v2 in (0, 1))",
            "check(feature_replay_ready_v3 in (0, 1))",
            "check(triggered_path_replay_ready_v4 in (0, 1))",
            "check(decision_provenance_ready_v5 in (0, 1))",
            "check(raw_derivatives_captured_v5 in (0, 1))",
            "check(production_evidence_complete_v5 in (0, 1))",
            "check(confirmation_ohlcv_captured_v5 in (0, 1))",
        ),
        triggers=(
            TriggerSpec(
                "production_evidence_no_update",
                "UPDATE",
                "production evidence is immutable",
            ),
            TriggerSpec(
                "production_evidence_no_delete",
                "DELETE",
                "production evidence is immutable",
            ),
        ),
    ),
    "production_feature_replay_results_v2": ManagedTableSpec(
        name="production_feature_replay_results_v2",
        columns=(
            _c("id", "INTEGER", pk=1),
            _c("snapshot_id", "INTEGER", not_null=True),
            _c("symbol", "TEXT", not_null=True),
            _c("decision_path", "TEXT", not_null=True, default="'UNKNOWN'"),
            _c("status", "TEXT", not_null=True),
            _c("strategy_equivalent", "INTEGER", not_null=True),
            _c("differences_json", "TEXT", not_null=True),
            _c("replay_version", "TEXT", not_null=True),
            _c("replayed_at", "REAL", not_null=True),
            _c("observational_only", "INTEGER", not_null=True, default="1"),
            _c("hard_gating_allowed", "INTEGER", not_null=True, default="0"),
            _c("trade_eligible", "INTEGER"),
        ),
        indexes=(
            IndexSpec(
                "idx_feature_replay_v2_status",
                ("status", "replayed_at"),
            ),
        ),
        foreign_keys=(
            ForeignKeySpec("snapshot_id", "production_evidence_snapshots", "id"),
        ),
        check_fragments=(
            "check(strategy_equivalent in (0, 1))",
            "check(observational_only = 1)",
            "check(hard_gating_allowed = 0)",
            "check(trade_eligible is null)",
        ),
        triggers=(
            TriggerSpec(
                "production_feature_replay_v2_no_update",
                "UPDATE",
                "feature replay results are immutable",
            ),
            TriggerSpec(
                "production_feature_replay_v2_no_delete",
                "DELETE",
                "feature replay results are immutable",
            ),
        ),
    ),
    "lbank_execution_observations": ManagedTableSpec(
        name="lbank_execution_observations",
        columns=(
            _c("symbol", "TEXT", pk=1),
            _c("observation_status", "TEXT", not_null=True, default="'UNKNOWN'"),
            _c("observed_at", "REAL"),
            _c("reason", "TEXT"),
            _c("spread_pct", "REAL"),
            _c("cost_25_pct", "REAL"),
            _c("cost_50_pct", "REAL"),
            _c("cost_100_pct", "REAL"),
            _c("depth_10bps_min_usdt", "REAL"),
            _c("depth_25bps_min_usdt", "REAL"),
            _c("depth_50bps_min_usdt", "REAL"),
            _c("depth_100bps_min_usdt", "REAL"),
            _c("failures", "INTEGER", not_null=True, default="0"),
            _c("next_check_at", "REAL", not_null=True, default="0"),
            _c("payload", "TEXT", not_null=True, default="'{}'"),
            _c("updated_at", "REAL", not_null=True),
        ),
        indexes=(
            IndexSpec("idx_lbank_execution_queue", ("next_check_at", "observed_at")),
            IndexSpec("idx_lbank_execution_status", ("observation_status",)),
        ),
    ),
    "lbank_execution_observation_history": ManagedTableSpec(
        name="lbank_execution_observation_history",
        columns=(
            _c("id", "INTEGER", pk=1),
            _c("symbol", "TEXT", not_null=True),
            _c("observation_status", "TEXT", not_null=True),
            _c("observed_at", "REAL", not_null=True),
            _c("reason", "TEXT"),
            _c("spread_pct", "REAL"),
            _c("cost_25_pct", "REAL"),
            _c("cost_50_pct", "REAL"),
            _c("cost_100_pct", "REAL"),
            _c("depth_10bps_min_usdt", "REAL"),
            _c("depth_25bps_min_usdt", "REAL"),
            _c("depth_50bps_min_usdt", "REAL"),
            _c("depth_100bps_min_usdt", "REAL"),
            _c("payload", "TEXT", not_null=True, default="'{}'"),
            _c("created_at", "REAL", not_null=True),
        ),
        indexes=(
            IndexSpec(
                "idx_lbank_execution_history_symbol_time",
                ("symbol", "observed_at"),
            ),
            IndexSpec(
                "idx_lbank_execution_history_status_time",
                ("observation_status", "observed_at"),
            ),
            IndexSpec("idx_lbank_execution_history_observed_at", ("observed_at",)),
        ),
    ),
    "lbank_execution_decision_log": ManagedTableSpec(
        name="lbank_execution_decision_log",
        columns=(
            _c("id", "INTEGER", pk=1),
            _c("bucket_started_at", "INTEGER", not_null=True),
            _c("source", "TEXT", not_null=True),
            _c("symbol", "TEXT", not_null=True),
            _c("first_observed_at", "REAL", not_null=True),
            _c("last_observed_at", "REAL", not_null=True),
            _c("evaluation_count", "INTEGER", not_null=True),
            _c("volume_gate_passed", "INTEGER", not_null=True),
            _c("suitability_status", "TEXT", not_null=True),
            _c("suitability_would_admit", "INTEGER"),
            _c("disagreement_kind", "TEXT", not_null=True),
            _c("evidence_status", "TEXT"),
            _c("candidate_state", "TEXT"),
            _c("score", "REAL"),
            _c("scan_eligible", "INTEGER", not_null=True),
            _c("quote_volume", "REAL"),
            _c("last_price", "REAL"),
            _c("observational_only", "INTEGER", not_null=True, default="1"),
            _c("trade_eligible", "INTEGER"),
        ),
        indexes=(
            IndexSpec("idx_lbank_execution_decision_time", ("last_observed_at",)),
            IndexSpec(
                "idx_lbank_execution_decision_comparison",
                ("source", "disagreement_kind", "bucket_started_at"),
            ),
        ),
    ),
    "operational_historical_outcome_datasets": ManagedTableSpec(
        name="operational_historical_outcome_datasets",
        columns=(
            _c("id", "INTEGER", pk=1),
            _c("report_sha256", "TEXT", not_null=True),
            _c("source", "TEXT", not_null=True),
            _c("generated_at", "TEXT"),
            _c("window_start_ms", "INTEGER", not_null=True),
            _c("window_end_ms", "INTEGER", not_null=True),
            _c("days", "INTEGER", not_null=True),
            _c("strategy", "TEXT", not_null=True),
            _c("cost_basis", "TEXT", not_null=True),
            _c("strategy_equivalent", "INTEGER", not_null=True),
            _c("source_provenance_json", "TEXT", not_null=True),
            _c("imported_at", "INTEGER", not_null=True),
            _c("observational_only", "INTEGER", not_null=True, default="1"),
            _c("hard_gating_allowed", "INTEGER", not_null=True, default="0"),
        ),
        check_fragments=(
            "check(strategy_equivalent in (0, 1))",
            "check(observational_only = 1)",
            "check(hard_gating_allowed = 0)",
        ),
        triggers=(
            TriggerSpec(
                "operational_historical_datasets_no_update",
                "UPDATE",
                "operational historical datasets are immutable",
            ),
            TriggerSpec(
                "operational_historical_datasets_no_delete",
                "DELETE",
                "operational historical datasets are immutable",
            ),
        ),
    ),
    "operational_historical_signal_outcomes": ManagedTableSpec(
        name="operational_historical_signal_outcomes",
        columns=(
            _c("id", "INTEGER", pk=1),
            _c("dataset_id", "INTEGER", not_null=True),
            _c("event_key", "TEXT", not_null=True),
            _c("symbol", "TEXT", not_null=True),
            _c("signal_timestamp_ms", "INTEGER", not_null=True),
            _c("exit_timestamp_ms", "INTEGER"),
            _c("outcome", "TEXT", not_null=True),
            _c("gross_realized_r", "REAL"),
            _c("net_realized_r", "REAL", not_null=True),
            _c("exit_reason", "TEXT"),
            _c("cost_basis", "TEXT", not_null=True),
            _c("details_json", "TEXT", not_null=True),
            _c("observational_only", "INTEGER", not_null=True, default="1"),
            _c("trade_eligible", "INTEGER"),
        ),
        indexes=(
            IndexSpec(
                "idx_operational_historical_symbol",
                ("dataset_id", "symbol", "signal_timestamp_ms"),
            ),
        ),
        foreign_keys=(
            ForeignKeySpec(
                "dataset_id",
                "operational_historical_outcome_datasets",
                "id",
            ),
        ),
        check_fragments=(
            "check(observational_only = 1)",
            "check(trade_eligible is null)",
        ),
        triggers=(
            TriggerSpec(
                "operational_historical_outcomes_no_update",
                "UPDATE",
                "operational historical outcomes are immutable",
            ),
            TriggerSpec(
                "operational_historical_outcomes_no_delete",
                "DELETE",
                "operational historical outcomes are immutable",
            ),
        ),
    ),
    "provider_states": ManagedTableSpec(
        name="provider_states",
        columns=(
            _c("provider_id", "TEXT", pk=1),
            _c("upstream_identity", "TEXT", not_null=True),
            _c("status", "TEXT", not_null=True),
            _c("failure_class", "TEXT", not_null=True),
            _c("consecutive_failures", "INTEGER", not_null=True),
            _c("circuit_open_until", "REAL", not_null=True),
            _c("replacement_generation", "INTEGER", not_null=True),
            _c("last_success_at", "REAL", not_null=True),
            _c("updated_at", "REAL", not_null=True),
        ),
    ),
}


_MIGRATION_INFRA_TABLES = frozenset({"schema_migrations", "db_readiness_probe"})


def _sql_literal_marker(value: str) -> str:
    """Return an opaque, case-sensitive marker that cannot contain SQL syntax."""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"\x00s{digest}\x00"


def managed_runtime_table_names() -> frozenset[str]:
    """Return the complete first-party runtime table ownership set."""
    return frozenset(_RUNTIME_SCHEMA)


def _sql_compact(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    compact: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(value):
        character = value[index]
        following = value[index + 1] if index + 1 < len(value) else ""

        if quote is not None:
            compact.append(character if quote == "'" else character.casefold())
            closing = "]" if quote == "[" else quote
            if character == closing:
                if following == closing:
                    compact.append(
                        following if quote == "'" else following.casefold()
                    )
                    index += 2
                    continue
                quote = None
            index += 1
            continue

        if character == "-" and following == "-":
            index += 2
            while index < len(value) and value[index] not in "\r\n":
                index += 1
            continue
        if character == "/" and following == "*":
            comment_end = value.find("*/", index + 2)
            if comment_end < 0:
                return ""
            index = comment_end + 2
            continue
        if character in {"'", '"', "`", "["}:
            quote = character
            compact.append(character)
        elif not character.isspace():
            compact.append(character.casefold())
        index += 1
    return "".join(compact)


def _sql_structure(value: str | None) -> tuple[str, tuple[str, ...]]:
    """Return executable SQL structure with comments and quoted identifiers hidden."""
    if not isinstance(value, str):
        return "", ()

    compact: list[str] = []
    literals: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        following = value[index + 1] if index + 1 < len(value) else ""

        if character == "-" and following == "-":
            index += 2
            while index < len(value) and value[index] not in "\r\n":
                index += 1
            continue
        if character == "/" and following == "*":
            comment_end = value.find("*/", index + 2)
            if comment_end < 0:
                return "", ()
            index = comment_end + 2
            continue
        if character == "'":
            index += 1
            literal: list[str] = []
            closed = False
            while index < len(value):
                if value[index] == "'":
                    if index + 1 < len(value) and value[index + 1] == "'":
                        literal.append("'")
                        index += 2
                        continue
                    index += 1
                    closed = True
                    break
                literal.append(value[index])
                index += 1
            if not closed:
                return "", ()
            literal_value = "".join(literal)
            literals.append(literal_value)
            compact.append(_sql_literal_marker(literal_value))
            continue
        if character in {'"', "`", "["}:
            closing = "]" if character == "[" else character
            index += 1
            closed = False
            while index < len(value):
                if value[index] == closing:
                    if index + 1 < len(value) and value[index + 1] == closing:
                        index += 2
                        continue
                    index += 1
                    closed = True
                    break
                index += 1
            if not closed:
                return "", ()
            compact.append("\x00i\x00")
            continue
        if not character.isspace():
            compact.append(character.casefold())
        index += 1

    return "".join(compact), tuple(literals)


def _check_structures(value: str | None) -> tuple[str, ...]:
    """Return every complete executable CHECK clause in normalized form."""
    structure, _ = _sql_structure(value)
    checks: list[str] = []
    offset = 0
    pattern = re.compile(r"check\(")

    while match := pattern.search(structure, offset):
        start = match.start()
        depth = 0
        cursor = match.end() - 1
        while cursor < len(structure):
            character = structure[cursor]
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    checks.append(structure[start : cursor + 1])
                    offset = cursor + 1
                    break
            cursor += 1
        else:
            checks.append(structure[start:])
            break

    return tuple(checks)


def _sql_unquoted_tokens(value: str | None) -> tuple[str, ...]:
    """Return executable word tokens outside comments and quoted content."""
    if not isinstance(value, str):
        return ()

    tokens: list[str] = []
    token: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        following = value[index + 1] if index + 1 < len(value) else ""

        if character == "-" and following == "-":
            if token:
                tokens.append("".join(token).casefold())
                token.clear()
            index += 2
            while index < len(value) and value[index] not in "\r\n":
                index += 1
            continue
        if character == "/" and following == "*":
            if token:
                tokens.append("".join(token).casefold())
                token.clear()
            comment_end = value.find("*/", index + 2)
            if comment_end < 0:
                return ()
            index = comment_end + 2
            continue
        if character in {"'", '"', "`", "["}:
            if token:
                tokens.append("".join(token).casefold())
                token.clear()
            closing = "]" if character == "[" else character
            index += 1
            closed = False
            while index < len(value):
                if value[index] == closing:
                    if index + 1 < len(value) and value[index + 1] == closing:
                        index += 2
                        continue
                    index += 1
                    closed = True
                    break
                index += 1
            if not closed:
                return ()
            continue
        if character.isalnum() or character == "_":
            token.append(character)
        elif token:
            tokens.append("".join(token).casefold())
            token.clear()
        index += 1

    if token:
        tokens.append("".join(token).casefold())
    return tuple(tokens)


def _default_normalized(value: object) -> str | None:
    if value is None:
        return None
    return str(value).strip()


def _table_sql(conn: sqlite3.Connection, table_name: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    if row is None or not isinstance(row[0], str):
        return None
    return row[0]


def _column_issues(
    conn: sqlite3.Connection,
    spec: ManagedTableSpec,
) -> list[SchemaIssue]:
    rows = conn.execute(f'PRAGMA table_info("{spec.name}")').fetchall()
    actual_names = tuple(str(row[1]) for row in rows)
    expected_names = tuple(column.name for column in spec.columns)
    if set(actual_names) != set(expected_names):
        return [
            SchemaIssue(
                "COLUMN_SET_MISMATCH",
                spec.name,
                f"expected columns {expected_names!r}; found {actual_names!r}",
            )
        ]

    actual = {str(row[1]): row for row in rows}
    issues: list[SchemaIssue] = []
    if "collate" in _sql_unquoted_tokens(_table_sql(conn, spec.name)):
        issues.append(
            SchemaIssue(
                "COLUMN_COLLATION_MISMATCH",
                spec.name,
                "managed columns must use the canonical default collation",
            )
        )
    for column in spec.columns:
        row = actual[column.name]
        declared_type = str(row[2] or "").strip().upper()
        not_null = bool(int(row[3]))
        default = _default_normalized(row[4])
        pk = int(row[5])
        if (
            declared_type != column.declared_type
            or not_null != column.not_null
            or default != column.default
            or pk != column.primary_key_position
        ):
            issues.append(
                SchemaIssue(
                    "COLUMN_CONSTRAINT_MISMATCH",
                    f"{spec.name}.{column.name}",
                    "declared type/null/default/primary-key metadata differs",
                )
            )
    return issues


def _index_issues(
    conn: sqlite3.Connection,
    spec: ManagedTableSpec,
) -> list[SchemaIssue]:
    rows = conn.execute(f'PRAGMA index_list("{spec.name}")').fetchall()
    actual_user_indexes = {
        str(row[1]): row
        for row in rows
        if len(row) < 4 or str(row[3]).casefold() == "c"
    }
    expected_names = {index.name for index in spec.indexes}
    if set(actual_user_indexes) != expected_names:
        return [
            SchemaIssue(
                "INDEX_MISMATCH",
                spec.name,
                f"expected named indexes {sorted(expected_names)!r}; "
                f"found {sorted(actual_user_indexes)!r}",
            )
        ]

    issues: list[SchemaIssue] = []
    for index in spec.indexes:
        index_row = actual_user_indexes[index.name]
        unique = bool(int(index_row[2]))
        partial = bool(int(index_row[4])) if len(index_row) > 4 else False
        key_parts = tuple(
            (
                str(row[2]),
                bool(int(row[3])),
                str(row[4] or "").upper(),
            )
            for row in conn.execute(
                f'PRAGMA index_xinfo("{index.name}")'
            ).fetchall()
            if len(row) < 6 or bool(int(row[5]))
        )
        expected_parts = tuple(
            (column, False, "BINARY") for column in index.columns
        )
        if (
            key_parts != expected_parts
            or unique != index.unique
            or partial
        ):
            issues.append(
                SchemaIssue(
                    "INDEX_MISMATCH",
                    index.name,
                    "index uniqueness, key order, collation, direction, or predicate differs",
                )
            )
    return issues


def _foreign_key_issues(
    conn: sqlite3.Connection,
    spec: ManagedTableSpec,
) -> list[SchemaIssue]:
    actual = {
        (
            str(row[3]),
            str(row[2]),
            str(row[4]),
            str(row[5]).upper(),
            str(row[6]).upper(),
            str(row[7]).upper(),
        )
        for row in conn.execute(f'PRAGMA foreign_key_list("{spec.name}")').fetchall()
    }
    expected = {
        (
            fk.column,
            fk.target_table,
            fk.target_column,
            fk.on_update.upper(),
            fk.on_delete.upper(),
            fk.match.upper(),
        )
        for fk in spec.foreign_keys
    }
    if actual == expected:
        return []
    return [
        SchemaIssue(
            "FOREIGN_KEY_MISMATCH",
            spec.name,
            "foreign-key structure differs from canonical contract",
        )
    ]


def _check_issues(conn: sqlite3.Connection, spec: ManagedTableSpec) -> list[SchemaIssue]:
    expected = Counter(
        _sql_structure(fragment)[0] for fragment in spec.check_fragments
    )
    actual = Counter(_check_structures(_table_sql(conn, spec.name)))
    issues: list[SchemaIssue] = []

    missing = tuple((expected - actual).elements())
    if missing:
        issues.append(
            SchemaIssue(
                "CHECK_MISSING",
                spec.name,
                f"missing critical CHECK constraints: {missing!r}",
            )
        )

    unexpected = tuple((actual - expected).elements())
    if unexpected:
        issues.append(
            SchemaIssue(
                "CHECK_UNEXPECTED",
                spec.name,
                f"unexpected CHECK constraints: {unexpected!r}",
            )
        )

    return issues


def _trigger_is_canonical(
    *,
    table_name: str,
    trigger: TriggerSpec,
    sql: str | None,
) -> bool:
    structure, literals = _sql_structure(sql)
    if not structure:
        return False
    abort_marker = _sql_literal_marker(trigger.abort_message)
    quoted_identifier = re.escape("\x00i\x00")
    trigger_identifier = (
        "(?:" + re.escape(trigger.name.casefold()) + "|" + quoted_identifier + ")"
    )
    table_identifier = (
        "(?:" + re.escape(table_name.casefold()) + "|" + quoted_identifier + ")"
    )
    canonical = (
        r"createtrigger(?:ifnotexists)?"
        + trigger_identifier
        + "before"
        + re.escape(trigger.event.casefold())
        + "on"
        + table_identifier
        + r"beginselectraise\(abort,"
        + re.escape(abort_marker)
        + r"\);end;?"
    )
    return trigger.abort_message in literals and re.fullmatch(canonical, structure) is not None


def _trigger_issues(
    conn: sqlite3.Connection,
    spec: ManagedTableSpec,
) -> list[SchemaIssue]:
    expected_names = {trigger.name for trigger in spec.triggers}
    rows = conn.execute(
        "SELECT name, tbl_name, sql FROM sqlite_master "
        "WHERE type='trigger' AND tbl_name=?",
        (spec.name,),
    ).fetchall()
    actual = {str(row[0]): row for row in rows}
    if set(actual) != expected_names:
        return [
            SchemaIssue(
                "TRIGGER_MISMATCH",
                spec.name,
                f"expected triggers {sorted(expected_names)!r}; found {sorted(actual)!r}",
            )
        ]

    issues: list[SchemaIssue] = []
    for trigger in spec.triggers:
        row = actual[trigger.name]
        if str(row[1]) != spec.name or not _trigger_is_canonical(
            table_name=spec.name,
            trigger=trigger,
            sql=row[2],
        ):
            issues.append(
                SchemaIssue(
                    "TRIGGER_MISMATCH",
                    trigger.name,
                    "trigger must be a canonical BEFORE event ABORT guard",
                )
            )
    return issues


def _unknown_user_tables(conn: sqlite3.Connection) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    known = managed_runtime_table_names() | _MIGRATION_INFRA_TABLES
    return tuple(str(row[0]) for row in rows if str(row[0]) not in known)


def managed_runtime_global_object_owners() -> dict[str, tuple[str, str]]:
    """Return reserved index/trigger names and their canonical owners."""
    owners: dict[str, tuple[str, str]] = {}
    for table_name, spec in _RUNTIME_SCHEMA.items():
        for index in spec.indexes:
            owners[index.name] = ("index", table_name)
        for trigger in spec.triggers:
            owners[trigger.name] = ("trigger", table_name)
    return owners


def verify_managed_schema_connection(
    conn: sqlite3.Connection,
    *,
    required_tables: frozenset[str] | None = None,
    allow_missing_tables: frozenset[str] = frozenset(),
    check_user_version: int | None = None,
) -> SchemaVerificationResult:
    """Inspect managed schema metadata without mutating the SQLite connection."""
    selected = managed_runtime_table_names() if required_tables is None else required_tables
    unknown_requested = set(selected) - managed_runtime_table_names()
    if unknown_requested:
        raise ValueError(f"unknown managed table names: {sorted(unknown_requested)!r}")
    unknown_allowed = set(allow_missing_tables) - managed_runtime_table_names()
    if unknown_allowed:
        raise ValueError(f"unknown optional table names: {sorted(unknown_allowed)!r}")

    issues: list[SchemaIssue] = []
    user_version_row = conn.execute("PRAGMA user_version").fetchone()
    user_version = int(user_version_row[0]) if user_version_row else None
    if check_user_version is not None and user_version != int(check_user_version):
        issues.append(
            SchemaIssue(
                "USER_VERSION_MISMATCH",
                "PRAGMA user_version",
                f"expected {int(check_user_version)}; found {user_version}",
            )
        )

    existing = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for table_name in sorted(selected):
        if table_name not in existing:
            if table_name not in allow_missing_tables:
                issues.append(
                    SchemaIssue(
                        "TABLE_MISSING",
                        table_name,
                        "managed table is absent",
                    )
                )
            continue

        spec = _RUNTIME_SCHEMA[table_name]
        issues.extend(_column_issues(conn, spec))
        issues.extend(_index_issues(conn, spec))
        issues.extend(_foreign_key_issues(conn, spec))
        issues.extend(_check_issues(conn, spec))
        issues.extend(_trigger_issues(conn, spec))

    unique_result = verify_unique_constraints_connection(
        conn,
        tables=frozenset(selected),
    )
    for unique_issue in unique_result.issues:
        issues.append(
            SchemaIssue(
                "UNIQUE_KEY_MISMATCH",
                unique_issue.table,
                f"expected unique keys {unique_issue.expected!r}; "
                f"found {unique_issue.actual!r}; {unique_issue.detail}",
            )
        )

    return SchemaVerificationResult(
        valid=not issues,
        user_version=user_version,
        issues=tuple(issues),
        unknown_user_objects=_unknown_user_tables(conn),
    )


def verify_managed_schema(
    db_path: str | Path,
    *,
    required_tables: frozenset[str] | None = None,
    allow_missing_tables: frozenset[str] = frozenset(),
    check_user_version: int | None = None,
    busy_timeout_ms: int = 5_000,
) -> SchemaVerificationResult:
    """Open an existing database read-only and inspect its managed schema."""
    path = Path(db_path)
    if not path.is_file():
        raise SchemaContractError("database does not exist")
    if busy_timeout_ms < 0:
        raise ValueError("busy_timeout_ms must be non-negative")
    uri = f"{path.resolve().as_uri()}?mode=ro"
    timeout_seconds = max(busy_timeout_ms / 1_000.0, 0.001)
    try:
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=timeout_seconds,
            isolation_level=None,
        )
    except sqlite3.Error as exc:
        raise SchemaContractError("database open failed") from exc
    try:
        conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        return verify_managed_schema_connection(
            conn,
            required_tables=required_tables,
            allow_missing_tables=allow_missing_tables,
            check_user_version=check_user_version,
        )
    except sqlite3.Error as exc:
        raise SchemaContractError("schema metadata is unreadable") from exc
    finally:
        conn.close()


def _raise_for_result(result: SchemaVerificationResult) -> None:
    if result.valid:
        return
    summary = "; ".join(
        f"{issue.code}:{issue.object_name}" for issue in result.issues
    )
    raise SchemaContractError(f"managed schema verification failed: {summary}")


def require_managed_schema_connection(
    conn: sqlite3.Connection,
    *,
    required_tables: frozenset[str] | None = None,
    allow_missing_tables: frozenset[str] = frozenset(),
    check_user_version: int | None = None,
) -> SchemaVerificationResult:
    """Require a valid managed schema on an existing SQLite connection."""
    result = verify_managed_schema_connection(
        conn,
        required_tables=required_tables,
        allow_missing_tables=allow_missing_tables,
        check_user_version=check_user_version,
    )
    _raise_for_result(result)
    return result


def require_managed_schema(
    db_path: str | Path,
    *,
    required_tables: frozenset[str] | None = None,
    allow_missing_tables: frozenset[str] = frozenset(),
    check_user_version: int | None = None,
    busy_timeout_ms: int = 5_000,
) -> SchemaVerificationResult:
    """Require a valid managed schema while opening the database read-only."""
    result = verify_managed_schema(
        db_path,
        required_tables=required_tables,
        allow_missing_tables=allow_missing_tables,
        check_user_version=check_user_version,
        busy_timeout_ms=busy_timeout_ms,
    )
    _raise_for_result(result)
    return result
