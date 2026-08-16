import math
from statistics import median
from typing import Any


class FinalRanking:
    """Read-only ranking over already-produced candidate measurements."""

    VERSION = "final_ranking_observational_v1"
    WEIGHTS = {
        "cascade_readiness": 25.0,
        "signal_score": 20.0,
        "execution_quality": 20.0,
        "relative_weakness": 15.0,
        "empirical_probability": 10.0,
        "freshness": 10.0,
    }

    @staticmethod
    def _finite(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        return number if math.isfinite(number) else None

    @classmethod
    def _component(cls, value: float | None, weight: float, reason: str | None = None) -> dict:
        if value is None:
            return {"available": False, "value": None, "weight": weight, "points": None, "reason": reason}
        bounded = min(max(float(value), 0.0), 1.0)
        return {"available": True, "value": round(bounded, 6), "weight": weight, "points": round(bounded * weight, 6)}

    @classmethod
    def _readiness(cls, candidate: dict, metrics: dict) -> float | None:
        stages = metrics.get("strategy_stages")
        if isinstance(stages, dict):
            fields = ("hype", "damage", "setup", "trigger")
            if all(isinstance(stages.get(field), bool) for field in fields):
                return sum(stages[field] for field in fields) / len(fields)
        status = candidate.get("status") or metrics.get("observation_status")
        return {
            "WATCH": 0.0, "FUEL-RICH": 0.25, "PRE-TRIGGER": 0.5,
            "ARMED": 0.75, "TRIGGERED": 1.0,
        }.get(status)

    @classmethod
    def _relative_weakness(cls, metrics: dict) -> float | None:
        packet = metrics.get("relative_weakness_features")
        timeframes = packet.get("timeframes") if isinstance(packet, dict) and packet.get("available") is True else None
        if not isinstance(timeframes, dict):
            return None
        values = []
        for timeframe in ("4h", "1h", "15m", "5m"):
            fields = timeframes.get(timeframe)
            if not isinstance(fields, dict):
                continue
            value = cls._finite(fields.get("relative_return_6bars_pct"))
            if value is not None:
                values.append(value)
        if not values:
            return None
        # 0% relative return scores neutral; -5% or weaker reaches the cap.
        return min(max(-median(values) / 5.0, 0.0), 1.0)

    @classmethod
    def for_candidate(cls, symbol: str, candidate: dict) -> dict:
        metrics = candidate.get("metrics") if isinstance(candidate.get("metrics"), dict) else {}
        score = cls._finite(candidate.get("score"))
        if score is None:
            score = cls._finite(metrics.get("observation_score"))
        execution = candidate.get("execution_suitability")
        execution_status = execution.get("status") if isinstance(execution, dict) else None
        probability = None
        position = metrics.get("position_setup")
        if isinstance(position, dict):
            raw_probability = cls._finite(position.get("tp_24h_probability"))
            if raw_probability is not None:
                probability = raw_probability / 100.0 if raw_probability > 1.0 else raw_probability
        age = cls._finite(candidate.get("age_seconds"))
        components = {
            "cascade_readiness": cls._component(
                cls._readiness(candidate, metrics), cls.WEIGHTS["cascade_readiness"], "lifecycle stages unavailable",
            ),
            "signal_score": cls._component(
                score / 100.0 if score is not None else None, cls.WEIGHTS["signal_score"], "live and observation scores unavailable",
            ),
            "execution_quality": cls._component(
                {"SUITABLE": 1.0, "MARGINAL": 0.6, "POOR": 0.0}.get(execution_status),
                cls.WEIGHTS["execution_quality"], "execution suitability unavailable or unknown",
            ),
            "relative_weakness": cls._component(
                cls._relative_weakness(metrics), cls.WEIGHTS["relative_weakness"], "benchmark-relative returns unavailable",
            ),
            "empirical_probability": cls._component(
                probability, cls.WEIGHTS["empirical_probability"], "candidate-specific empirical probability unavailable",
            ),
            "freshness": cls._component(
                max(0.0, 1.0 - age / 180.0) if age is not None and age >= 0 else None,
                cls.WEIGHTS["freshness"], "observation age unavailable",
            ),
        }
        available_weight = sum(packet["weight"] for packet in components.values() if packet["available"])
        points = sum(packet["points"] for packet in components.values() if packet["available"])
        normalized = points / available_weight * 100.0 if available_weight else None
        confidence = available_weight / sum(cls.WEIGHTS.values())
        ranking_score = normalized * confidence if normalized is not None else None
        missing = [name for name, packet in components.items() if not packet["available"]]
        return {
            "version": cls.VERSION,
            "symbol": symbol,
            "score": round(ranking_score, 6) if ranking_score is not None else None,
            "normalized_available_score": round(normalized, 6) if normalized is not None else None,
            "confidence": round(confidence, 6),
            "available_weight": available_weight,
            "components": components,
            "missing_components": missing,
            "anti_chase": {"status": "NOT_EVALUATED", "veto": None, "reason": "no calibrated anti-chase decision packet"},
            "observational_only": True,
            "trade_eligible": None,
        }

    @classmethod
    def rank(cls, candidates: dict[str, dict], limit: int = 3) -> dict:
        packets = [cls.for_candidate(symbol, candidate) for symbol, candidate in candidates.items()]
        packets.sort(key=lambda packet: (
            packet["score"] is not None,
            packet["score"] if packet["score"] is not None else -1.0,
            packet["confidence"],
            packet["symbol"],
        ), reverse=True)
        for index, packet in enumerate(packets, start=1):
            packet["rank"] = index
        return {
            "version": cls.VERSION,
            "observational_only": True,
            "trade_eligible": None,
            "ranked_count": len(packets),
            "top": packets[:max(0, int(limit))],
            "all": packets,
        }
