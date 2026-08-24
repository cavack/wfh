"""Bounded, read-only API for deterministic paper portfolio research."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from waterfallhunter.core.execution_planning import (
    SHA256_HEX_PATTERN,
    RiskPolicy,
)
from waterfallhunter.core.canonical_json import canonical_json_bytes
from waterfallhunter.core.portfolio_replay import (
    PortfolioEvent,
    build_signal_level_research_report,
    replay_paper_portfolio,
)


MAX_REPLAY_EVENTS = 5_000
MAX_SIGNAL_ROWS = 5_000
MAX_REPLAY_PAYLOAD_BYTES = 10_000_000


class SignalResearchRow(BaseModel):
    """A signal-level observation kept separate from portfolio realizability."""

    model_config = ConfigDict(extra="allow", frozen=True)

    signal_id: str = Field(min_length=1)
    signal_triggered_at: int = Field(ge=0, strict=True)


class BacktestLabRequest(BaseModel):
    """Caller-controlled dataset inputs; policy controls are intentionally absent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["backtest_lab_request_v1"] = "backtest_lab_request_v1"
    artifact_key_id: Literal["wfh-backtest-hmac-v1"]
    artifact_hmac_sha256: str = Field(pattern=SHA256_HEX_PATTERN)
    dataset_manifest_hash: str = Field(pattern=SHA256_HEX_PATTERN)
    initial_equity: float = Field(gt=0, le=1_000_000_000, allow_inf_nan=False)
    events: tuple[PortfolioEvent, ...] = Field(max_length=MAX_REPLAY_EVENTS)
    signal_rows: tuple[SignalResearchRow, ...] = Field(
        default=(),
        max_length=MAX_SIGNAL_ROWS,
    )

    @model_validator(mode="after")
    def _bounded_serialized_payload(self) -> "BacktestLabRequest":
        encoded = json.dumps(
            self.model_dump(mode="json"),
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > MAX_REPLAY_PAYLOAD_BYTES:
            raise ValueError("replay payload exceeds the 10 MB processing limit")
        return self


class BacktestLabResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["backtest_lab_response_v1"]
    execution_mode: Literal["PAPER_ONLY"]
    strategy_equivalent: Literal[False]
    claims_allowed: Literal[False]
    promotion_allowed: Literal[False]
    risk_policy: dict[str, Any]
    portfolio_report: dict[str, Any]
    signal_level_report: dict[str, Any]
    limitations: tuple[str, ...]


def backtest_attestation_sha256(
    payload: BacktestLabRequest,
    *,
    artifact_hmac_key: str,
) -> str:
    material = payload.model_dump(mode="json", exclude={"artifact_hmac_sha256"})
    return hmac.new(
        artifact_hmac_key.encode("utf-8"),
        canonical_json_bytes(material),
        hashlib.sha256,
    ).hexdigest()


def _run_replay(payload: BacktestLabRequest) -> BacktestLabResponse:
    policy = RiskPolicy.v1()
    portfolio_report = replay_paper_portfolio(
        list(payload.events),
        initial_equity=payload.initial_equity,
        risk_policy=policy,
        dataset_manifest_hash=payload.dataset_manifest_hash,
    )
    signal_report = build_signal_level_research_report(
        [row.model_dump(mode="json") for row in payload.signal_rows],
        dataset_manifest_hash=payload.dataset_manifest_hash,
    )
    return BacktestLabResponse(
        contract_version="backtest_lab_response_v1",
        execution_mode="PAPER_ONLY",
        strategy_equivalent=False,
        claims_allowed=False,
        promotion_allowed=False,
        risk_policy=policy.model_dump(mode="json"),
        portfolio_report=portfolio_report,
        signal_level_report=signal_report,
        limitations=(
            "RESEARCH_ONLY_NOT_A_TRADING_SIGNAL",
            "NO_PROBABILITY_OR_PROFITABILITY_CLAIM",
            "NO_LIVE_ORDER_PATH",
            "STRATEGY_EQUIVALENCE_NOT_ESTABLISHED",
            "CALLER_DATASET_REQUIRES_INDEPENDENT_PROVENANCE_REVIEW",
        ),
    )


def build_backtest_lab_router(*, artifact_hmac_key: str | None = None) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/api/backtest-lab/contract",
        responses={422: {"description": "Unsupported query parameter"}},
    )
    async def backtest_lab_contract(request: Request):
        unsupported = sorted(request.query_params.keys())
        if unsupported:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "unsupported query parameter",
                    "unsupported_parameters": unsupported,
                    "allowed_parameters": [],
                },
            )
        policy = RiskPolicy.v1()
        return {
            "contract_version": "backtest_lab_contract_v1",
            "execution_mode": "PAPER_ONLY",
            "maximum_replay_events": MAX_REPLAY_EVENTS,
            "maximum_signal_rows": MAX_SIGNAL_ROWS,
            "maximum_processing_payload_bytes": MAX_REPLAY_PAYLOAD_BYTES,
            "artifact_authentication": "HMAC_SHA256_REQUIRED",
            "artifact_key_id": "wfh-backtest-hmac-v1",
            "risk_policy": policy.model_dump(mode="json"),
            "caller_risk_overrides_allowed": False,
            "database_writes": False,
            "strategy_equivalent": False,
            "claims_allowed": False,
            "promotion_allowed": False,
        }

    @router.post(
        "/api/backtest-lab/replay",
        response_model=BacktestLabResponse,
        responses={
            413: {"description": "Request body exceeds ingress limit"},
            422: {"description": "Invalid or unsafe replay request"},
            503: {"description": "Artifact verification is not configured"},
        },
    )
    async def backtest_lab_replay(payload: BacktestLabRequest):
        if artifact_hmac_key is None or len(artifact_hmac_key.encode("utf-8")) < 32:
            raise HTTPException(
                status_code=503,
                detail="backtest artifact verification is unavailable",
            )
        expected = backtest_attestation_sha256(
            payload,
            artifact_hmac_key=artifact_hmac_key,
        )
        if not hmac.compare_digest(expected, payload.artifact_hmac_sha256):
            raise HTTPException(status_code=422, detail="backtest artifact attestation invalid")
        try:
            return await asyncio.to_thread(_run_replay, payload)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": "replay rejected", "reason": str(exc)},
            ) from exc

    return router
