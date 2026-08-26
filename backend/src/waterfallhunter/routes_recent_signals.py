from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from waterfallhunter.core.managed_sqlite import connect_managed_sqlite


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _build_report(db_path: str, limit: int) -> dict[str, Any]:
    with connect_managed_sqlite(db_path, timeout=10.0) as conn:
        rows = conn.execute(
            """
            SELECT l.id, l.symbol, l.triggered_at, l.state_before, l.score,
                   l.entry_price, l.stop_loss, l.take_profit_1, l.take_profit_2,
                   l.trigger_metrics_json, l.execution_status,
                   m.signal_class, m.strategy_profile, m.score_version,
                   o.outcome_status, o.resolved_at
            FROM lbank_signal_ledger AS l
            JOIN signal_metadata AS m ON m.signal_id = l.id
            LEFT JOIN lbank_signal_outcomes AS o ON o.id = (
                SELECT o2.id FROM lbank_signal_outcomes AS o2
                WHERE o2.signal_id = l.id
                ORDER BY o2.resolved_at DESC, o2.id DESC LIMIT 1
            )
            ORDER BY l.triggered_at DESC, l.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    signals = []
    for row in rows:
        metrics = _json_object(row[9])
        policy = _json_object(metrics.get("leverage_policy"))
        signals.append({
            "signal_id": int(row[0]), "symbol": str(row[1]),
            "triggered_at": int(row[2]), "state_before": str(row[3]),
            "score": float(row[4]), "entry_price": row[5],
            "stop_loss": row[6], "take_profit_1": row[7],
            "take_profit_2": row[8],
            "applied_leverage": metrics.get("applied_leverage"),
            "leverage_policy": policy,
            "execution_status": str(row[10]),
            "signal_class": str(row[11]), "strategy_profile": str(row[12]),
            "score_version": str(row[13]), "outcome_status": row[14],
            "outcome_resolved_at": row[15],
        })
    return {
        "contract_version": "recent_signal_history_v1",
        "operational": True,
        "observational_only": True,
        "hard_gating_allowed": False,
        "count": len(signals),
        "signals": signals,
    }


def build_recent_signals_router(db_path: str) -> APIRouter:
    router = APIRouter()

    @router.get("/api/recent-signals")
    async def recent_signals(
        request: Request,
        limit: int = Query(default=20, ge=1, le=100),
    ):
        unsupported = sorted(set(request.query_params.keys()) - {"limit"})
        if unsupported:
            raise HTTPException(status_code=422, detail={
                "error": "unsupported query parameter",
                "unsupported_parameters": unsupported,
                "allowed_parameters": ["limit"],
            })
        return await asyncio.to_thread(_build_report, db_path, limit)

    return router
