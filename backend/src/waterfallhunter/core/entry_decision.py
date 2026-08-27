"""Canonical, user-facing entry decision for WaterfallHunter.

The engine is pure and intentionally separates lifecycle context from the
single actionable decision exposed to the dashboard and notifications.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class EntryDecisionPolicy:
    version: str = "entry_policy_v1"
    forming_minimum: float = 55.0
    entry_ready_minimum: float = 78.0
    max_analysis_age_seconds: float = 180.0
    max_reference_age_seconds: float = 60.0
    anti_chase_hard_block_atr: float = 1.2
    maximum_spread_pct: float = 0.30
    maximum_slippage_pct: float = 0.30


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}

def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(float(value), upper))


def _ramp(value: float, lower: float, upper: float, maximum: float) -> float:
    if upper <= lower:
        return 0.0
    return _clamp((value - lower) / (upper - lower), 0.0, 1.0) * maximum


def _has_number(packet: dict[str, Any], key: str) -> bool:
    return _finite(packet.get(key)) is not None


def _structure_points(metrics: dict[str, Any]) -> tuple[float, float, list[str]]:
    candles = _record(metrics.get("candle_features"))
    context = _record(candles.get("4h"))
    if context.get("valid") is not True:
        return 0.0, 0.0, ["STRUCTURE_UNAVAILABLE"]
    score = 0.0
    score += 4.0 if context.get("hype_context") is True else 0.0
    score += 4.0 if context.get("lower_high") is True else 0.0
    score += 5.0 if context.get("setup") == "FAILED_PULLBACK" else 0.0
    score += 3.0 if context.get("bearish_close") is True else 0.0
    score += 2.0 if context.get("volume_acceleration") is True else 0.0
    reasons = ["STRUCTURE_SUPPORTIVE"] if score >= 10.0 else ["STRUCTURE_WEAK"]
    return score, 20.0, reasons


def _timing_points(metrics: dict[str, Any]) -> tuple[float, float, list[str]]:
    candles = _record(metrics.get("candle_features"))
    score = 0.0
    available = 0.0
    for timeframe in ("1h", "15m", "5m"):
        context = _record(candles.get(timeframe))
        if context.get("valid") is not True:
            continue
        available += 5.0
        ready = bool(
            context.get("lower_high") is True
            and (context.get("reclaim") is True or context.get("repump") is True)
            and context.get("rsi_rollover") is True
            and context.get("bearish_close") is True
        )
        if ready:
            score += 5.0
    if available == 0:
        return 0.0, 0.0, ["TIMING_UNAVAILABLE"]
    return score, available, ["TIMING_CONFIRMED" if score >= 10.0 else "TIMING_INCOMPLETE"]


def _order_flow_points(metrics: dict[str, Any]) -> tuple[float, float, list[str], bool]:
    micro = _record(metrics.get("microstructure"))
    derivatives = _record(metrics.get("derivatives"))
    taker_ratio = _finite(derivatives.get("taker_buy_sell_ratio"))
    sell_flow = _finite(micro.get("sell_flow_usdt"))
    buy_flow = _finite(micro.get("buy_flow_usdt"))
    footprint = _record(micro.get("footprint"))
    available = 0.0
    score = 0.0

    if taker_ratio is not None:
        available += 10.0
        if taker_ratio <= 0.8:
            score += 10.0
        elif taker_ratio <= 0.9:
            score += 8.0
        elif taker_ratio < 1.0:
            score += 6.0
        elif taker_ratio <= 1.1:
            score += 3.0

    if sell_flow is not None and buy_flow is not None:
        available += 5.0
        total = sell_flow + buy_flow
        if total > 0:
            sell_share = sell_flow / total
            score += _ramp(sell_share, 0.5, 0.75, 5.0)

    if isinstance(footprint.get("aggressive_selling"), bool):
        available += 3.0
        if footprint.get("available") is True and footprint.get("aggressive_selling") is True:
            score += 3.0

    if isinstance(micro.get("approved"), bool):
        available += 2.0
        if micro.get("approved") is True and micro.get("spoofing_detected") is not True:
            score += 2.0

    direction_ok = bool(
        (taker_ratio is not None and taker_ratio < 1.0)
        or (sell_flow is not None and buy_flow is not None and sell_flow > buy_flow)
    )
    reason = "SELL_PRESSURE_CONFIRMED" if direction_ok else "BUYERS_ACTIVE"
    return score, available, [reason], direction_ok

def _derivative_points(metrics: dict[str, Any]) -> tuple[float, float, list[str]]:
    derivatives = _record(metrics.get("derivatives"))
    if derivatives.get("available") is not True:
        return 0.0, 0.0, ["DERIVATIVES_UNAVAILABLE"]

    score = 0.0
    available = 0.0
    funding = _finite(derivatives.get("funding_rate"))
    funding_percentile = _finite(derivatives.get("funding_percentile"))
    oi_change = _finite(derivatives.get("oi_change_1h_pct"))
    taker_change = _finite(derivatives.get("taker_ratio_change_1h"))
    top_ratio = _finite(derivatives.get("top_trader_long_short_ratio"))
    taker_ratio = _finite(derivatives.get("taker_buy_sell_ratio"))

    if funding is not None:
        available += 2.0
        if funding > 0:
            score += min(2.0, _ramp(funding, 0.0, 0.0005, 2.0))

    if funding_percentile is not None:
        available += 4.0
        score += _ramp(funding_percentile, 0.5, 0.95, 4.0)

    if oi_change is not None:
        available += 4.0
        if oi_change >= 0.5:
            score += 4.0
        elif oi_change > 0:
            score += 3.0
        elif oi_change >= -0.25:
            score += 2.0
        elif oi_change >= -0.5:
            score += 1.0

    if top_ratio is not None:
        available += 3.0
        if taker_ratio is None or taker_ratio <= 1.5:
            score += _ramp(top_ratio, 1.2, 2.0, 3.0)

    if taker_change is not None:
        available += 2.0
        if taker_ratio is not None and taker_ratio < 1.0 and taker_change < 0:
            score += _ramp(abs(taker_change), 0.1, 0.4, 2.0)

    reasons: list[str] = []
    if top_ratio is not None and top_ratio >= 1.5:
        reasons.append("LONG_CROWDING_PRESENT")
    if funding is not None and funding < 0:
        reasons.append("SHORT_SQUEEZE_RISK")
    if oi_change is not None and oi_change <= -0.5:
        reasons.append("OI_UNWINDING")
    return score, available, reasons

def _execution_points(metrics: dict[str, Any], policy: EntryDecisionPolicy) -> tuple[float, float, list[str], bool]:
    micro = _record(metrics.get("microstructure"))
    approved = micro.get("approved")
    spread = _finite(micro.get("spread_pct"))
    slippage = _finite(micro.get("slippage_pct"))
    bid_depth = _finite(micro.get("bid_depth_usdt"))
    ask_depth = _finite(micro.get("ask_depth_usdt"))
    available = 0.0
    score = 0.0

    if isinstance(approved, bool):
        available += 4.0
        if approved and micro.get("spoofing_detected") is not True:
            score += 4.0
    if spread is not None:
        available += 2.0
        if spread <= 0.10:
            score += 2.0
        elif spread <= policy.maximum_spread_pct:
            score += 1.0
    if slippage is not None:
        available += 2.0
        if slippage <= 0.10:
            score += 2.0
        elif slippage <= policy.maximum_slippage_pct:
            score += 1.0
    if bid_depth is not None and ask_depth is not None:
        available += 2.0
        if bid_depth > 0 and ask_depth > 0:
            score += 2.0

    execution_ok = bool(
        approved is True
        and spread is not None
        and slippage is not None
        and spread <= policy.maximum_spread_pct
        and slippage <= policy.maximum_slippage_pct
    )
    return score, available, ["EXECUTION_OK" if execution_ok else "EXECUTION_DEGRADED"], execution_ok

def _cross_exchange_points(metrics: dict[str, Any]) -> tuple[float, float, list[str], bool]:
    breakdown = _record(metrics.get("breakdown_confirmation"))
    value = breakdown.get("confirmation_exchange_15m")
    if not isinstance(value, bool):
        return 0.0, 0.0, ["CROSS_EXCHANGE_UNAVAILABLE"], False
    return (5.0 if value else 0.0), 5.0, ["CROSS_EXCHANGE_CONFIRMED" if value else "CROSS_EXCHANGE_DISAGREEMENT"], value


def _price_location_points(metrics: dict[str, Any]) -> tuple[float, float, list[str]]:
    location = _record(metrics.get("price_location"))
    below_vwap = location.get("below_vwap")
    if not isinstance(below_vwap, bool):
        return 0.0, 0.0, ["PRICE_LOCATION_UNAVAILABLE"]
    return (5.0 if below_vwap else 0.0), 5.0, ["BELOW_VWAP" if below_vwap else "ABOVE_VWAP"]


def _cascade_points(metrics: dict[str, Any]) -> tuple[float, float, list[str]]:
    cascade = _record(metrics.get("cascade_intelligence"))
    points = _finite(cascade.get("readiness_points"))
    if points is None:
        return 0.0, 0.0, ["CASCADE_EVIDENCE_UNAVAILABLE"]
    status = str(cascade.get("status") or "UNAVAILABLE")
    return _clamp(points, 0.0, 10.0), 10.0, [f"CASCADE_{status}"]


def _trade_plan(metrics: dict[str, Any]) -> dict[str, Any] | None:
    setup = _record(metrics.get("position_setup"))
    required = ("entry_price", "stop_loss", "take_profit_1", "take_profit_2")
    if str(setup.get("status") or "").upper().startswith("REJECTED"):
        return None
    if not all(_has_number(setup, key) for key in required):
        return None
    return {
        "entry_price": float(setup["entry_price"]),
        "stop_loss": float(setup["stop_loss"]),
        "take_profit_1": float(setup["take_profit_1"]),
        "take_profit_2": float(setup["take_profit_2"]),
        "take_profit_3": _finite(setup.get("take_profit_3")),
        "reward_to_risk": _finite(setup.get("reward_to_risk")),
        "leverage": _finite(metrics.get("applied_leverage")),
    }

def _anti_chase_extension(metrics: dict[str, Any]) -> float | None:
    anti = _record(metrics.get("anti_chase"))
    cross = _record(anti.get("cross_timeframe"))
    return _finite(cross.get("max_post_break_extension_atr"))


def build_entry_decision(
    metrics: dict[str, Any],
    candidate_status: str,
    *,
    evaluated_at: int,
    analysis_age_seconds: float | None,
    reference_age_seconds: float | None,
    policy: EntryDecisionPolicy | None = None,
) -> dict[str, Any]:
    policy = policy or EntryDecisionPolicy()
    reasons: list[str] = []
    block_reasons: list[str] = []
    status = str(candidate_status or "WATCH").upper()

    analysis_age = _finite(analysis_age_seconds)
    reference_age = _finite(reference_age_seconds)
    if analysis_age is None or analysis_age > policy.max_analysis_age_seconds:
        block_reasons.append("STALE_ANALYSIS")
    if reference_age is None or reference_age > policy.max_reference_age_seconds:
        block_reasons.append("STALE_REFERENCE")

    if status == "INVALIDATED":
        block_reasons.append("STRUCTURE_INVALIDATED")

    extension = _anti_chase_extension(metrics)
    late = bool(
        status == "EXHAUSTED"
        or (extension is not None and extension >= policy.anti_chase_hard_block_atr)
    )
    if late:
        block_reasons.append("ANTI_CHASE_HARD_BLOCK")

    components: dict[str, dict[str, float]] = {}
    total_points = 0.0
    available_weight = 0.0

    structure, maximum, component_reasons = _structure_points(metrics)
    components["structure"] = {"points": round(structure, 2), "maximum": maximum}
    total_points += structure
    available_weight += maximum
    reasons.extend(component_reasons)

    timing, maximum, component_reasons = _timing_points(metrics)
    components["timing"] = {"points": round(timing, 2), "maximum": maximum}
    total_points += timing
    available_weight += maximum
    reasons.extend(component_reasons)

    order_flow, maximum, component_reasons, direction_ok = _order_flow_points(metrics)
    components["order_flow"] = {"points": round(order_flow, 2), "maximum": maximum}
    total_points += order_flow
    available_weight += maximum
    reasons.extend(component_reasons)

    derivatives, maximum, component_reasons = _derivative_points(metrics)
    components["derivatives"] = {"points": round(derivatives, 2), "maximum": maximum}
    total_points += derivatives
    available_weight += maximum
    reasons.extend(component_reasons)

    execution, maximum, component_reasons, execution_ok = _execution_points(metrics, policy)
    components["execution"] = {"points": round(execution, 2), "maximum": maximum}
    total_points += execution
    available_weight += maximum
    reasons.extend(component_reasons)

    cross, maximum, component_reasons, cross_ok = _cross_exchange_points(metrics)
    components["cross_exchange"] = {"points": round(cross, 2), "maximum": maximum}
    total_points += cross
    available_weight += maximum
    reasons.extend(component_reasons)

    location, maximum, component_reasons = _price_location_points(metrics)
    components["price_location"] = {"points": round(location, 2), "maximum": maximum}
    total_points += location
    available_weight += maximum
    reasons.extend(component_reasons)

    cascade, maximum, component_reasons = _cascade_points(metrics)
    components["cascade"] = {"points": round(cascade, 2), "maximum": maximum}
    total_points += cascade
    available_weight += maximum
    reasons.extend(component_reasons)

    readiness = round(_clamp(total_points, 0.0, 100.0), 2)
    coverage_pct = round(_clamp(available_weight, 0.0, 100.0), 2)
    timing_ok = timing >= 10.0
    trade_plan = _trade_plan(metrics)
    trade_plan_ok = trade_plan is not None
    if not trade_plan_ok:
        reasons.append("TRADE_PLAN_UNAVAILABLE")

    if block_reasons:
        decision = "LATE" if late and "STRUCTURE_INVALIDATED" not in block_reasons else "INVALIDATED" if "STRUCTURE_INVALIDATED" in block_reasons else "NO_TRADE"
    elif (
        readiness >= policy.entry_ready_minimum
        and coverage_pct >= 65.0
        and direction_ok
        and timing_ok
        and execution_ok
        and cross_ok
        and trade_plan_ok
    ):
        decision = "ACTIVE" if status == "TRIGGERED" else "ENTRY_READY"
        reasons.append("ENTRY_GATES_PASS")
    elif readiness >= policy.forming_minimum:
        decision = "FORMING"
    else:
        decision = "NO_TRADE"

    packet = {
        "contract_version": "entry_decision_v1",
        "policy_version": policy.version,
        "evaluated_at": int(evaluated_at),
        "decision": decision,
        "lifecycle_state": status,
        "entry_readiness": readiness,
        "evidence_coverage_pct": coverage_pct,
        "hard_blocked": bool(block_reasons),
        "block_reasons": sorted(set(block_reasons)),
        "reason_codes": sorted(set(reasons)),
        "components": components,
        "trade_plan": trade_plan,
        "policy": asdict(policy),
    }
    return packet
