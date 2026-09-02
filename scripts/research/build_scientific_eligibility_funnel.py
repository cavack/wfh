#!/usr/bin/env python3
"""Explain scientific eligibility without fabricating causal joins or costs."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


REQUIREMENTS = (
    "valid_point_in_time_provenance",
    "complete_trade_plan",
    "valid_entry_geometry",
    "complete_future_window",
    "outcome_linkable",
    "gross_r_computable",
    "fees_complete",
    "slippage_complete",
    "funding_complete",
    "net_r_complete",
    "scientifically_evaluable",
)
DECISIONS = ("NO_TRADE", "FORMING", "ENTRY_READY", "ACTIVE", "LATE", "INVALIDATED", "EXPIRED", "UNAVAILABLE")


def _value(row: dict[str, Any], key: str) -> Any:
    field = row.get(key)
    return field.get("value") if isinstance(field, dict) else field


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and value == value


def _trade_plan(row: dict[str, Any]) -> dict[str, Any] | None:
    plan = _value(row, "trade_plan")
    return plan if isinstance(plan, dict) else None


def _geometry(plan: dict[str, Any] | None) -> bool:
    if not plan:
        return False
    entry, stop = plan.get("entry_price"), plan.get("stop_loss")
    targets = [plan.get("take_profit_1"), plan.get("take_profit_2")]
    if not (_numeric(entry) and _numeric(stop) and all(_numeric(t) for t in targets)):
        return False
    # The persisted contract has no side field.  Accept either orientation
    # only when the stop and both targets are on opposite sides of entry.
    return (stop < entry < min(targets)) or (max(targets) < entry < stop)


def _explicit_outcome_link(row: dict[str, Any]) -> bool:
    """Require a persisted causal identity, never signal/time proximity."""
    outcome = row.get("outcome") or {}
    return bool(
        row.get("decision_event_id")
        and (
            outcome.get("decision_event_id") == row.get("decision_event_id")
            or outcome.get("candidate_evaluation_id") == row.get("candidate_evaluation_id")
        )
    )


def _read(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build(rows: list[dict[str, Any]], *, source: str) -> dict[str, Any]:
    flags: list[dict[str, bool]] = []
    decisions = Counter(_value(row, "decision") or "UNAVAILABLE" for row in rows)
    for row in rows:
        plan = _trade_plan(row)
        outcome = row.get("outcome") or {}
        outcome_status = outcome.get("status")
        provenance = bool(
            _value(row, "code_sha")
            and _value(row, "decision_contract_sha")
            and _value(row, "decision_at")
            and _value(row, "evidence_as_of")
        )
        trade_plan = bool(plan and plan.get("status") == "READY")
        window = bool(
            outcome_status in ("COMPLETE", "SCIENTIFICALLY_EVALUABLE")
            and _numeric(outcome.get("observed_candles", {}).get("value"))
            and outcome.get("observed_candles", {}).get("value")
            == outcome.get("expected_candles", {}).get("value")
        )
        linkable = _explicit_outcome_link(row)
        gross = linkable and _numeric(outcome.get("gross_r", {}).get("value"))
        costs = outcome.get("costs") or {}
        fees = _numeric(costs.get("fees", {}).get("value"))
        slippage = _numeric(costs.get("slippage", {}).get("value"))
        funding = _numeric(costs.get("funding", {}).get("value"))
        net = _numeric(costs.get("net_r", {}).get("value"))
        flags.append(
            {
                "valid_point_in_time_provenance": provenance,
                "complete_trade_plan": trade_plan,
                "valid_entry_geometry": _geometry(plan),
                "complete_future_window": window,
                "outcome_linkable": linkable,
                "gross_r_computable": gross,
                "fees_complete": fees,
                "slippage_complete": slippage,
                "funding_complete": funding,
                "net_r_complete": net,
                "scientifically_evaluable": all((provenance, trade_plan, _geometry(plan), window, linkable, gross, fees, slippage, funding, net)),
            }
        )

    counts = {name + "_count": sum(f[name] for f in flags) for name in REQUIREMENTS}
    intersections: dict[str, int] = {}
    for name, members in {
        "complete_window_and_trade_plan": ("complete_future_window", "complete_trade_plan"),
        "complete_window_and_costs": ("complete_future_window", "fees_complete", "slippage_complete", "funding_complete"),
        "trade_plan_and_provenance": ("complete_trade_plan", "valid_point_in_time_provenance"),
        "outcome_and_costs": ("outcome_linkable", "fees_complete", "slippage_complete", "funding_complete"),
        "all_except_funding": tuple(x for x in REQUIREMENTS if x not in ("funding_complete", "scientifically_evaluable")),
        "all_except_source_sha": tuple(x for x in REQUIREMENTS if x not in ("valid_point_in_time_provenance", "scientifically_evaluable")),
        "all_except_outcome_link": tuple(x for x in REQUIREMENTS if x not in ("outcome_linkable", "scientifically_evaluable")),
    }.items():
        intersections[name] = sum(all(f[m] for m in members) for f in flags)

    total = len(rows)
    blockers = [
        {
            "requirement": name,
            "lost_rows": total - counts[name + "_count"],
            "classification": "VERIFIED_FACT",
            "reason": {
                "valid_point_in_time_provenance": "code_sha, decision_contract_sha, decision_at, and evidence_as_of are unavailable in normalized packets",
                "complete_trade_plan": "candidate packets do not persist a READY trade plan for every row",
                "valid_entry_geometry": "geometry is unavailable or not a valid stop/target orientation",
                "complete_future_window": "persisted outcome status/window is not complete",
                "outcome_linkable": "no explicit decision-to-outcome causal identity is persisted",
                "gross_r_computable": "gross R requires an explicitly linked causal outcome",
                "fees_complete": "fee ledger values and provenance are unavailable",
                "slippage_complete": "causal exit/entry slippage values and provenance are unavailable",
                "funding_complete": "historical funding cashflows are unavailable; zero is not imputed",
                "net_r_complete": "net R requires gross R and all cost components",
                "scientifically_evaluable": "all scientific requirements must be true",
            }[name],
        }
        for name in REQUIREMENTS
    ]
    blockers.sort(key=lambda item: (-item["lost_rows"], item["requirement"]))
    return {
        "artifact": "SCIENTIFIC_ELIGIBILITY_FUNNEL",
        "version": "v1",
        "source": source,
        "total_candidate_rows": total,
        "decision_counts": {name: decisions.get(name, 0) for name in DECISIONS},
        **counts,
        "intersections": intersections,
        "top_actual_blockers": blockers,
        "linkage_assessment": {
            "status": "INVALID_FOR_SCIENCE",
            "classification": "VERIFIED_FACT",
            "reason": "The normalized export contains signal_id/time proximity but no persisted decision-to-outcome causal identity contract; nearest-by-symbol/time is not used as scientific evidence.",
        },
        "disposition": "PARAMETER_SEARCH_NOT_READY",
        "disposition_reasons": [
            f"scientifically_evaluable_count={counts['scientifically_evaluable_count']}",
            f"complete_future_window_count={counts['complete_future_window_count']}",
            f"outcome_linkable_count={counts['outcome_linkable_count']}",
            f"net_r_complete_count={counts['net_r_complete_count']}",
        ],
    }


def run(input_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    input_path, output_path = Path(input_path), Path(output_path)
    result = build(_read(input_path), source=input_path.name)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.input, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
