import asyncio
import time
import json
import sqlite3

import pytest

from schema_test_support import migrate_test_database
from waterfallhunter.core.entry_decision_store import EntryDecisionStore


def packet(decision: str, readiness: float, now: int) -> dict:
    return {
        "contract_version": "entry_decision_v1",
        "policy_version": "entry_policy_v1",
        "evaluated_at": now,
        "decision": decision,
        "lifecycle_state": "ARMED",
        "entry_readiness": readiness,
        "evidence_coverage_pct": 82.0,
        "hard_blocked": decision in {"LATE", "INVALIDATED"},
        "block_reasons": ["ANTI_CHASE_HARD_BLOCK"] if decision == "LATE" else [],
        "reason_codes": ["SELL_PRESSURE_CONFIRMED"],
        "components": {},
        "trade_plan": None,
        "policy": {},
    }


def test_store_appends_only_decision_transitions(tmp_path) -> None:
    db_path = migrate_test_database(tmp_path / "registry.db")
    store = EntryDecisionStore(db_path)

    first = store.append_if_changed("SXT/USDT:USDT", packet("ENTRY_READY", 84.0, 100))
    duplicate = store.append_if_changed("SXT/USDT:USDT", packet("ENTRY_READY", 85.0, 101))
    late = store.append_if_changed("SXT/USDT:USDT", packet("LATE", 82.0, 120))

    assert first is not None
    assert duplicate is None
    assert late is not None
    latest = store.latest_for_symbol("SXT/USDT:USDT")
    assert latest is not None
    assert latest["decision"] == "LATE"
    assert latest["entry_readiness"] == 82.0


def test_entry_ready_history_survives_later_transition(tmp_path) -> None:
    db_path = migrate_test_database(tmp_path / "registry.db")
    store = EntryDecisionStore(db_path)
    store.append_if_changed("SXT/USDT:USDT", packet("ENTRY_READY", 84.0, 100))
    store.append_if_changed("SXT/USDT:USDT", packet("INVALIDATED", 40.0, 130))
    history = store.history_for_symbol("SXT/USDT:USDT", limit=10)
    assert [row["decision"] for row in history] == ["INVALIDATED", "ENTRY_READY"]


def test_decision_events_are_immutable(tmp_path) -> None:
    db_path = migrate_test_database(tmp_path / "registry.db")
    store = EntryDecisionStore(db_path)
    event_id = store.append_if_changed(
        "SXT/USDT:USDT",
        packet("ENTRY_READY", 84.0, 100),
    )
    assert event_id is not None
    with sqlite3.connect(db_path) as conn:
        try:
            conn.execute(
                "UPDATE entry_decision_events SET decision='NO_TRADE' WHERE id=?",
                (event_id,),
            )
        except sqlite3.DatabaseError:
            pass
        else:
            raise AssertionError("entry decision events must be immutable")


def test_latest_transition_uses_append_order_when_clock_moves_backward(tmp_path) -> None:
    db_path = migrate_test_database(tmp_path / "registry.db")
    store = EntryDecisionStore(db_path)
    store.append_if_changed("SXT/USDT:USDT", packet("ENTRY_READY", 84.0, 200))
    late_id = store.append_if_changed("SXT/USDT:USDT", packet("LATE", 80.0, 100))
    assert late_id is not None

    latest = store.latest_for_symbol("SXT/USDT:USDT")
    assert latest is not None
    assert latest["decision"] == "LATE"

    duplicate = store.append_if_changed("SXT/USDT:USDT", packet("LATE", 79.0, 150))
    assert duplicate is None
    history = store.history_for_symbol("SXT/USDT:USDT", limit=10)
    assert [row["decision"] for row in history] == ["LATE", "ENTRY_READY"]


def test_latest_for_symbol_includes_latest_durable_advisory(tmp_path) -> None:
    db_path = migrate_test_database(tmp_path / "registry.db")
    store = EntryDecisionStore(db_path)
    event_id = store.append_if_changed(
        "SXT/USDT:USDT",
        packet("ENTRY_READY", 84.0, 100),
    )
    assert event_id is not None
    store.append_advisory(
        event_id,
        {
            "observational_only": True,
            "decision_mutated": False,
            "ai_advice": "SHORT",
            "ai_confidence": 81,
            "ai_reasoning": "Evidence agrees.",
            "ai_provider": "gemini",
            "ai_model": "gemini-test",
            "ai_status": "AVAILABLE",
        },
        advisory_at=110,
    )

    latest = EntryDecisionStore(db_path).latest_for_symbol("SXT/USDT:USDT")
    assert latest is not None
    assert latest["event_id"] == event_id
    assert latest["ai_advisory"]["ai_advice"] == "SHORT"


def test_advisory_is_append_only_and_survives_store_restart(tmp_path) -> None:
    db_path = migrate_test_database(tmp_path / "registry.db")
    store = EntryDecisionStore(db_path)
    decision_event_id = store.append_if_changed(
        "SXT/USDT:USDT",
        packet("ENTRY_READY", 84.0, 100),
    )
    assert decision_event_id is not None

    advisory_event_id = store.append_advisory(
        decision_event_id,
        {
            "observational_only": True,
            "decision_mutated": False,
            "ai_advice": "SHORT",
            "ai_confidence": 81,
            "ai_reasoning": "Derivatives and sell flow agree.",
            "ai_provider": "gemini",
            "ai_model": "gemini-test",
            "ai_status": "AVAILABLE",
        },
        advisory_at=110,
    )

    restarted = EntryDecisionStore(db_path)
    history = restarted.history_for_symbol("SXT/USDT:USDT", limit=10)
    assert advisory_event_id > 0
    assert history[0]["decision"] == "ENTRY_READY"
    assert history[0]["ai_advisory"]["ai_advice"] == "SHORT"
    assert history[0]["ai_advisory"]["ai_model"] == "gemini-test"
    assert history[0]["ai_advisory"]["advisory_at"] == 110


def test_guarded_append_rejects_recycled_lifecycle_before_event_or_outbox(tmp_path) -> None:
    db_path = migrate_test_database(tmp_path / "registry.db")
    store = EntryDecisionStore(db_path)
    symbol = "TEST/USDT:USDT"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE lbank_catalog SET lifecycle_id=2, scan_eligible=1, status='WATCH' WHERE symbol=?",
            (symbol,),
        )

    with pytest.raises(RuntimeError, match="candidate lifecycle is no longer current"):
        store.append_if_changed(
            symbol,
            packet("ENTRY_READY", 84.0, 100),
            expected_lifecycle_id=1,
        )

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM entry_decision_events WHERE symbol=?", (symbol,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM entry_notification_outbox"
        ).fetchone()[0] == 0


def test_guarded_append_rejects_scan_ineligible_candidate(tmp_path) -> None:
    db_path = migrate_test_database(tmp_path / "registry.db")
    store = EntryDecisionStore(db_path)
    symbol = "TEST/USDT:USDT"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE lbank_catalog SET scan_eligible=0 WHERE symbol=?",
            (symbol,),
        )

    with pytest.raises(RuntimeError, match="candidate lifecycle is no longer current"):
        store.append_if_changed(
            symbol,
            packet("ENTRY_READY", 84.0, 100),
            expected_lifecycle_id=1,
        )


def test_history_rejects_packet_hash_mismatch(tmp_path) -> None:
    db_path = migrate_test_database(tmp_path / "registry.db")
    store = EntryDecisionStore(db_path)
    event_id = store.append_if_changed(
        "SXT/USDT:USDT", packet("ENTRY_READY", 84.0, 100)
    )
    assert event_id is not None
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TRIGGER entry_decision_events_no_update")
        corrupted = packet("ENTRY_READY", 99.0, 100)
        conn.execute(
            "UPDATE entry_decision_events SET packet_json=? WHERE id=?",
            (json.dumps(corrupted, sort_keys=True, separators=(",", ":")), event_id),
        )

    with pytest.raises(ValueError, match="packet hash mismatch"):
        store.latest_for_symbol("SXT/USDT:USDT")


def test_history_rejects_advisory_hash_mismatch(tmp_path) -> None:
    db_path = migrate_test_database(tmp_path / "registry.db")
    store = EntryDecisionStore(db_path)
    event_id = store.append_if_changed(
        "SXT/USDT:USDT", packet("ENTRY_READY", 84.0, 100)
    )
    assert event_id is not None
    advisory_id = store.append_advisory(
        event_id,
        {
            "observational_only": True,
            "decision_mutated": False,
            "ai_advice": "SHORT",
            "ai_confidence": 81,
            "ai_reasoning": "Evidence agrees.",
            "ai_provider": "gemini",
            "ai_model": "gemini-test",
            "ai_status": "AVAILABLE",
        },
        advisory_at=110,
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TRIGGER entry_decision_advisories_no_update")
        row = conn.execute(
            "SELECT advisory_json FROM entry_decision_advisories WHERE id=?", (advisory_id,)
        ).fetchone()
        corrupted = json.loads(row[0])
        corrupted["ai_confidence"] = 1
        conn.execute(
            "UPDATE entry_decision_advisories SET advisory_json=? WHERE id=?",
            (json.dumps(corrupted, sort_keys=True, separators=(",", ":")), advisory_id),
        )

    with pytest.raises(ValueError, match="advisory hash mismatch"):
        store.latest_for_symbol("SXT/USDT:USDT")


def test_runtime_binds_canonical_append_to_expected_lifecycle(monkeypatch) -> None:
    from waterfallhunter import main

    symbol = "CAS/USDT:USDT"
    expected_lifecycle = 23
    observed: list[int | None] = []
    monkeypatch.setattr(main.scanner, "active_candidates", {symbol: {}})
    monkeypatch.setattr(main.scanner, "get_live_reference", lambda _symbol: (0.01, time.time()))
    monkeypatch.setattr(main.execution_decision_logger, "observe_evaluation", lambda *args, **kwargs: None)

    async def cross_check_symbol(*args, **kwargs):
        return {
            "is_valid": True, "score": 80.0, "suggested_status": "ARMED",
            "metrics": {"exchange": "binance", "mapped_symbol": symbol},
        }

    monkeypatch.setattr(main.validator, "cross_check_symbol", cross_check_symbol)
    monkeypatch.setattr(main, "_apply_deterministic_entry_gate", lambda _s, state, _m: (state, False))
    monkeypatch.setattr(main, "build_signal_leverage_advisory", lambda metrics, execution_suitability=None: {
        "policy_version": "adaptive_signal_leverage_v1",
        "minimum": 4, "maximum": 18, "symbol_agnostic": True,
        "signal_only": True, "advisory_only": True,
        "status": "UNAVAILABLE", "leverage": None, "reason": "test unavailable",
    })
    monkeypatch.setattr(main.entry_decision_store, "latest_for_symbol", lambda _symbol: None)
    monkeypatch.setattr(main, "build_entry_decision", lambda *args, **kwargs: {"decision": "FORMING"})

    def stop_append(*args, **kwargs):
        observed.append(kwargs.get("expected_lifecycle_id"))
        raise RuntimeError("stop-after-canonical-append")

    monkeypatch.setattr(main.entry_decision_store, "append_if_changed", stop_append)
    with pytest.raises(RuntimeError, match="stop-after-canonical-append"):
        asyncio.run(main.evaluate_candidate(symbol, {
            "status": "ARMED", "lifecycle_id": expected_lifecycle, "scan_eligible": True,
            "quote_volume": 3_000_000.0, "last_price": 0.01,
        }))
    assert observed == [expected_lifecycle]


def _actionable_packet(*, leverage: int, now: int = 100, lifecycle_id: int = 1) -> dict:
    value = packet("ENTRY_READY", 90.0, now)
    value["lifecycle_id"] = lifecycle_id
    value["trade_plan"] = {
        "entry_price": 100.0, "stop_loss": 102.0,
        "take_profit_1": 98.0, "take_profit_2": 96.0,
        "take_profit_3": None, "reward_to_risk": 2.0,
        "leverage": leverage,
    }
    value["leverage_advisory"] = {
        "status": "AVAILABLE", "leverage": leverage,
        "policy_version": "adaptive_signal_leverage_v1", "reason": None,
        "execution_suitability_input": {"status": "SUITABLE"},
    }
    return value


def test_same_entry_ready_persists_material_leverage_projection_change_without_duplicate_notification(tmp_path) -> None:
    db_path = migrate_test_database(tmp_path / "registry.db")
    store = EntryDecisionStore(db_path)
    first = store.append_if_changed("SXT/USDT:USDT", _actionable_packet(leverage=6, now=100))
    changed = store.append_if_changed("SXT/USDT:USDT", _actionable_packet(leverage=10, now=110))
    assert first is not None
    assert changed is not None
    latest = store.latest_for_symbol("SXT/USDT:USDT")
    assert latest["trade_plan"]["leverage"] == 10
    assert latest["leverage_advisory"]["leverage"] == 10
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM entry_notification_outbox").fetchone()[0] == 1


def test_same_entry_ready_persists_execution_suitability_provenance_change(tmp_path) -> None:
    db_path = migrate_test_database(tmp_path / "registry.db")
    store = EntryDecisionStore(db_path)
    first_packet = _actionable_packet(leverage=8, now=100)
    second_packet = _actionable_packet(leverage=8, now=110)
    second_packet["leverage_advisory"]["execution_suitability_input"] = {
        "status": "MARGINAL", "maximum_leverage": 10, "observed_samples": 55
    }
    assert store.append_if_changed("SXT/USDT:USDT", first_packet) is not None
    changed = store.append_if_changed("SXT/USDT:USDT", second_packet)
    assert changed is not None
    latest = store.latest_for_symbol("SXT/USDT:USDT")
    assert latest["leverage_advisory"]["execution_suitability_input"]["status"] == "MARGINAL"


def test_same_entry_ready_same_material_projection_remains_deduplicated(tmp_path) -> None:
    db_path = migrate_test_database(tmp_path / "registry.db")
    store = EntryDecisionStore(db_path)
    assert store.append_if_changed("SXT/USDT:USDT", _actionable_packet(leverage=8, now=100)) is not None
    duplicate = _actionable_packet(leverage=8, now=120)
    duplicate["entry_readiness"] = 91.0
    assert store.append_if_changed("SXT/USDT:USDT", duplicate) is None
