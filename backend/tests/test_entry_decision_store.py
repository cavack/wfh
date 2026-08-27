import sqlite3

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
