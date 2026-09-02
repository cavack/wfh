"""Pure scheduling helpers for the live hunter loop."""

from __future__ import annotations

from typing import Any, Mapping


DEFAULT_EVALUATION_CONCURRENCY = 12

_STATE_PRIORITY = {
    "TRIGGERED": 0,
    "ARMED": 1,
    "PRE-TRIGGER": 2,
    "FUEL-RICH": 3,
    "WATCH": 4,
}


def remaining_cycle_delay(
    cycle_started_at: float,
    now: float,
    target_interval_seconds: float,
) -> float:
    """Return delay needed to maintain a start-to-start target period."""
    elapsed = max(0.0, float(now) - float(cycle_started_at))
    return max(0.0, float(target_interval_seconds) - elapsed)


def ordered_hunter_candidates(
    candidates: Mapping[str, dict[str, Any]],
    live_candidates: Mapping[str, dict[str, Any]] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Prioritize near-trigger states, then the stalest observation."""
    live = live_candidates or {}

    def sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, float, str]:
        symbol, data = item
        state = str(data.get("status") or "WATCH").upper()
        live_data = live.get(symbol) if isinstance(live.get(symbol), dict) else {}
        observed_at = live_data.get("analysis_observed_at")
        if isinstance(observed_at, bool) or not isinstance(observed_at, (int, float)):
            observed_at = 0.0
        return (_STATE_PRIORITY.get(state, 5), float(observed_at), symbol)

    return sorted(candidates.items(), key=sort_key)
