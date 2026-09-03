#!/usr/bin/env python3
"""Development-only calibration of the causally observable Entry Readiness subset."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from scripts.backtest_metrics import expanding_walk_forward_windows, performance_metrics, selection_key

THRESHOLDS = (40.0, 45.0, 50.0, 55.0, 60.0, 65.0)
REQUIRED_OBSERVED_MAXIMUM = 73.0
REQUIRED_TIMING_POINTS = 10.0


def _packet(trade: dict) -> dict:
    value = trade.get("historical_entry_readiness_observable")
    return value if isinstance(value, dict) else {}


def _eligible(trade: dict, threshold: float) -> bool:
    packet = _packet(trade)
    if packet.get("schema_version") != "entry_readiness_historical_observable_v1":
        return False
    score = packet.get("observed_score")
    maximum = packet.get("observed_maximum")
    components = packet.get("components") if isinstance(packet.get("components"), dict) else {}
    timing = components.get("timing") if isinstance(components.get("timing"), dict) else {}
    timing_points = timing.get("points")
    return bool(
        isinstance(score, (int, float)) and not isinstance(score, bool)
        and isinstance(maximum, (int, float)) and not isinstance(maximum, bool)
        and math.isclose(float(maximum), REQUIRED_OBSERVED_MAXIMUM, rel_tol=0.0, abs_tol=1e-9)
        and packet.get("direction_ok") is True
        and isinstance(timing_points, (int, float)) and not isinstance(timing_points, bool)
        and float(timing_points) >= REQUIRED_TIMING_POINTS
        and float(score) >= threshold
    )


def _apply_cooldown(trades: list[dict], threshold: float, cooldown_hours: float) -> list[dict]:
    cooldown_ms = int(max(float(cooldown_hours), 0.0) * 3_600_000)
    selected = [trade for trade in trades if _eligible(trade, threshold)]
    result: list[dict] = []
    cooldown_until: dict[str, int] = {}
    for trade in sorted(selected, key=lambda item: (item["timestamp"], str(item.get("symbol", "")))):
        symbol = str(trade.get("symbol", ""))
        if trade["timestamp"] < cooldown_until.get(symbol, 0):
            continue
        result.append(trade)
        cooldown_until[symbol] = int(trade["timestamp"]) + cooldown_ms
    return result


def _walk_forward(trades: list[dict], *, threshold: float, start_ms: int, end_ms: int,
                  horizon_ms: int, folds: int = 3, minimum_fold_trades: int = 8) -> dict:
    windows = expanding_walk_forward_windows(
        start_ms=start_ms, end_ms=end_ms, outcome_horizon_ms=horizon_ms, folds=folds,
    )
    fold_packets = []
    oos: list[dict] = []
    for window in windows:
        selected = [
            trade for trade in trades
            if window["test_start_ms"] <= trade["timestamp"] < window["test_signal_end_ms"]
        ]
        metrics = performance_metrics(selected, return_field="net_realized_r")
        sufficient = metrics.get("available") is True and metrics.get("sample_size", 0) >= minimum_fold_trades
        fold_packets.append({**window, "sufficient": sufficient, "performance": metrics})
        if sufficient:
            oos.extend(selected)
    aggregate = performance_metrics(oos, return_field="net_realized_r")
    sufficient_folds = sum(item["sufficient"] for item in fold_packets)
    positive_folds = sum(
        item["sufficient"] and item["performance"].get("expectancy_r", 0.0) > 0
        for item in fold_packets
    )
    required_positive = math.ceil(folds * 2 / 3)
    valid = bool(
        sufficient_folds == folds
        and positive_folds >= required_positive
        and aggregate.get("available") is True
        and aggregate.get("expectancy_r", 0.0) > 0
        and aggregate.get("profit_factor") is not None
        and aggregate.get("max_drawdown_pct", float("inf")) <= 20.0
    )
    return {
        "threshold": threshold,
        "oos_folds": folds,
        "sufficient_oos_folds": sufficient_folds,
        "positive_oos_folds": positive_folds,
        "minimum_positive_oos_folds": required_positive,
        "performance": aggregate,
        "folds": fold_packets,
        "valid": valid,
        "complexity": 0,
    }


def calibrate(report: dict, *, thresholds=THRESHOLDS, minimum_fold_trades: int = 8) -> dict:
    window = report.get("window") if isinstance(report.get("window"), dict) else {}
    start_ms, end_ms = window.get("start_ms"), window.get("end_ms")
    if not isinstance(start_ms, int) or not isinstance(end_ms, int) or start_ms >= end_ms:
        raise ValueError("invalid immutable source window")
    trades = report.get("trades") if isinstance(report.get("trades"), list) else None
    if trades is None or report.get("historical_microstructure_contract", {}).get("strategy_equivalent") is not False:
        raise ValueError("enriched research-only candidate pool required")
    hold_hours = report.get("max_hold_hours")
    if not isinstance(hold_hours, int) or hold_hours < 1:
        raise ValueError("invalid outcome horizon")
    horizon_ms = hold_hours * 3_600_000
    development_end = start_ms + (end_ms - start_ms) * 5 // 6
    cooldown_hours = float(report.get("cooldown_hours") or 0.0)
    by_threshold = {float(t): _apply_cooldown(trades, float(t), cooldown_hours) for t in thresholds}
    assessments = {
        threshold: _walk_forward(
            selected,
            threshold=threshold,
            start_ms=start_ms,
            end_ms=development_end,
            horizon_ms=horizon_ms,
            minimum_fold_trades=minimum_fold_trades,
        )
        for threshold, selected in by_threshold.items()
    }
    ranked = [(selection_key(packet), threshold) for threshold, packet in assessments.items() if packet["valid"]]
    selected_threshold = sorted(ranked)[0][1] if ranked else None
    plateau_neighbors: list[float] = []
    if selected_threshold is not None:
        ordered = sorted(float(value) for value in thresholds)
        index = ordered.index(selected_threshold)
        neighbors = [value for value in ordered[max(0, index - 1):index + 2] if value != selected_threshold]
        plateau_neighbors = [value for value in neighbors if assessments[value]["valid"]]
        if not plateau_neighbors:
            selected_threshold = None
    holdout = {}
    selected_count = 0
    if selected_threshold is not None:
        selected_trades = by_threshold[selected_threshold]
        holdout_trades = [trade for trade in selected_trades if trade["timestamp"] >= development_end]
        holdout = performance_metrics(holdout_trades, return_field="net_realized_r")
        selected_count = len(selected_trades)
    return {
        "schema_version": "entry_readiness_historical_observable_calibration_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_window": dict(window),
        "development_end_ms": development_end,
        "selection_contract": {
            "configuration_space_frozen_before_enriched_results": True,
            "thresholds": [float(value) for value in thresholds],
            "required_observed_maximum": REQUIRED_OBSERVED_MAXIMUM,
            "required_timing_points": REQUIRED_TIMING_POINTS,
            "direction_ok_required": True,
            "anchored_walk_forward_folds": 3,
            "minimum_fold_trades": minimum_fold_trades,
            "outcome_horizon_purge_ms": horizon_ms,
            "holdout_used_for_selection": False,
            "plateau_neighbor_required": True,
        },
        "all_development_assessments": {str(key): value for key, value in assessments.items()},
        "selected": {
            "threshold": selected_threshold,
            "plateau_neighbors": plateau_neighbors,
            "selection_source": "development_anchored_walk_forward_only",
            "holdout_used_for_selection": False,
            "research_only": True,
            "production_applied": False,
            "selected_full_sample_count": selected_count,
        },
        "holdout": holdout,
        "promotion_eligibility": {
            "eligible": False,
            "reasons": [
                "only 73/100 Entry Readiness points are causally observable in this archive study",
                "execution, cross-exchange and cascade evidence remain unavailable",
                "fee/slippage cost basis is modeled/empirical research evidence rather than realized account execution",
                "historical observable threshold is not the production 78 threshold and cannot be substituted for it",
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enriched-report", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = Path(args.enriched_report)
    report = json.loads(source.read_text())
    result = calibrate(report)
    result["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(destination)
    print(json.dumps({"selected": result["selected"], "holdout": result["holdout"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
