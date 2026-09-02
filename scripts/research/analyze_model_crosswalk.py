#!/usr/bin/env python3
"""Produce deterministic P0-D model-layer and evidence-reuse artifacts."""
from __future__ import annotations
import argparse, collections, hashlib, json
from pathlib import Path

NOT_RUN = "NOT_RUN_INSUFFICIENT_EVIDENCE"

def _read(path: Path) -> list[dict]:
    if not path.exists(): return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

def _value(row, key):
    field = row.get(key)
    return field.get("value") if isinstance(field, dict) else field

def _reason(row, key):
    field = row.get(key)
    return field.get("reason") if isinstance(field, dict) else None

def _artifact_status(rows: list[dict]) -> str:
    return "COMPLETE" if rows and any(r.get("outcome", {}).get("status") == "COMPLETE" for r in rows) else NOT_RUN

def analyze(rows: list[dict], *, input_name: str = "normalized_research.jsonl") -> tuple[dict, dict]:
    status = _artifact_status(rows)
    if status == NOT_RUN:
        base = {"status": NOT_RUN, "reason": "no normalized runtime rows with complete outcomes", "input": input_name, "matched_packet_count": 0}
        reuse = {"status": NOT_RUN, "reason": "no normalized runtime rows with complete outcomes", "input": input_name, "row_count": len(rows), "families": []}
        return base, reuse
    matched = [r for r in rows if r.get("packet_id") is not None]
    availability = collections.Counter()
    transitions = collections.Counter()
    blockers = collections.Counter()
    joint = collections.Counter()
    readiness_delta, coverage_delta = [], []
    family_use = collections.defaultdict(lambda: {"rows": 0, "available": 0, "unavailable": 0, "reasons": collections.Counter()})
    for r in matched:
        avail = "available" if _value(r, "availability") is not None else "unavailable"
        availability[avail] += 1
        old = _value(r, "lifecycle_v1")
        new = _value(r, "readiness")
        transitions[f"{old or 'NULL'}->{new or 'NULL'}"] += 1
        rs = tuple(sorted(set(r.get("outcome", {}).get("reasons", []))))
        if not rs: rs = ("none",)
        blockers[rs[0]] += 1
        if len(rs) > 1: joint[" + ".join(rs)] += 1
        for family in ("availability", "acquisition_path", "freshness", "components", "gates", "trade_plan"):
            f = family_use[family]; f["rows"] += 1
            value, reason = _value(r, family), _reason(r, family)
            if value is None:
                f["unavailable"] += 1
                if reason: f["reasons"][reason] += 1
            else: f["available"] += 1
        rv, cv = _value(r, "readiness"), _value(r, "coverage")
        if isinstance(rv, (int, float)) and isinstance(cv, (int, float)):
            readiness_delta.append(float(rv) - float(cv))
        # Coverage delta is expressed against the normalized expected complete horizon.
        expected = r.get("outcome", {}).get("expected_candles", {}).get("value")
        observed = r.get("outcome", {}).get("observed_candles", {}).get("value")
        if isinstance(expected, (int, float)) and isinstance(observed, (int, float)) and expected:
            coverage_delta.append(float(observed) - float(expected))
    def counts(counter): return {str(k): counter[k] for k in sorted(counter)}
    crosswalk = {
        "artifact": "MODEL_LAYER_CROSSWALK",
        "version": "v1",
        "status": status,
        "input": input_name,
        "matched_packet_count": len(matched),
        "availability_differences": {"available": availability["available"], "unavailable": availability["unavailable"], "difference": availability["available"] - availability["unavailable"]},
        "decision_transitions": counts(transitions),
        "first_blockers": counts(blockers),
        "joint_blockers": counts(joint),
        "readiness_coverage_deltas": {"readiness_minus_coverage": {"count": len(readiness_delta), "mean": sum(readiness_delta) / len(readiness_delta) if readiness_delta else None, "reason": None if readiness_delta else "readiness_or_coverage_not_numeric"}, "observed_minus_expected_candles": {"count": len(coverage_delta), "mean": sum(coverage_delta) / len(coverage_delta) if coverage_delta else None, "reason": None if coverage_delta else "horizon_unavailable_or_incomplete"}},
    }
    families = []
    for name in sorted(family_use):
        f = family_use[name]
        families.append({"family": name, "rows": f["rows"], "available": f["available"], "unavailable": f["unavailable"], "unavailable_reasons": counts(f["reasons"])})
    reuse = {"artifact": "EVIDENCE_REUSE_MATRIX", "version": "v1", "status": status, "input": input_name, "row_count": len(rows), "families": families, "reuse_rule": "one immutable normalized packet may contribute to each explicitly available family; unavailable is never imputed"}
    return crosswalk, reuse

def run(input_path: str | Path, output_dir: str | Path) -> tuple[dict, dict]:
    source = Path(input_path); out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    crosswalk, reuse = analyze(_read(source), input_name=source.name)
    for name, value in (("MODEL_LAYER_CROSSWALK.json", crosswalk), ("EVIDENCE_REUSE_MATRIX.json", reuse)):
        (out / name).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return crosswalk, reuse

def main():
    p = argparse.ArgumentParser(); p.add_argument("--input", required=True); p.add_argument("--output-dir", required=True); p.add_argument("--print-summary", action="store_true"); a = p.parse_args(); c, r = run(a.input, a.output_dir)
    if a.print_summary: print(json.dumps({"crosswalk": c, "reuse": r}, sort_keys=True))
if __name__ == "__main__": main()
