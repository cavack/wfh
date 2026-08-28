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


def test_runtime_binds_canonical_append_to_expected_lifecycle() -> None:
    from pathlib import Path
    from waterfallhunter import main

    source = Path(main.__file__).read_text(encoding="utf-8")
    candidate_body = source.split("async def evaluate_candidate(", 1)[1]
    decision_section = candidate_body.split("episode_id =", 1)[0]
    assert "expected_lifecycle_id=" in decision_section
