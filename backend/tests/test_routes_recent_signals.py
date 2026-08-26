from fastapi import FastAPI
from fastapi.testclient import TestClient

from schema_test_support import migrate_test_database
from waterfallhunter.core.contracts import SignalClass
from waterfallhunter.core.db import DBAdapter
from waterfallhunter.core.lbank_signal_ledger import LBankSignalLedger
from waterfallhunter.core.signal_metadata import (
    ClassificationMethod,
    MODEL_GENERATION,
    STRICT_STRATEGY_PROFILE,
    SignalMetadataInput,
)
from waterfallhunter.routes_recent_signals import build_recent_signals_router

SYMBOL = "RECENT/USDT:USDT"


def _metadata() -> SignalMetadataInput:
    return SignalMetadataInput(
        signal_class=SignalClass.STRICT,
        strategy_profile=STRICT_STRATEGY_PROFILE,
        score_version="score_v2",
        model_generation=MODEL_GENERATION,
        decision_contract_hash="a" * 64,
        analysis_observed_at=1_700_000_000,
        reference_observed_at=1_699_999_990,
        classification_method=ClassificationMethod.FUTURE_PIPELINE_EXPLICIT,
        classification_evidence_hash=None,
    )


def test_recent_signals_route_returns_immutable_trigger_history_with_leverage(tmp_path):
    db_path = migrate_test_database(tmp_path / "recent.db")
    db = DBAdapter(str(db_path))
    db.update_candidates(
        {
            SYMBOL: {
                "last_price": 0.01,
                "quote_volume": 3_000_000.0,
                "is_meme": False,
                "scan_eligible": True,
            }
        }
    )
    assert db.update_candidate_state(SYMBOL, "ARMED")
    metrics = {
        "strategy_profile": STRICT_STRATEGY_PROFILE,
        "score_version": "score_v2",
        "applied_leverage": 11,
        "leverage_policy": {
            "version": "adaptive_signal_leverage_v1",
            "minimum": 4,
            "maximum": 18,
        },
        "position_setup": {
            "entry_price": 0.0101,
            "stop_loss": 0.0105,
            "take_profit_1": 0.0097,
            "take_profit_2": 0.0093,
        },
    }
    signal_id = LBankSignalLedger(str(db_path)).persist_trigger(
        SYMBOL,
        "ARMED",
        score=91.5,
        trigger_metrics=metrics,
        execution_suitability={"status": "SUITABLE", "failed_checks": []},
        metadata=_metadata(),
        triggered_at=1_700_000_010,
    )
    assert signal_id == 1

    app = FastAPI()
    app.include_router(build_recent_signals_router(str(db_path)))
    response = TestClient(app).get("/api/recent-signals?limit=10")
    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "recent_signal_history_v1"
    assert body["operational"] is True
    assert body["observational_only"] is True
    assert body["hard_gating_allowed"] is False
    assert body["count"] == 1
    row = body["signals"][0]
    assert row["signal_id"] == 1
    assert row["symbol"] == SYMBOL
    assert row["signal_class"] == "STRICT"
    assert row["strategy_profile"] == STRICT_STRATEGY_PROFILE
    assert row["score"] == 91.5
    assert row["applied_leverage"] == 11
    assert row["leverage_policy"]["maximum"] == 18
    assert row["entry_price"] == 0.0101


def test_recent_signals_route_rejects_unsupported_or_out_of_range_queries(tmp_path):
    db_path = migrate_test_database(tmp_path / "recent-empty.db")
    app = FastAPI()
    app.include_router(build_recent_signals_router(str(db_path)))
    client = TestClient(app)
    assert client.get("/api/recent-signals?promote=true").status_code == 422
    assert client.get("/api/recent-signals?limit=101").status_code == 422
