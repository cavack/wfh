import logging
import asyncio
import traceback
import json
import time
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
import os

from waterfallhunter.config import settings
from waterfallhunter.core.db import DBAdapter
from waterfallhunter.discovery.lbank_scanner import LBankCatalogScanner
from waterfallhunter.discovery.dexscreener import DexScreenerClient
from waterfallhunter.discovery.onchain import OnChainIntelligence
from waterfallhunter.core.multi_exchange_validator import MultiExchangeValidator
from waterfallhunter.core.notifier import TelegramNotifier
from waterfallhunter.core.ai_veto import AIVetoEngine
from waterfallhunter.core.risk_manager import get_leverage
from waterfallhunter.core.dashboard import compact_metrics
from waterfallhunter.core.final_ranking import FinalRanking
from waterfallhunter.core.signal_funnel import SignalFunnel
from waterfallhunter.core.stage_lifecycle import StageLifecycleStore
from waterfallhunter.core.historical_outcome_store import HistoricalOutcomeStore
from waterfallhunter.core.production_evidence import ProductionEvidenceRecorder
from waterfallhunter.core.decision_provenance import build_decision_contract
from waterfallhunter.core.feature_replay import FeatureReplayStore, FeatureReplayWorker
from waterfallhunter.core.lbank_execution_shadow import LBankExecutionShadowWorker
from waterfallhunter.core.lbank_execution_store import LBankExecutionStore
from waterfallhunter.core.lbank_execution_candidate import (
    LBankExecutionCandidateEnricher,
)
from waterfallhunter.core.lbank_execution_decision import (
    LBankExecutionDecisionLogger,
)
from waterfallhunter.core.lbank_signal_ledger import (
    LBankSignalLedger,
)
from waterfallhunter.core.lbank_signal_outcome import (
    LBankSignalOutcomeStore,
    LBankSignalSettlementWorker,
)
from waterfallhunter.routes_execution_suitability import (
    build_execution_suitability_router,
)
from waterfallhunter.routes_execution_outcomes import (
    build_execution_outcome_router,
)
from waterfallhunter.routes_historical_outcomes import (
    build_historical_outcome_router,
)
from waterfallhunter.routes_production_evidence import (
    build_production_evidence_router,
)
from waterfallhunter.routes_feature_replay import build_feature_replay_router
from waterfallhunter.core.lbank_execution_outcome_report import (
    LBankExecutionOutcomeReport,
)

logging.basicConfig(level=settings.log_level)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("WaterfallHunter")


def _signal_alert_allowed(metrics: dict) -> bool:
    return str(metrics.get("strategy_profile") or "") != (
        MultiExchangeValidator.experimental_profile
    )

app = FastAPI(
    title="WaterfallHunter API - Production",
    version="7.5.1-Stable",
)

db = DBAdapter(
    db_path=settings.registry_db_path,
)

stage_lifecycle_store = StageLifecycleStore(
    db_path=db.db_path,
)

historical_outcome_store = HistoricalOutcomeStore(
    db_path=db.db_path,
    cache_ttl_seconds=60.0,
)

production_evidence_recorder = ProductionEvidenceRecorder(
    db_path=db.db_path,
    bucket_seconds=900,
)

feature_replay_store = FeatureReplayStore(
    db_path=db.db_path,
)
feature_replay_worker = FeatureReplayWorker(
    feature_replay_store,
    batch_size=3,
)

app.include_router(
    build_execution_suitability_router(
        db.db_path
    )
)

app.include_router(
    build_historical_outcome_router(
        historical_outcome_store
    )
)

app.include_router(
    build_production_evidence_router(
        production_evidence_recorder
    )
)

app.include_router(
    build_feature_replay_router(
        feature_replay_store
    )
)

app.include_router(
    build_execution_outcome_router(
        db.db_path
    )
)

execution_suitability_enricher = (
    LBankExecutionCandidateEnricher(
        db_path=db.db_path,
        cache_ttl_seconds=60.0,
    )
)

signal_ledger = LBankSignalLedger(
    db_path=db.db_path,
)

signal_outcome_store = LBankSignalOutcomeStore(
    db_path=db.db_path,
)

execution_outcome_report = LBankExecutionOutcomeReport(
    db_path=db.db_path,
)

dex_client = DexScreenerClient(
    enabled=settings.dexscreener_enabled,
    token_map_json=settings.dexscreener_token_map_json,
)

onchain_client = OnChainIntelligence(
    etherscan_api_key=settings.etherscan_api_key,
    solscan_api_key=settings.solscan_api_key,
    large_transfer_usd=settings.onchain_large_transfer_usd,
)

scanner = LBankCatalogScanner(
    db_adapter=db,
    max_price=1.0,
    min_volume_usdt=2_000_000.0,
    dex_client=dex_client,
    onchain_client=onchain_client,
)

execution_decision_logger = (
    LBankExecutionDecisionLogger(
        db_path=db.db_path,
        enricher=execution_suitability_enricher,
        evaluation_bucket_seconds=3600,
        snapshot_interval_seconds=3600,
        retention_days=30,
        volume_gate_min_usdt=(
            scanner.min_volume_usdt
        ),
    )
)

validator = MultiExchangeValidator()

notifier = TelegramNotifier(
    db_adapter=db,
    scanner=scanner,
)

ai_veto = AIVetoEngine()

_hunter_running = False
_hunter_last_completed_at: float | None = None
_hunter_last_progress_at: float | None = None
_lbank_execution_shadow_worker: LBankExecutionShadowWorker | None = None
_signal_settlement_worker: LBankSignalSettlementWorker | None = None
_signal_evidence_metrics_last_refresh = 0.0
_signal_evidence_metrics_lock = asyncio.Lock()
_sse_clients = set()
_background_tasks = set()

if "tracked_candidates" not in globals():
    tracked_candidates = Gauge(
        "waterfall_tracked_candidates",
        "Active candidates currently tracked",
    )

if "catalog_last_refresh" not in globals():
    catalog_last_refresh = Gauge(
        "waterfall_catalog_last_refresh_timestamp",
        "Unix timestamp of the last successful LBank catalog refresh",
    )

if "hunter_last_cycle" not in globals():
    hunter_last_cycle = Gauge(
        "waterfall_hunter_last_cycle_timestamp",
        "Unix timestamp of the last completed hunter cycle",
    )

if "hunter_last_progress" not in globals():
    hunter_last_progress = Gauge(
        "waterfall_hunter_last_progress_timestamp",
        "Unix timestamp of the last hunter loop progress",
    )

if "derivative_packet_outcomes" not in globals():
    derivative_packet_outcomes = Counter(
        "waterfall_derivative_packet_outcomes_total",
        "Complete or incomplete live derivatives packets evaluated by the hunter.",
        (
            "source",
            "outcome",
            "reason",
        ),
    )

if "lbank_execution_shadow_enabled_metric" not in globals():
    lbank_execution_shadow_enabled_metric = Gauge(
        "waterfall_lbank_execution_shadow_enabled",
        "Whether LBank execution shadow observation is enabled.",
    )

if "lbank_execution_shadow_attempted_metric" not in globals():
    lbank_execution_shadow_attempted_metric = Gauge(
        "waterfall_lbank_execution_shadow_attempted_total",
        "Total LBank shadow observations attempted since process start.",
    )

if "lbank_execution_shadow_observed_metric" not in globals():
    lbank_execution_shadow_observed_metric = Gauge(
        "waterfall_lbank_execution_shadow_observed_total",
        "Total successful LBank shadow observations since process start.",
    )

if "lbank_execution_shadow_unavailable_metric" not in globals():
    lbank_execution_shadow_unavailable_metric = Gauge(
        "waterfall_lbank_execution_shadow_unavailable_total",
        "Total unavailable LBank shadow observations since process start.",
    )

if "lbank_execution_shadow_last_progress_metric" not in globals():
    lbank_execution_shadow_last_progress_metric = Gauge(
        "waterfall_lbank_execution_shadow_last_progress_timestamp",
        "Unix timestamp of the last LBank shadow worker progress.",
    )

if "signal_ledger_metric" not in globals():
    signal_ledger_metric = Gauge(
        "waterfall_signal_ledger_total",
        "Immutable natural production signals captured by the ledger.",
    )

if "signal_outcome_metric" not in globals():
    signal_outcome_metric = Gauge(
        "waterfall_signal_outcomes_total",
        "Append-only 24h observational signal outcomes.",
    )

if "signal_mature_pending_metric" not in globals():
    signal_mature_pending_metric = Gauge(
        "waterfall_signal_mature_pending_total",
        "Mature natural signals still awaiting an observational outcome.",
    )

if "signal_decisive_outcome_metric" not in globals():
    signal_decisive_outcome_metric = Gauge(
        "waterfall_signal_decisive_outcomes_total",
        "Outcomes usable for observational execution-suitability comparison.",
    )

if "signal_evidence_ready_metric" not in globals():
    signal_evidence_ready_metric = Gauge(
        "waterfall_signal_evidence_ready",
        "Whether outcome evidence is sufficient for observational comparison only.",
    )

if "signal_evidence_span_metric" not in globals():
    signal_evidence_span_metric = Gauge(
        "waterfall_signal_evidence_span_days",
        "Observation span in days across decisive signal outcomes.",
    )

if "signal_settlement_coverage_metric" not in globals():
    signal_settlement_coverage_metric = Gauge(
        "waterfall_signal_settlement_coverage_ratio",
        "Settled share of mature signals; NaN when no signal is mature.",
    )

if "signal_oldest_mature_pending_age_metric" not in globals():
    signal_oldest_mature_pending_age_metric = Gauge(
        "waterfall_signal_oldest_mature_pending_age_seconds",
        "Age beyond maturity of the oldest signal awaiting settlement; NaN when empty.",
    )

if "signal_settlement_worker_running_metric" not in globals():
    signal_settlement_worker_running_metric = Gauge(
        "waterfall_signal_settlement_worker_running",
        "Whether the observational signal settlement worker is running.",
    )

if "signal_settlement_cycles_metric" not in globals():
    signal_settlement_cycles_metric = Gauge(
        "waterfall_signal_settlement_cycles_total",
        "Signal settlement cycles attempted since process start.",
    )

if "signal_settlement_failures_metric" not in globals():
    signal_settlement_failures_metric = Gauge(
        "waterfall_signal_settlement_failures_total",
        "Signal settlement cycles failed since process start.",
    )

if "signal_settlement_last_completed_metric" not in globals():
    signal_settlement_last_completed_metric = Gauge(
        "waterfall_signal_settlement_last_completed_timestamp",
        "Unix timestamp of the last completed signal settlement cycle.",
    )

if "signal_settlement_last_error_metric" not in globals():
    signal_settlement_last_error_metric = Gauge(
        "waterfall_signal_settlement_last_error_timestamp",
        "Unix timestamp of the last failed signal settlement cycle; zero when none.",
    )

if "signal_proxy_execution_metric" not in globals():
    signal_proxy_execution_metric = Gauge(
        "waterfall_signal_proxy_execution_total",
        "Natural signals by bounded trigger-time volume/execution comparison.",
        ("comparison",),
    )

if "signal_proxy_execution_decisive_metric" not in globals():
    signal_proxy_execution_decisive_metric = Gauge(
        "waterfall_signal_proxy_execution_decisive_outcomes_total",
        "Decisive outcomes by bounded trigger-time volume/execution comparison.",
        ("comparison",),
    )

if "candidate_state_metric" not in globals():
    candidate_state_metric = Gauge(
        "waterfall_candidate_state_total",
        "Current scan-eligible candidates by bounded lifecycle state.",
        ("state",),
    )

_CANDIDATE_METRIC_STATES = (
    "WATCH",
    "FUEL-RICH",
    "PRE-TRIGGER",
    "ARMED",
    "TRIGGERED",
)

_PROXY_EXECUTION_METRIC_COMPARISONS = (
    "AGREE_ACCEPT",
    "AGREE_REJECT",
    "VOLUME_PASS_EXECUTION_REJECT",
    "VOLUME_REJECT_EXECUTION_ACCEPT",
    "UNKNOWN",
)

_DERIVATIVE_METRIC_SOURCES = frozenset(
    {
        "binance",
        "bybit",
        "kucoin",
        "okx",
        "mexc",
        "bingx",
        "gateio",
        "bitget",
        "htx",
    }
)


def derivative_packet_metric_labels(
    packet: dict | None,
) -> dict[str, str]:
    """Return bounded Prometheus labels for a normalized derivative packet."""

    packet = (
        packet
        if isinstance(
            packet,
            dict,
        )
        else {}
    )

    source = str(
        packet.get(
            "source_exchange"
        )
        or ""
    ).lower()

    source = (
        source
        if source in _DERIVATIVE_METRIC_SOURCES
        else "unknown"
    )

    if packet.get(
        "available"
    ) is True:
        return {
            "source": source,
            "outcome": "complete",
            "reason": "none",
        }

    reason = str(
        packet.get(
            "reason"
        )
        or ""
    ).lower()

    reason_codes = (
        (
            "missing valid funding rate",
            "missing_funding_rate",
        ),
        (
            "missing valid open interest",
            "missing_open_interest",
        ),
        (
            "missing valid taker buy/sell ratio",
            "missing_taker_buy_sell_ratio",
        ),
        (
            "missing valid top trader",
            "missing_top_trader_ratio",
        ),
        (
            "invalid derivatives retrieval timestamp",
            "invalid_retrieval_timestamp",
        ),
        (
            "stale",
            "stale_data",
        ),
        (
            "unsupported derivatives source",
            "unsupported_source",
        ),
        (
            "no complete live derivatives data source",
            "no_complete_source",
        ),
        (
            "source unavailable",
            "source_unavailable",
        ),
    )

    reason_code = next(
        (
            code
            for needle, code
            in reason_codes
            if needle in reason
        ),
        "other",
    )

    return {
        "source": source,
        "outcome": "incomplete",
        "reason": reason_code,
    }


def _record_derivative_packet_outcome(
    metrics: dict | None,
) -> None:
    if not isinstance(
        metrics,
        dict,
    ):
        return

    packet = metrics.get(
        "derivatives"
    )

    if not isinstance(
        packet,
        dict,
    ):
        return

    derivative_packet_outcomes.labels(
        **derivative_packet_metric_labels(
            packet
        )
    ).inc()


def _start_background_task(
    coro,
):
    """Track long-lived tasks so shutdown can cancel them cleanly."""

    task = asyncio.create_task(
        coro
    )

    _background_tasks.add(
        task
    )

    task.add_done_callback(
        _background_tasks.discard
    )

    return task


def _build_lbank_execution_shadow_worker(
) -> LBankExecutionShadowWorker | None:
    if not settings.lbank_execution_shadow_enabled:
        return None

    store = LBankExecutionStore(
        db_path=db.db_path
    )

    return LBankExecutionShadowWorker(
        store,
        batch_size=(
            settings
            .lbank_execution_shadow_batch_size
        ),
        success_recheck_seconds=(
            settings
            .lbank_execution_shadow_success_recheck_seconds
        ),
        failure_recheck_seconds=(
            settings
            .lbank_execution_shadow_failure_recheck_seconds
        ),
    )


def _lbank_shadow_health_snapshot() -> dict:
    if _lbank_execution_shadow_worker is None:
        return {
            "enabled": False,
            "running": False,
            "batch_size": None,
            "last_started_at": None,
            "last_progress_at": None,
            "last_completed_at": None,
            "total_attempted": 0,
            "total_observed": 0,
            "total_unavailable": 0,
        }

    return {
        "enabled": True,
        **(
            _lbank_execution_shadow_worker
            .health_snapshot()
        ),
    }


async def _fetch_signal_outcome_candles(
    signal: dict,
    start_ms: int,
    end_ms: int,
) -> list:
    try:
        trigger_metrics = json.loads(
            signal.get(
                "trigger_metrics_json"
            )
            or "{}"
        )
    except (
        TypeError,
        json.JSONDecodeError,
    ):
        return []

    exchange_name = trigger_metrics.get(
        "exchange"
    )
    mapped_symbol = trigger_metrics.get(
        "mapped_symbol"
    )
    if not exchange_name or not mapped_symbol:
        return []

    rows_by_timestamp: dict[int, list] = {}
    cursor = int(start_ms)

    for _ in range(20):
        packet = await (
            validator.gateway
            .fetch_ohlcv_from_source(
                str(exchange_name),
                str(mapped_symbol),
                timeframe="1m",
                since=cursor,
                limit=1000,
            )
        )
        rows = packet.get("data") or []
        if not rows:
            break

        last_timestamp = None
        for row in rows:
            try:
                timestamp = int(row[0])
            except (
                IndexError,
                TypeError,
                ValueError,
            ):
                continue
            if start_ms <= timestamp < end_ms:
                rows_by_timestamp[timestamp] = row
            if (
                last_timestamp is None
                or timestamp > last_timestamp
            ):
                last_timestamp = timestamp

        if last_timestamp is None:
            break
        next_cursor = last_timestamp + 60_000
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if cursor >= end_ms:
            break

    return [
        rows_by_timestamp[timestamp]
        for timestamp in sorted(
            rows_by_timestamp
        )
    ]


def _build_signal_settlement_worker(
) -> LBankSignalSettlementWorker:
    return LBankSignalSettlementWorker(
        signal_outcome_store,
        _fetch_signal_outcome_candles,
        horizon_seconds=86400,
        close_delay_seconds=120,
        batch_size=3,
    )


def _update_lbank_shadow_metrics() -> None:
    snapshot = (
        _lbank_shadow_health_snapshot()
    )

    lbank_execution_shadow_enabled_metric.set(
        1.0
        if snapshot[
            "enabled"
        ]
        else 0.0
    )

    lbank_execution_shadow_attempted_metric.set(
        float(
            snapshot.get(
                "total_attempted"
            )
            or 0
        )
    )

    lbank_execution_shadow_observed_metric.set(
        float(
            snapshot.get(
                "total_observed"
            )
            or 0
        )
    )

    lbank_execution_shadow_unavailable_metric.set(
        float(
            snapshot.get(
                "total_unavailable"
            )
            or 0
        )
    )

    last_progress = snapshot.get(
        "last_progress_at"
    )

    if isinstance(
        last_progress,
        (
            int,
            float,
        ),
    ):
        lbank_execution_shadow_last_progress_metric.set(
            float(
                last_progress
            )
        )


def _update_candidate_state_metrics(
    candidates: dict,
) -> None:
    counts = {
        state: 0
        for state in _CANDIDATE_METRIC_STATES
    }
    for candidate in candidates.values():
        if not isinstance(candidate, dict):
            continue
        state = str(
            candidate.get("status")
            or ""
        )
        if state in counts:
            counts[state] += 1
    for state, value in counts.items():
        candidate_state_metric.labels(
            state=state
        ).set(value)


def _update_signal_settlement_worker_metrics() -> None:
    snapshot = (
        _signal_settlement_worker.health_snapshot()
        if _signal_settlement_worker is not None
        else {}
    )
    signal_settlement_worker_running_metric.set(
        1.0 if snapshot.get("running") is True else 0.0
    )
    signal_settlement_cycles_metric.set(
        float(snapshot.get("total_cycles") or 0)
    )
    signal_settlement_failures_metric.set(
        float(snapshot.get("total_failures") or 0)
    )
    signal_settlement_last_completed_metric.set(
        float(snapshot.get("last_completed_at") or 0.0)
    )
    signal_settlement_last_error_metric.set(
        float(snapshot.get("last_error_at") or 0.0)
    )


async def _update_signal_evidence_metrics(
    *,
    force: bool = False,
) -> None:
    global _signal_evidence_metrics_last_refresh

    now = time.monotonic()
    if (
        not force
        and now
        - _signal_evidence_metrics_last_refresh
        < 60.0
    ):
        return

    async with _signal_evidence_metrics_lock:
        now = time.monotonic()
        if (
            not force
            and now
            - _signal_evidence_metrics_last_refresh
            < 60.0
        ):
            return

        report = await asyncio.to_thread(
            execution_outcome_report.build_report
        )
        settlement = report.get("settlement") or {}
        evidence = report.get("evidence") or {}
        proxy_execution = (
            report.get("by_proxy_execution_comparison")
            or {}
        )

        signal_ledger_metric.set(
            float(settlement.get("signal_count") or 0)
        )
        signal_outcome_metric.set(
            float(settlement.get("settled_outcome_count") or 0)
        )
        signal_mature_pending_metric.set(
            float(
                settlement.get(
                    "unsettled_mature_signal_count"
                )
                or 0
            )
        )
        signal_decisive_outcome_metric.set(
            float(evidence.get("decisive_outcome_count") or 0)
        )
        signal_evidence_ready_metric.set(
            1.0
            if evidence.get("ready") is True
            else 0.0
        )
        signal_evidence_span_metric.set(
            float(evidence.get("observation_span_days") or 0.0)
        )
        coverage = settlement.get(
            "mature_settlement_coverage_rate"
        )
        signal_settlement_coverage_metric.set(
            float(coverage)
            if isinstance(coverage, (int, float))
            and not isinstance(coverage, bool)
            else float("nan")
        )
        oldest_pending_age = settlement.get(
            "oldest_unsettled_mature_age_seconds"
        )
        signal_oldest_mature_pending_age_metric.set(
            float(oldest_pending_age)
            if isinstance(oldest_pending_age, (int, float))
            and not isinstance(oldest_pending_age, bool)
            else float("nan")
        )
        for comparison in _PROXY_EXECUTION_METRIC_COMPARISONS:
            group = proxy_execution.get(comparison) or {}
            signal_proxy_execution_metric.labels(
                comparison=comparison
            ).set(float(group.get("signal_count") or 0))
            signal_proxy_execution_decisive_metric.labels(
                comparison=comparison
            ).set(
                float(group.get("decisive_outcome_count") or 0)
            )
        _signal_evidence_metrics_last_refresh = now


def _store_live_metrics(
    symbol: str,
    metrics: dict | None,
):
    normalized = (
        dict(
            metrics
        )
        if isinstance(
            metrics,
            dict,
        )
        else {}
    )

    if (
        normalized.get(
            "score"
        )
        is None
        and not normalized.get(
            "analysis_reason"
        )
    ):
        normalized[
            "analysis_reason"
        ] = str(
            normalized.get(
                "error"
            )
            or "live analysis unavailable"
        )

    scanner.active_candidates.setdefault(
        symbol,
        {},
    )[
        "metrics"
    ] = (
        compact_metrics(
            normalized
        )
        or {}
    )


def get_formatted_candidates():
    now = time.time()

    active_from_db = (
        db.get_all_active_candidates()
    )

    historical_by_symbol = (
        historical_outcome_store.symbol_summaries()
    )

    for (
        symbol,
        data,
    ) in active_from_db.items():
        live_data = (
            scanner
            .active_candidates
            .get(
                symbol,
                {},
            )
        )

        if live_data:
            (
                price,
                observed_at,
            ) = (
                scanner
                .get_live_reference(
                    symbol
                )
            )

            is_live = (
                price is not None
                and observed_at is not None
            )

            data[
                "observed_at"
            ] = observed_at

            data[
                "age_seconds"
            ] = (
                round(
                    now
                    - observed_at,
                    1,
                )
                if observed_at is not None
                else None
            )

            data[
                "score"
            ] = (
                live_data.get(
                    "score"
                )
                if is_live
                else None
            )

            live_metrics = live_data.get(
                "metrics"
            )

            data[
                "metrics"
            ] = (
                (
                    compact_metrics(
                        live_metrics
                    )
                    if isinstance(
                        live_metrics,
                        dict,
                    )
                    else {
                        "analysis_reason": (
                            "live analysis pending"
                        )
                    }
                )
                if is_live
                else None
            )

            data[
                "last_price"
            ] = (
                price
                if is_live
                else None
            )

            data[
                "quote_volume"
            ] = (
                live_data.get(
                    "quote_volume"
                )
                if is_live
                else None
            )

            data[
                "data_status"
            ] = (
                "live"
                if is_live
                else "unavailable"
            )

            data[
                "analysis_status"
            ] = (
                live_data.get(
                    "analysis_status",
                    (
                        "ready"
                        if data[
                            "score"
                        ]
                        is not None
                        else "pending"
                    ),
                )
                if is_live
                else "unavailable"
            )

            data[
                "dex_context"
            ] = (
                live_data.get(
                    "dex_context"
                )
                if is_live
                else None
            )

            data[
                "onchain_context"
            ] = (
                live_data.get(
                    "onchain_context"
                )
                if is_live
                else None
            )

        else:
            data[
                "last_price"
            ] = None

            data[
                "quote_volume"
            ] = None

            data[
                "observed_at"
            ] = None

            data[
                "age_seconds"
            ] = None

            data[
                "score"
            ] = None

            data[
                "metrics"
            ] = None

            data[
                "data_status"
            ] = "unavailable"

            data[
                "analysis_status"
            ] = "unavailable"

            data[
                "dex_context"
            ] = None

            data[
                "onchain_context"
            ] = None

        data[
            "execution_suitability"
        ] = (
            execution_suitability_enricher
            .for_symbol(
                symbol
            )
        )

        data["historical_outcome"] = (
            historical_by_symbol.get(symbol)
            or {
                "available": False,
                "evidence_source": "historical_backfill",
                "ranking_eligible": False,
            }
        )

        data.pop(
            "trigger_data",
            None,
        )

    final_ranking = FinalRanking.rank(
        active_from_db,
        limit=3,
    )

    signal_funnel = SignalFunnel.build(
        active_from_db,
        generated_at=now,
    )

    ranking_by_symbol = {
        packet["symbol"]: packet
        for packet in final_ranking["all"]
    }

    for symbol, data in active_from_db.items():
        data["final_ranking"] = ranking_by_symbol[symbol]

    sorted_candidates = {
        key: value
        for key, value
        in sorted(
            active_from_db.items(),
            key=lambda item: (
                item[1].get(
                    "score"
                )
                if item[1].get(
                    "score"
                )
                is not None
                else -1
            ),
            reverse=True,
        )
    }

    return {
        "total": len(
            sorted_candidates
        ),
        "candidates": (
            sorted_candidates
        ),
        "final_ranking": {
            key: value
            for key, value in final_ranking.items()
            if key != "all"
        },
        "signal_funnel": signal_funnel,
    }


async def sse_broadcaster():
    while _hunter_running:
        if _sse_clients:
            data = (
                get_formatted_candidates()
            )

            msg = (
                f"data: "
                f"{json.dumps(data)}"
                f"\n\n"
            )

            for q in list(
                _sse_clients
            ):
                try:
                    q.put_nowait(
                        msg
                    )
                except asyncio.QueueFull:
                    pass

        await asyncio.sleep(
            1.0
        )


async def evaluate_candidate(
    symbol: str,
    data: dict,
):
    scanner.active_candidates.setdefault(
        symbol,
        {},
    )[
        "analysis_status"
    ] = "pending"

    (
        lbank_price,
        reference_observed_at,
    ) = scanner.get_live_reference(
        symbol
    )

    current_state = data[
        "status"
    ]

    execution_decision_logger.observe_evaluation(
        symbol,
        volume_gate_passed=bool(
            execution_decision_logger
            .volume_gate_passes(
                data.get(
                    "quote_volume"
                )
            )
        ),
        scan_eligible=bool(
            data.get(
                "scan_eligible"
            )
        ),
        candidate_state=str(
            current_state
        ),
        score=data.get(
            "score"
        ),
        quote_volume=data.get(
            "quote_volume"
        ),
        last_price=data.get(
            "last_price"
        ),
    )

    reference_source = "lbank"

    decision_contract = build_decision_contract(
        app_version=app.version,
        validator=validator,
        settings=settings,
        recorder_bucket_seconds=(
            production_evidence_recorder.bucket_seconds
        ),
    )

    if lbank_price is None:
        fallback_reference = (
            await validator
            .resolve_live_reference(
                symbol
            )
        )

        if not fallback_reference:
            production_evidence_recorder.record(
                symbol,
                candidate_state=str(current_state),
                reference_source=None,
                reference_price=None,
                result={
                    "is_valid": False,
                    "score": None,
                    "suggested_status": "REJECTED",
                    "metrics": {"error": "no fresh reference price in exchange waterfall"},
                },
                decision_contract=decision_contract,
            )
            scanner.active_candidates.setdefault(
                symbol,
                {},
            )[
                "score"
            ] = None

            scanner.active_candidates[
                symbol
            ][
                "analysis_status"
            ] = "unavailable"

            _store_live_metrics(
                symbol,
                {
                    "error": (
                        "no fresh reference price "
                        "in exchange waterfall"
                    )
                },
            )

            if current_state in {
                "FUEL-RICH",
                "PRE-TRIGGER",
                "ARMED",
                "TRIGGERED",
            }:
                db.update_candidate_state(
                    symbol,
                    "WATCH",
                )

            return

        lbank_price = (
            fallback_reference[
                "price"
            ]
        )

        reference_source = (
            fallback_reference[
                "exchange"
            ]
        )

        live_data = (
            scanner
            .active_candidates
            .setdefault(
                symbol,
                {},
            )
        )

        live_data[
            "last_price"
        ] = lbank_price

        live_data[
            "reference_observed_at"
        ] = time.time()

        live_data[
            "reference_source"
        ] = reference_source

        if (
            fallback_reference[
                "quote_volume"
            ]
            is not None
        ):
            live_data[
                "quote_volume"
            ] = (
                fallback_reference[
                    "quote_volume"
                ]
            )

    result = (
        await validator
        .cross_check_symbol(
            symbol,
            lbank_price,
            reference_source=(
                reference_source
            ),
        )
    )

    result_metrics = result.setdefault(
        "metrics",
        {},
    )
    snapshot_stages = result_metrics.get(
        "strategy_stages"
    )
    if isinstance(snapshot_stages, dict):
        result_metrics["snapshot_stage_chain"] = {
            "version": "snapshot_stage_chain_v1",
            "passed": snapshot_stages.get("passed") is True,
            "observational_only": True,
            "hard_gating_allowed": False,
        }
        result_metrics["stage_lifecycle"] = (
            stage_lifecycle_store.advance(
                symbol,
                int(data.get("lifecycle_id") or 1),
                snapshot_stages,
            )
        )

    def record_final_production_decision(
        path: str,
        reason: str,
        **details,
    ) -> None:
        result_metrics = result.setdefault(
            "metrics",
            {},
        )
        result_metrics[
            "production_decision"
        ] = {
            "final": True,
            "path": str(path),
            "reason": str(reason),
            "recorded_after_persistence": (
                path == "TRIGGERED"
            ),
            **details,
        }
        production_evidence_recorder.record(
            symbol,
            candidate_state=str(current_state),
            reference_source=reference_source,
            reference_price=lbank_price,
            result=result,
            decision_contract=decision_contract,
        )

    production_evidence_recorder.record(
        symbol,
        candidate_state=str(current_state),
        reference_source=reference_source,
        reference_price=lbank_price,
        result=result,
        decision_contract=decision_contract,
    )

    _record_derivative_packet_outcome(
        result.get(
            "metrics"
        )
    )

    if not result[
        "is_valid"
    ]:
        stored_metrics = (
            result.get(
                "metrics"
            )
            or {
                "error": (
                    "live validation unavailable"
                )
            }
        )

        stored_metrics[
            "analysis_reason"
        ] = str(
            stored_metrics.get(
                "analysis_reason"
            )
            or stored_metrics.get(
                "error"
            )
            or "live validation unavailable"
        )

        observation_status = (
            result.get(
                "observation_status"
            )
        )

        observation_score = (
            result.get(
                "observation_score"
            )
        )

        if observation_status in {
            "WATCH",
            "FUEL-RICH",
            "PRE-TRIGGER",
        }:
            live = (
                scanner
                .active_candidates
                .setdefault(
                    symbol,
                    {},
                )
            )

            live[
                "score"
            ] = observation_score

            live[
                "analysis_status"
            ] = "observed"

            stored_metrics[
                "observation_status"
            ] = observation_status

            stored_metrics[
                "observation_score"
            ] = observation_score

            stored_metrics[
                "trade_eligible"
            ] = False

            if (
                current_state
                != observation_status
            ):
                if not db.update_candidate_state(
                    symbol,
                    observation_status,
                ):
                    logger.error(
                        "Candidate observation state "
                        "persistence failed for %s -> %s",
                        symbol,
                        observation_status,
                    )

            observation_exchange = (
                stored_metrics.get(
                    "exchange"
                )
            )

            observation_symbol = (
                stored_metrics.get(
                    "mapped_symbol"
                )
            )

            if (
                observation_exchange
                and observation_symbol
            ):
                validator.ws_manager.unsubscribe(
                    observation_exchange,
                    observation_symbol,
                )

        else:
            scanner.active_candidates.setdefault(
                symbol,
                {},
            )[
                "score"
            ] = None

            scanner.active_candidates[
                symbol
            ][
                "analysis_status"
            ] = "unavailable"

            if current_state in {
                "FUEL-RICH",
                "PRE-TRIGGER",
                "ARMED",
                "TRIGGERED",
            }:
                db.update_candidate_state(
                    symbol,
                    "WATCH",
                )

        if data.get(
            "dex_context"
        ):
            stored_metrics[
                "dex_context"
            ] = data[
                "dex_context"
            ]

        if data.get(
            "onchain_context"
        ):
            stored_metrics[
                "onchain_context"
            ] = data[
                "onchain_context"
            ]

        _store_live_metrics(
            symbol,
            stored_metrics,
        )

        return

    score = result[
        "score"
    ]

    new_state = result[
        "suggested_status"
    ]

    metrics = result[
        "metrics"
    ]

    if data.get(
        "dex_context"
    ):
        metrics[
            "dex_context"
        ] = data[
            "dex_context"
        ]

    if data.get(
        "onchain_context"
    ):
        metrics[
            "onchain_context"
        ] = data[
            "onchain_context"
        ]

    ex_name = metrics.get(
        "exchange"
    )

    mapped_sym = metrics.get(
        "mapped_symbol"
    )

    if (
        symbol
        not in scanner.active_candidates
    ):
        scanner.active_candidates[
            symbol
        ] = {}

    scanner.active_candidates[
        symbol
    ][
        "score"
    ] = score

    scanner.active_candidates[
        symbol
    ][
        "analysis_status"
    ] = "ready"

    _store_live_metrics(
        symbol,
        metrics,
    )

    observational_states = {
        "WATCH",
        "FUEL-RICH",
        "PRE-TRIGGER",
        "ARMED",
    }

    if (
        new_state
        in observational_states
    ):
        if (
            current_state
            != new_state
        ):
            if not db.update_candidate_state(
                symbol,
                new_state,
            ):
                logger.error(
                    "Candidate state persistence "
                    "failed for %s -> %s",
                    symbol,
                    new_state,
                )
                return

        if new_state == "ARMED":
            validator.ws_manager.subscribe(
                ex_name,
                mapped_sym,
            )
        else:
            validator.ws_manager.unsubscribe(
                ex_name,
                mapped_sym,
            )

        return

    if (
        new_state == "TRIGGERED"
        and current_state == "TRIGGERED"
    ):
        record_final_production_decision(
            "STALE_TRIGGER_SUPPRESSED",
            "candidate was already persisted as TRIGGERED",
        )

        _store_live_metrics(
            symbol,
            metrics,
        )

        validator.ws_manager.unsubscribe(
            ex_name,
            mapped_sym,
        )

        return

    if new_state == "TRIGGERED":
        (
            is_vetoed,
            advisory,
        ) = await ai_veto.evaluate_symbol(
            symbol,
            metrics.get(
                "orderbook",
                {},
            ),
            metrics.get(
                "ticker",
                {},
            ),
        )

        metrics[
            "ai_advisory"
        ] = advisory

        if is_vetoed:
            state_persisted = db.update_candidate_state(
                symbol,
                "WATCH",
            )

            record_final_production_decision(
                "AI_VETOED",
                "AI advisory vetoed the validated trigger candidate",
                state_persisted=bool(state_persisted),
            )

            validator.ws_manager.unsubscribe(
                ex_name,
                mapped_sym,
            )

            _store_live_metrics(
                symbol,
                metrics,
            )

            return

        try:
            metrics[
                "applied_leverage"
            ] = get_leverage(
                symbol
            )

        except Exception as exc:
            record_final_production_decision(
                "LEVERAGE_REJECTED",
                "leverage calculation failed",
                error_type=type(exc).__name__,
            )

            logger.warning(
                "Leverage calculation failed "
                "for %s: %s",
                symbol,
                exc,
            )
            return

        execution_suitability = (
            execution_suitability_enricher
            .for_symbol(symbol)
        )
        quote_volume = data.get(
            "quote_volume"
        )
        volume_gate_passed = (
            execution_decision_logger
            .volume_gate_passes(
                quote_volume
            )
        )
        proxy_execution_disagreement = (
            execution_decision_logger
            .comparison_kind(
                volume_gate_passed,
                str(
                    execution_suitability.get(
                        "status"
                    )
                    or "UNKNOWN"
                ),
            )
        )

        signal_id = signal_ledger.persist_trigger(
            symbol,
            current_state,
            score=score,
            trigger_metrics=metrics,
            execution_suitability=(
                execution_suitability
            ),
            quote_volume=quote_volume,
            volume_gate_passed=volume_gate_passed,
            proxy_execution_disagreement=(
                proxy_execution_disagreement
            ),
        )

        if signal_id is None:
            record_final_production_decision(
                "PERSISTENCE_REJECTED",
                "signal persistence rejected or failed",
            )

            logger.error(
                "Signal persistence rejected or failed for %s; "
                "stale Telegram alert suppressed",
                symbol,
            )
            return

        experimental_profile = not _signal_alert_allowed(metrics)

        record_final_production_decision(
            "TRIGGERED",
            (
                "experimental trigger persisted to the immutable signal ledger"
                if experimental_profile
                else "validated trigger persisted to the immutable signal ledger"
            ),
            signal_id=int(signal_id),
        )

        logger.warning(
            "🔥 [%s] TRIGGERED - Score: %s/100 "
            "(signal_id=%s)",
            symbol,
            score,
            signal_id,
        )

        if _signal_alert_allowed(metrics):
            await notifier.send_signal_alert(
                symbol,
                {
                    "score": score,
                    "metrics": metrics,
                },
            )
        else:
            logger.warning(
                "Experimental signal %s persisted without Telegram delivery",
                signal_id,
            )

        validator.ws_manager.unsubscribe(
            ex_name,
            mapped_sym,
        )

        _store_live_metrics(
            symbol,
            metrics,
        )

        return


async def hunter_loop(
    interval_seconds: int = 60,
):
    global _hunter_running
    global _hunter_last_completed_at
    global _hunter_last_progress_at

    _hunter_running = True

    await asyncio.sleep(
        5
    )

    logger.info(
        "🛡️ [SYSTEM] Engine Online: "
        "State Machine running."
    )

    while _hunter_running:
        try:
            _hunter_last_progress_at = (
                time.time()
            )

            await (
                scanner
                .refresh_live_references()
            )

            candidates = (
                db.get_all_active_candidates()
            )

            if candidates:
                semaphore = (
                    asyncio.Semaphore(
                        6
                    )
                )
                evaluations_since_flush = 0

                async def evaluate_bounded(
                    symbol,
                    data,
                ):
                    global _hunter_last_progress_at
                    nonlocal evaluations_since_flush

                    async with semaphore:
                        try:
                            if _hunter_running:
                                await evaluate_candidate(
                                    symbol,
                                    data,
                                )
                        finally:
                            _hunter_last_progress_at = (
                                time.time()
                            )
                            evaluations_since_flush += 1

                            if evaluations_since_flush >= 30:
                                evaluations_since_flush = 0
                                await asyncio.to_thread(
                                    execution_decision_logger
                                    .flush_evaluations
                                )

                results = await asyncio.gather(
                    *(
                        evaluate_bounded(
                            symbol,
                            data,
                        )
                        for symbol, data
                        in candidates.items()
                    ),
                    return_exceptions=True,
                )

                for result in results:
                    if isinstance(
                        result,
                        Exception,
                    ):
                        logger.warning(
                            "Candidate evaluation failed: %s",
                            result,
                        )

                    _hunter_last_progress_at = (
                        time.time()
                    )

            await asyncio.to_thread(
                execution_decision_logger
                .flush_evaluations
            )

            await asyncio.to_thread(
                execution_decision_logger
                .record_universe_snapshot
            )

            validator.ws_manager.prune_stale_cache()

            _hunter_last_completed_at = (
                time.time()
            )

            await asyncio.sleep(
                interval_seconds
            )

        except asyncio.CancelledError:
            break

        except Exception as exc:
            logger.error(
                "⚠️ Hunter Loop Error: %s",
                exc,
            )

            await asyncio.sleep(
                15
            )


async def live_reference_loop(
    interval_seconds: int = 30,
):
    while True:
        try:
            await (
                scanner
                .refresh_live_references()
            )

        except asyncio.CancelledError:
            break

        except Exception as exc:
            logger.warning(
                "Live reference refresh failed: %s",
                exc,
            )

        await asyncio.sleep(
            interval_seconds
        )


@app.on_event(
    "startup"
)
async def startup_event():
    global _lbank_execution_shadow_worker
    global _signal_settlement_worker

    if settings.live_trading_enabled:
        raise RuntimeError(
            "LIVE_TRADING_ENABLED must remain "
            "false for WaterfallHunter"
        )

    _start_background_task(
        scanner.start_background_scanner(
            21600
        )
    )

    _start_background_task(
        live_reference_loop()
    )

    _start_background_task(
        hunter_loop(
            interval_seconds=60
        )
    )

    _start_background_task(
        feature_replay_worker.run_forever(
            interval_seconds=60.0,
        )
    )
    logger.info(
        "Observational feature-equivalent replay enabled "
        "(batch=3 interval=60s)"
    )

    _start_background_task(
        sse_broadcaster()
    )

    _start_background_task(
        notifier.start_interactive_bot()
    )

    _lbank_execution_shadow_worker = (
        _build_lbank_execution_shadow_worker()
    )

    if (
        _lbank_execution_shadow_worker
        is not None
    ):
        logger.info(
            "LBank execution shadow enabled: "
            "batch=%s interval=%ss",
            (
                _lbank_execution_shadow_worker
                .batch_size
            ),
            settings.lbank_execution_shadow_interval_seconds,
        )

        _start_background_task(
            _lbank_execution_shadow_worker.run_forever(
                interval_seconds=(
                    settings
                    .lbank_execution_shadow_interval_seconds
                ),
            )
        )

    else:
        logger.info(
            "LBank execution shadow disabled."
        )

    _signal_settlement_worker = (
        _build_signal_settlement_worker()
    )
    _start_background_task(
        _signal_settlement_worker
        .run_forever(
            interval_seconds=900.0,
        )
    )
    logger.info(
        "Observational 24h signal settlement enabled "
        "(batch=3 interval=900s)"
    )


@app.on_event(
    "shutdown"
)
async def shutdown_event():
    global _hunter_running
    global _lbank_execution_shadow_worker
    global _signal_settlement_worker

    _hunter_running = False

    feature_replay_worker.stop()

    scanner.stop()

    if (
        _lbank_execution_shadow_worker
        is not None
    ):
        _lbank_execution_shadow_worker.stop()

    if _signal_settlement_worker is not None:
        _signal_settlement_worker.stop()

    tasks = list(
        _background_tasks
    )

    for task in tasks:
        task.cancel()

    if tasks:
        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

    if (
        _lbank_execution_shadow_worker
        is not None
    ):
        await (
            _lbank_execution_shadow_worker
            .close()
        )

        _lbank_execution_shadow_worker = None

    _signal_settlement_worker = None

    await scanner.close()
    await validator.close_all()


def _readiness_snapshot() -> tuple[
    bool,
    dict,
]:
    """
    Build the operational readiness packet.

    Shadow execution observation is intentionally informational only and does
    not gate readiness. Catalogue freshness and hunter progress remain the
    authoritative readiness requirements used by the existing /api/health
    contract.
    """

    now = time.time()

    catalog_age = (
        None
        if scanner.last_successful_refresh_at
        is None
        else (
            now
            - scanner.last_successful_refresh_at
        )
    )

    hunter_age = (
        None
        if _hunter_last_progress_at
        is None
        else (
            now
            - _hunter_last_progress_at
        )
    )

    catalog_fresh = (
        catalog_age is not None
        and catalog_age <= 25_200
    )

    hunter_fresh = (
        hunter_age is not None
        and hunter_age <= 180
    )

    ready = (
        catalog_fresh
        and hunter_fresh
    )

    if not ready:
        return (
            False,
            {
                "status": "degraded",
                "catalog_age_seconds": (
                    catalog_age
                ),
                "hunter_progress_age_seconds": (
                    hunter_age
                ),
            },
        )

    return (
        True,
        {
            "status": "healthy",
            "tracked": len(
                scanner.active_candidates
            ),
            "catalog_age_seconds": round(
                catalog_age,
                1,
            ),
            "hunter_progress_age_seconds": round(
                hunter_age,
                1,
            ),
            "lbank_execution_shadow": (
                _lbank_shadow_health_snapshot()
            ),
        },
    )


@app.get(
    "/api/health"
)
async def health_check():
    ready, payload = (
        _readiness_snapshot()
    )

    if not ready:
        raise HTTPException(
            status_code=503,
            detail=payload,
        )

    return payload


@app.get(
    "/livez"
)
async def liveness_check():
    return {
        "status": "alive",
    }


@app.get(
    "/readyz"
)
async def readiness_check():
    return await health_check()


@app.get(
    "/healthz"
)
async def healthz_check():
    return await health_check()


@app.get(
    "/metrics"
)
async def metrics():
    active_candidates = db.get_all_active_candidates()
    tracked_candidates.set(
        len(active_candidates)
    )
    _update_candidate_state_metrics(
        active_candidates
    )

    if (
        scanner.last_successful_refresh_at
        is not None
    ):
        catalog_last_refresh.set(
            scanner.last_successful_refresh_at
        )

    if (
        _hunter_last_completed_at
        is not None
    ):
        hunter_last_cycle.set(
            _hunter_last_completed_at
        )

    if (
        _hunter_last_progress_at
        is not None
    ):
        hunter_last_progress.set(
            _hunter_last_progress_at
        )

    _update_lbank_shadow_metrics()
    _update_signal_settlement_worker_metrics()
    await _update_signal_evidence_metrics()

    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get(
    "/api/stream"
)
async def stream_candidates():
    q = asyncio.Queue(
        maxsize=100
    )

    _sse_clients.add(
        q
    )

    async def event_generator():
        try:
            yield (
                f"data: "
                f"{json.dumps(get_formatted_candidates())}"
                f"\n\n"
            )

            while True:
                yield await q.get()

        finally:
            _sse_clients.discard(
                q
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


@app.get(
    "/api/candidates"
)
async def get_candidates():
    return get_formatted_candidates()
