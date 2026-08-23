from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from schema_test_support import migrate_test_database
from waterfallhunter.core.lifecycle_v2_shadow import (
    LifecycleV2Evidence,
    LifecycleV2State,
    compare_v1_v2_shadow,
    evaluate_lifecycle_v2_shadow,
)
from waterfallhunter.core.lifecycle_v2_shadow_store import (
    LifecycleV2ShadowStore,
    LifecycleV2ShadowStoreError,
)
from waterfallhunter.core.schema_contract import (
    CURRENT_RUNTIME_SCHEMA_VERSION,
    verify_managed_schema,
)


def _evidence() -> LifecycleV2Evidence:
    return LifecycleV2Evidence(
        eligible_data=True,
        fuel_rich=True,
        structure_count=2,
        flow_family_pass=True,
        relative_family_pass=False,
        anti_chase_pass=True,
        strict_setup_ready=True,
        lower_tf_trigger_closed=False,
        distance_to_trigger_atr=0.4,
        lbank_constraints_fresh=True,
        orderbook_fresh=True,
        levels_constructible=True,
        estimated_round_trip_cost_r=0.1,
        executable_depth_multiple=12,
        preliminary_portfolio_capacity=True,
        confirmation_count=2,
        confirmation_family_count=2,
        extension_atr=0.2,
        oldest_required_observed_at=990,
        decision_at=1_000,
        evidence_refs=("candle:3m:1000",),
    )


def test_migration_v5_is_verified_and_shadow_events_are_append_only(tmp_path: Path) -> None:
    db_path = migrate_test_database(tmp_path / "shadow.db")
    assert CURRENT_RUNTIME_SCHEMA_VERSION == 5
    assert verify_managed_schema(db_path, check_user_version=5).valid is True
    store = LifecycleV2ShadowStore(db_path)
    transition = evaluate_lifecycle_v2_shadow(
        episode_id="episode-1",
        current_state=LifecycleV2State.WATCH,
        evidence=_evidence(),
    )
    comparison = compare_v1_v2_shadow(
        episode_id="episode-1",
        v1_state="WATCH",
        v2_state=LifecycleV2State.WATCH,
        evidence=_evidence(),
    )

    assert store.append_comparison(
        symbol="TEST/USDT:USDT",
        v1_state="WATCH",
        transition=transition,
        comparison=comparison,
        created_at=1_001,
    ) is True
    assert store.append_comparison(
        symbol="TEST/USDT:USDT",
        v1_state="WATCH",
        transition=transition,
        comparison=comparison,
        created_at=1_001,
    ) is False
    assert store.latest_state(
        symbol="TEST/USDT:USDT",
        episode_id="episode-1",
    ) is LifecycleV2State.FUEL_RICH
    assert store.latest_state(
        symbol="OTHER/USDT:USDT",
        episode_id="episode-1",
    ) is LifecycleV2State.WATCH

    report = store.report()
    assert report["event_count"] == 1
    assert report["divergence_count"] == 1
    assert report["promotion_allowed"] is False
    assert report["analysis"]["profile_counts"] == {
        "STRICT_RETEST_BREAKDOWN_SHORT_V1": 1,
    }
    assert report["analysis"]["outcome_association"]["available"] is False
    assert report["analysis"]["promotion_decision"] == "DO_NOT_PROMOTE"
    with sqlite3.connect(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE lifecycle_v2_shadow_events SET v2_to_state='TRIGGERED'"
            )


def test_same_transition_hash_with_different_v1_material_is_a_conflict(tmp_path: Path) -> None:
    db_path = migrate_test_database(tmp_path / "conflict.db")
    store = LifecycleV2ShadowStore(db_path)
    transition = evaluate_lifecycle_v2_shadow(
        episode_id="episode-1",
        current_state=LifecycleV2State.WATCH,
        evidence=_evidence(),
    )
    comparison = compare_v1_v2_shadow(
        episode_id="episode-1",
        v1_state="WATCH",
        v2_state=LifecycleV2State.WATCH,
        evidence=_evidence(),
    )
    store.append_comparison(
        symbol="TEST/USDT:USDT",
        v1_state="WATCH",
        transition=transition,
        comparison=comparison,
        created_at=1_001,
    )

    with pytest.raises(LifecycleV2ShadowStoreError, match="IDEMPOTENCY_CONFLICT"):
        store.append_comparison(
            symbol="TEST/USDT:USDT",
            v1_state="ARMED",
            transition=transition,
            comparison=comparison,
            created_at=1_001,
        )
