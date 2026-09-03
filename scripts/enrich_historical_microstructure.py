#!/usr/bin/env python3
"""Research-only point-in-time microstructure enrichment from Binance archives."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from io import BytesIO, TextIOWrapper
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from zipfile import ZipFile

from waterfallhunter.core.entry_decision import (
    _derivative_points,
    _order_flow_points,
    _price_location_points,
    _structure_points,
    _timing_points,
)
from waterfallhunter.core.microstructure import MicrostructureAnalyzer

ARCHIVE_ROOT = "https://data.binance.vision/data/futures/um/daily"
TRADE_TTL_MS = 60_000
DEPTH_TTL_MS = 5_000
MAX_TRADES = 100


def _archive_url(kind: str, symbol: str, day: str) -> str:
    return f"{ARCHIVE_ROOT}/{kind}/{symbol}/{symbol}-{kind}-{day}.zip"


def _download(url: str, cache_path: Path) -> bytes | None:
    if cache_path.exists():
        return cache_path.read_bytes()
    try:
        with urlopen(url, timeout=60) as response:
            payload = response.read()
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    except (OSError, URLError):
        return None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp.write_bytes(payload)
    tmp.replace(cache_path)
    return payload


def _parse_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def _trade_rows_for_events(payload: bytes, event_times: list[int]) -> dict[int, list[dict]]:
    selected: dict[int, list[dict]] = {timestamp: [] for timestamp in event_times}
    if not payload:
        return selected
    with ZipFile(BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            return selected
        with archive.open(names[0]) as raw:
            for row in csv.DictReader(TextIOWrapper(raw, encoding="utf-8")):
                try:
                    timestamp = int(row["transact_time"])
                    price = float(row["price"])
                    amount = float(row["quantity"])
                    is_buyer_maker = _parse_bool(row["is_buyer_maker"])
                except (KeyError, TypeError, ValueError):
                    continue
                if timestamp <= 0 or price <= 0 or amount <= 0:
                    continue
                for event_time in event_times:
                    if event_time - TRADE_TTL_MS <= timestamp <= event_time:
                        selected[event_time].append({
                            "timestamp": timestamp,
                            "price": price,
                            "amount": amount,
                            "side": "sell" if is_buyer_maker else "buy",
                        })
    for event_time in selected:
        selected[event_time] = sorted(selected[event_time], key=lambda item: item["timestamp"])[-MAX_TRADES:]
    return selected


def _depth_rows_for_events(payload: bytes, event_times: list[int]) -> dict[int, dict | None]:
    snapshots: dict[int, dict[int, dict[float, float]]] = {timestamp: {} for timestamp in event_times}
    if not payload:
        return {timestamp: None for timestamp in event_times}
    with ZipFile(BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            return {timestamp: None for timestamp in event_times}
        with archive.open(names[0]) as raw:
            for row in csv.DictReader(TextIOWrapper(raw, encoding="utf-8")):
                try:
                    observed = int(datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).timestamp() * 1000)
                    percentage = float(row["percentage"])
                    notional = float(row["notional"])
                except (KeyError, TypeError, ValueError):
                    continue
                for event_time in event_times:
                    if event_time - DEPTH_TTL_MS <= observed <= event_time:
                        snapshots[event_time].setdefault(observed, {})[percentage] = notional
    result = {}
    for event_time, groups in snapshots.items():
        if not groups:
            result[event_time] = None
            continue
        observed = max(groups)
        levels = groups[observed]
        result[event_time] = {
            "observed_at_ms": observed,
            "age_ms": event_time - observed,
            "levels": {str(key): value for key, value in sorted(levels.items())},
            "bid_depth_1pct_usdt": levels.get(-1.0),
            "ask_depth_1pct_usdt": levels.get(1.0),
        }
    return result


def _observable_entry_readiness(trade: dict, flow: dict | None) -> dict:
    evidence = trade.get("evidence") if isinstance(trade.get("evidence"), dict) else {}
    stages = trade.get("stages") if isinstance(trade.get("stages"), dict) else {}
    candles = {}
    h4 = evidence.get("4h") if isinstance(evidence.get("4h"), dict) else {}
    candles["4h"] = {
        "valid": True,
        "hype_context": stages.get("hype") is True,
        "lower_high": h4.get("lower_high") is True,
        "setup": trade.get("setup_type"),
        "bearish_close": h4.get("bearish_close") is True,
        "volume_acceleration": h4.get("volume_acceleration") is True,
    }
    for timeframe in ("1h", "15m", "5m"):
        flags = evidence.get(timeframe) if isinstance(evidence.get(timeframe), dict) else {}
        candles[timeframe] = {
            "valid": True,
            "lower_high": flags.get("lower_high") is True,
            "reclaim": flags.get("reclaim_or_repump") is True,
            "repump": False,
            "rsi_rollover": flags.get("rsi_rollover") is True,
            "bearish_close": flags.get("bearish_close") is True,
        }
    derivatives = dict(trade.get("derivatives") or {})
    derivatives["available"] = bool(trade.get("derivatives"))
    micro = {}
    if flow is not None:
        micro = {
            "sell_flow_usdt": flow["sell_flow"],
            "buy_flow_usdt": flow["buy_flow"],
            "footprint": {
                "available": flow["footprint_available"],
                "aggressive_selling": bool(
                    flow["footprint_available"]
                    and flow["sell_flow"] > flow["buy_flow"]
                    and flow["sell_imbalances"] > 0
                ),
            },
        }
    price_component = ((trade.get("historical_score_v2") or {}).get("components") or {}).get("same_contract_price_location") or {}
    below_vwap = None
    if price_component.get("available") is True:
        below_vwap = float(price_component.get("points") or 0.0) > 0.0
    metrics = {
        "candle_features": candles,
        "derivatives": derivatives,
        "microstructure": micro,
        "price_location": {"below_vwap": below_vwap},
    }
    structure = _structure_points(metrics)
    timing = _timing_points(metrics)
    order_flow = _order_flow_points(metrics)
    deriv = _derivative_points(metrics)
    price = _price_location_points(metrics)
    components = {
        "structure": {"points": structure[0], "available_maximum": structure[1]},
        "timing": {"points": timing[0], "available_maximum": timing[1]},
        "order_flow": {"points": order_flow[0], "available_maximum": order_flow[1], "direction_ok": order_flow[3]},
        "derivatives": {"points": deriv[0], "available_maximum": deriv[1]},
        "price_location": {"points": price[0], "available_maximum": price[1]},
        "execution": {"points": None, "available_maximum": 0.0, "reason": "2026 exact spread/slippage/approval unavailable"},
        "cross_exchange": {"points": None, "available_maximum": 0.0, "reason": "single-venue archive"},
        "cascade": {"points": None, "available_maximum": 0.0, "reason": "historical cascade evidence unavailable"},
    }
    observed_score = sum(float(item["points"] or 0.0) for item in components.values() if item["points"] is not None)
    observed_maximum = sum(float(item["available_maximum"] or 0.0) for item in components.values())
    return {
        "schema_version": "entry_readiness_historical_observable_v1",
        "observed_score": round(observed_score, 6),
        "observed_maximum": round(observed_maximum, 6),
        "coverage_pct_of_production_100": round(observed_maximum, 6),
        "components": components,
        "direction_ok": order_flow[3],
        "strategy_equivalent": False,
        "production_threshold_directly_applicable": False,
    }


def enrich(report: dict, cache_dir: Path) -> dict:
    trades = report.get("trades") if isinstance(report.get("trades"), list) else []
    grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
    for trade in trades:
        timestamp = int(trade["timestamp"])
        day = datetime.fromtimestamp(timestamp / 1000, UTC).date().isoformat()
        grouped[(str(trade["symbol"]), day)].append(timestamp)
    packets = {}
    for index, ((symbol, day), event_times) in enumerate(sorted(grouped.items()), start=1):
        trade_url = _archive_url("aggTrades", symbol, day)
        depth_url = _archive_url("bookDepth", symbol, day)
        trade_payload = _download(trade_url, cache_dir / "aggTrades" / f"{symbol}-{day}.zip")
        depth_payload = _download(depth_url, cache_dir / "bookDepth" / f"{symbol}-{day}.zip")
        trade_rows = _trade_rows_for_events(trade_payload or b"", event_times)
        depth_rows = _depth_rows_for_events(depth_payload or b"", event_times)
        for event_time in event_times:
            selected = trade_rows[event_time]
            flow = MicrostructureAnalyzer._trade_flow_metrics(selected, contract_size=1.0) if len(selected) >= 20 else None
            packets[(symbol, event_time)] = {
                "schema_version": "historical_microstructure_enrichment_v1",
                "causal": True,
                "trade_source_url": trade_url,
                "depth_source_url": depth_url,
                "trade_flow": ({
                    "available": True,
                    "trade_count": len(selected),
                    "window_start_ms": event_time - TRADE_TTL_MS,
                    "window_end_ms": event_time,
                    **flow,
                } if flow is not None else {
                    "available": False,
                    "trade_count": len(selected),
                    "reason": "fewer than 20 causal trades in production-equivalent 60s window",
                }),
                "depth_proxy": ({
                    "available": True,
                    "semantic_equivalence": False,
                    "reason": "archive provides cumulative percentage depth, not production top-20 L2 ladder",
                    **depth_rows[event_time],
                } if depth_rows[event_time] is not None else {
                    "available": False,
                    "semantic_equivalence": False,
                    "reason": "no causal bookDepth snapshot within 5 seconds",
                }),
                "spread_pct": None,
                "slippage_pct": None,
                "spoofing_detected": None,
                "approved": None,
            }
        print(f"[{index}/{len(grouped)}] {symbol} {day}", flush=True)
    enriched = json.loads(json.dumps(report))
    available_flow = 0
    available_depth = 0
    maxima = []
    for trade in enriched["trades"]:
        packet = packets[(trade["symbol"], int(trade["timestamp"]))]
        trade["historical_microstructure"] = packet
        flow = packet["trade_flow"] if packet["trade_flow"].get("available") is True else None
        if flow is not None:
            available_flow += 1
        if packet["depth_proxy"].get("available") is True:
            available_depth += 1
        readiness = _observable_entry_readiness(trade, flow)
        trade["historical_entry_readiness_observable"] = readiness
        maxima.append(readiness["observed_maximum"])
    enriched["historical_microstructure_contract"] = {
        "schema_version": "historical_microstructure_enrichment_v1",
        "archive_root": ARCHIVE_ROOT,
        "trade_flow_semantics": "canonical MicrostructureAnalyzer._trade_flow_metrics over last <=100 aggTrades in causal 60s window",
        "depth_semantics": "proxy only; cumulative +/- percentage depth; excluded from canonical execution scoring",
        "spread_slippage_approval": "UNAVAILABLE",
        "strategy_equivalent": False,
        "events": len(enriched["trades"]),
        "trade_flow_available": available_flow,
        "depth_proxy_available": available_depth,
        "entry_readiness_observed_maximum_values": sorted(set(maxima)),
    }
    return enriched


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-pool", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = Path(args.candidate_pool)
    report = json.loads(source.read_text())
    enriched = enrich(report, Path(args.cache_dir))
    enriched["historical_microstructure_contract"]["source_candidate_pool_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(enriched, ensure_ascii=False, indent=2))
    print(destination)
    print(hashlib.sha256(destination.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
