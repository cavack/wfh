#!/usr/bin/env python3
"""Compile immutable runtime evidence into a deterministic research JSONL export."""
from __future__ import annotations
import argparse, bisect, collections, hashlib, json, math, sqlite3
from pathlib import Path
from typing import Any

STATUS = ("PENDING", "COMPLETE", "INSUFFICIENT_WINDOW", "MISSING_MARKET_DATA", "INVALID_LEVELS", "DUPLICATE_LINK", "PROVENANCE_MISMATCH")

def _json(value: Any) -> Any:
    if value is None: return None
    if isinstance(value, (str, int, bool)): return value
    if isinstance(value, float): return value if math.isfinite(value) else None
    if isinstance(value, bytes): return value.hex()
    if isinstance(value, dict): return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_json(v) for v in value]
    return str(value)

def _loads(value: Any) -> dict[str, Any]:
    if not value: return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except (TypeError, ValueError): return {"_invalid_json": True}

def _field(value: Any, reason: str | None = None) -> dict[str, Any]:
    return {"value": _json(value), "reason": reason} if value is None or reason else {"value": _json(value), "reason": None}

def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

def _rows(conn: sqlite3.Connection, table: str, where: str = "", args: tuple = ()) -> list[dict[str, Any]]:
    if table not in _tables(conn): return []
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table} {where}", args)]

def _evidence_payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        import zlib
        raw = zlib.decompress(row["evidence_zlib"])
        return json.loads(raw)
    except (KeyError, TypeError, ValueError, zlib.error): return {}

def compile_dataset(db_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path)); conn.row_factory = sqlite3.Row
    tables = _tables(conn)
    signals = _rows(conn, "lbank_signal_ledger", "ORDER BY id")
    outcomes = _rows(conn, "lbank_signal_outcomes", "ORDER BY id")
    decisions = _rows(conn, "entry_decision_events", "ORDER BY id")
    # Decision-event exports already contain their immutable packet.  Avoid
    # loading the multi-gigabyte snapshot blob column (and avoid a non-causal
    # cross-row join) when those primary rows are present.
    evidence = [] if decisions else _rows(conn, "production_evidence_snapshots", "ORDER BY id")
    replay = _rows(conn, "production_feature_replay_results_v2", "ORDER BY id")
    out_by_signal: dict[Any, list[dict[str, Any]]] = collections.defaultdict(list)
    for r in outcomes: out_by_signal[r.get("signal_id")].append(r)
    # Decision events are the primary candidate-evaluation rows.  The ledger is
    # retained as a compatibility fallback for old databases without events.
    primary_decisions = decisions if decisions else []
    records = []
    primary_rows = primary_decisions or [{"_ledger": s} for s in signals]
    signal_index = collections.defaultdict(list)
    for candidate in signals:
        signal_index[candidate.get("symbol")].append((candidate.get("triggered_at"), candidate))
    for values in signal_index.values():
        values.sort(key=lambda item: (item[0] if isinstance(item[0], (int, float)) else -1))
    for primary in primary_rows:
        s = primary.get("_ledger", primary)
        packet = _loads(primary.get("packet_json")) if primary.get("packet_json") else {}
        sid, symbol = s.get("id"), s.get("symbol")
        if primary_decisions:
            symbol = primary.get("symbol")
            triggered = primary.get("event_at")
            indexed = signal_index.get(symbol, [])
            if indexed and isinstance(triggered, (int, float)):
                pos = bisect.bisect_left([item[0] for item in indexed], triggered)
                nearby = indexed[max(0, pos - 1):pos + 1]
                if nearby:
                    s = min(nearby, key=lambda item: (abs(item[0] - triggered), item[0]))[1]
                    sid = s.get("id")
            # Only use an evidence snapshot causally available to this event.
            candidates = [e for e in evidence if e.get("symbol") == symbol and isinstance(e.get("observed_at"), (int,float)) and isinstance(triggered, (int,float)) and e["observed_at"] <= triggered]
            ev = max(candidates, key=lambda e: (e["observed_at"], e["id"])) if candidates else None
        else:
            triggered = s.get("triggered_at")
            candidates = [e for e in evidence if e.get("symbol") == symbol and isinstance(e.get("observed_at"), (int,float)) and isinstance(triggered, (int,float)) and e["observed_at"] >= triggered]
            ev = min(candidates, key=lambda e: (e["observed_at"], e["id"])) if candidates else None
        linked = out_by_signal.get(sid, [])
        o = linked[0] if len(linked) == 1 else None
        reasons: list[str] = []
        status = "PENDING"
        if not isinstance(triggered, (int, float)) or not math.isfinite(float(triggered)):
            status, reasons = "INVALID_LEVELS", ["nonfinite_or_invalid_signal_timestamp"]
        elif len(linked) > 1: status, reasons = "DUPLICATE_LINK", ["multiple_outcomes_for_signal_id"]
        elif not o: status, reasons = "MISSING_MARKET_DATA", ["outcome_row_unavailable"]
        elif o.get("outcome_status") == "PENDING": status, reasons = "PENDING", ["outcome_pending"]
        elif any(not isinstance(o.get(k), (int,float)) or not math.isfinite(float(o[k])) for k in ("min_price", "max_price") if o.get(k) is not None): status, reasons = "INVALID_LEVELS", ["nonfinite_outcome_level"]
        elif (isinstance(o.get("observation_started_at"), (int,float)) and o.get("observation_started_at") < triggered) or (isinstance(o.get("observation_ended_at"), (int,float)) and o.get("observation_ended_at") < triggered): status, reasons = "INVALID_LEVELS", ["observation_before_signal"]
        elif o.get("observed_candles") != o.get("expected_candles") or (o.get("outcome_status") not in ("COMPLETE", "SCIENTIFICALLY_EVALUABLE")): status, reasons = "INSUFFICIENT_WINDOW", ["incomplete_horizon_or_outcome_status"]
        else: status = "COMPLETE"
        payload = packet if primary_decisions else (_evidence_payload(ev) if ev else {})
        metrics = payload.get("metrics", {}) if isinstance(payload, dict) else {}
        provenance = payload.get("decision_provenance", {}) if isinstance(payload, dict) else {}
        evidence_code = ev.get("code_sha256_v5") if ev else None
        packet_code = provenance.get("source_tree_sha256") or payload.get("source_tree_sha256")
        if evidence_code and packet_code and evidence_code != packet_code:
            status, reasons = "PROVENANCE_MISMATCH", ["evidence_and_packet_code_sha_mismatch"]
        costs = _loads(o.get("details_json")) if o else {}
        cost_values = {
            "fees": costs.get("fees", costs.get("fee")),
            "slippage": costs.get("slippage"),
            "funding": costs.get("funding"),
            "net_r": costs.get("net_r", costs.get("net_realized_r")),
        }
        canonical_decision = packet.get("decision") if primary_decisions else None
        canonical_readiness = packet.get("entry_readiness") if primary_decisions else (ev or {}).get("suggested_status")
        record = {"record_version":"normalized_research_v1", "signal_id":sid, "candidate_evaluation_id": primary.get("id") if primary_decisions else None,
          "packet_id": primary.get("id") if primary_decisions else (ev.get("id") if ev else None), "symbol":symbol, "strategy_profile":(packet.get("lifecycle_state") if primary_decisions else s.get("state_before")),
          "decision":_field(canonical_decision, "decision_packet_unavailable" if not primary_decisions else ("decision_missing_in_packet" if canonical_decision is None else None)),
          "observed_at":_field(triggered, "missing_signal_timestamp" if triggered is None else None), "decision_at":_field((ev or {}).get("observed_at"), "evidence_packet_unavailable" if not ev else None),
          "evidence_as_of":_field((ev or {}).get("observed_at"), "evidence_packet_unavailable" if not ev else None),
          "code_sha":_field(evidence_code, "provenance_unavailable" if not evidence_code else None), "decision_contract_sha":_field(provenance.get("decision_contract_sha256"), "provenance_unavailable"),
          "lifecycle_v1":_field(s.get("state_before"), "lifecycle_unavailable" if not s.get("state_before") else None), "lifecycle_v2_shadow":_field(None, "no_linked_shadow_event"),
          "score_v2_strict":_field(s.get("score"), "score_unavailable" if s.get("score") is None else None), "score_v2_watch":_field(metrics.get("score"), "score_unavailable" if metrics.get("score") is None else None),
          "readiness":_field(canonical_readiness, "evidence_packet_unavailable" if not ev and not primary_decisions else ("readiness_missing_in_packet" if canonical_readiness is None else None)), "coverage":_field(packet.get("evidence_coverage_pct") if primary_decisions else (ev or {}).get("valid_candle_timeframes"), "evidence_packet_unavailable" if not ev and not primary_decisions else None),
          "components":_field(metrics.get("score_components"), "components_unavailable"), "gates":_field(metrics.get("quality_gates"), "gates_unavailable"), "trade_plan":_field(_loads(s.get("position_setup_json")), "trade_plan_unavailable" if not s.get("position_setup_json") else None),
          "freshness":_field(metrics.get("freshness"), "freshness_unavailable"), "availability":_field(payload.get("capture_limitations"), "availability_unavailable"), "acquisition_path":_field(metrics.get("source_capture") if not primary_decisions else None, "acquisition_path_unavailable_non_causal"),
          "outcome": {"status":status, "reasons":reasons, "horizon_seconds":_field((o or {}).get("horizon_seconds"), "outcome_unavailable" if not o else None), "observed_candles":_field((o or {}).get("observed_candles"), "outcome_unavailable" if not o else None), "expected_candles":_field((o or {}).get("expected_candles"), "outcome_unavailable" if not o else None), "entry_price":_field(s.get("entry_price"), "entry_price_unavailable"), "exit_price":_field(costs.get("exit_price"), "exit_price_unavailable"), "gross_r":_field(costs.get("gross_r") or (o or {}).get("gross_realized_r"), "gross_r_unavailable"), "costs":{k:_field(v, "cost_not_recorded") for k,v in cost_values.items()}, "source":_field((o or {}).get("price_source"), "outcome_unavailable" if not o else None), "resolved_at":_field((o or {}).get("resolved_at"), "outcome_unavailable" if not o else None)},
          "scientific_eligibility":{"eligible": status == "COMPLETE" and all(v is not None for v in cost_values.values()), "reason": None if status == "COMPLETE" and all(v is not None for v in cost_values.values()) else "incomplete_outcome_or_cost_packet"}}
        records.append(record)
    records.sort(key=lambda r: (str(r.get("symbol")), r.get("signal_id") if isinstance(r.get("signal_id"), int) else -1))
    data_path = out / "normalized_research.jsonl"
    lines = "".join(json.dumps(_json(r), sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n" for r in records)
    data_path.write_text(lines, encoding="utf-8")
    counts = collections.Counter(r["outcome"]["status"] for r in records)
    strata = collections.defaultdict(lambda: {"count": 0, "eligible_count": 0, "statuses": collections.Counter()})
    for r in records:
        availability = "AVAILABLE" if r["availability"]["value"] is not None else "UNAVAILABLE"
        key = (str(r["lifecycle_v1"]["value"]), availability)
        strata[key]["count"] += 1
        strata[key]["eligible_count"] += int(r["scientific_eligibility"]["eligible"])
        strata[key]["statuses"][r["outcome"]["status"]] += 1
    crosswalk = {
        "crosswalk_version": "score_readiness_crosswalk_v1",
        "method": "point_in_time_join_by_signal_id",
        "rows": [
            {"lifecycle": k[0], "availability": k[1], "count": v["count"],
             "scientifically_eligible_count": v["eligible_count"],
             "status_counts": {s: v["statuses"].get(s, 0) for s in STATUS}}
            for k, v in sorted(strata.items())
        ],
        "blocking_note": "Descriptive only; no thresholds, weights, or promotion decisions.",
    }
    crosswalk_bytes = (json.dumps(crosswalk, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (out / "score_readiness_crosswalk.json").write_bytes(crosswalk_bytes)
    manifest = {"manifest_version":"normalized_research_manifest_v1", "database":str(Path(db_path).name), "tables":sorted(tables), "record_count":len(records), "status_counts":{s:counts.get(s,0) for s in STATUS}, "scientifically_eligible_count":sum(r["scientific_eligibility"]["eligible"] for r in records), "jsonl_sha256":hashlib.sha256(lines.encode()).hexdigest(), "jsonl_bytes":len(lines.encode()), "crosswalk_sha256":hashlib.sha256(crosswalk_bytes).hexdigest(), "nulls_require_reasons":True}
    (out / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    conn.close(); return manifest

def main() -> None:
    p=argparse.ArgumentParser(); p.add_argument("--db", required=True); p.add_argument("--output-dir", required=True); p.add_argument("--print-manifest", action="store_true"); a=p.parse_args(); m=compile_dataset(a.db,a.output_dir)
    if a.print_manifest: print(json.dumps(m, sort_keys=True))
if __name__ == "__main__": main()
