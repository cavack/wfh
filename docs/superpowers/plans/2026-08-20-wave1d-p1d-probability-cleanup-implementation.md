# Wave 1D P1-D Probability Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the statistically invalid `tp_24h_probability` proxy from runtime eligibility, observational ranking, dashboard payloads, and Telegram messaging while preserving Entry/TP/SL arithmetic, existing non-probability evidence, paper-only safety, and the distinction between ranking score and calibrated probability.

**Architecture:** Keep the historical 5m fetch in `MultiExchangeValidator` because it still supplies recent-high geometry and source capture, but decouple it from `PositionCalculator` probability semantics. Remove the probability component from `FinalRanking`; preserve surviving legacy weights only as transitional implementation details. Preserve the pre-existing mathematical meaning of ranking score as raw weighted points by returning `points` directly instead of renormalizing the surviving 90 maximum to 100. Remove the field at dashboard/Telegram boundaries. `calibrated_probability` remains `None`.

**Tech Stack:** Python 3.13, pytest, FastAPI runtime payload helpers, Next.js-compatible JSON payloads, GitHub Actions, Docker/Compose.

**Spec:** `docs/superpowers/specs/2026-08-20-wave1d-probability-freshness-strict-filtering-design.md`, section 6.

## Global Constraints

- Start only after the Wave 0→1C stack is merged and the exact new `main` is GREEN under separate `MERGE_APPROVAL`.
- Branch P1-D from that fresh `main`; do not stack source implementation on PR #36.
- Do not modify ScoreV2 weights/gates, lifecycle semantics, Entry/TP/SL formulas, leverage, AI advisory behavior, execution suitability, or LBank source policy.
- Do not remove the validator's historical 5m fetch solely because probability no longer consumes it; recent-high calculation and evidence capture still use it.
- Do not create a replacement probability, confidence estimate, ETA, or hidden proxy.
- Do not rescale the surviving ranking maximum from 90 to 100. A complete surviving packet may have ranking score up to 90; this is a transitional observational score, not Final Signal Score calibration.
- `normalized_available_score` may remain as a diagnostic of available components but must not become the authoritative ranking score or a probability label.
- No Production operations or schema migration.

## File Structure Map

### Existing source modified

- `backend/src/waterfallhunter/core/position_calculator.py`
- `backend/src/waterfallhunter/core/multi_exchange_validator.py`
- `backend/src/waterfallhunter/core/final_ranking.py`
- `backend/src/waterfallhunter/core/dashboard.py`
- `backend/src/waterfallhunter/core/notifier.py`

### Tests

- Create `backend/tests/test_probability_cleanup.py`
- Modify `backend/tests/test_final_ranking.py`
- Modify `backend/tests/test_dashboard.py`
- Modify `backend/tests/test_notifier.py`
- Run `backend/tests/test_golden_model_regression.py`

---

### Task 1: RED — prove the invalid probability dependency

**Files:**
- Create: `backend/tests/test_probability_cleanup.py`
- Modify: `backend/tests/test_final_ranking.py`
- Modify: `backend/tests/test_dashboard.py`
- Modify: `backend/tests/test_notifier.py`

- [ ] **Step 1: Add a position setup regression that must succeed without historical probability samples**

Add a test equivalent to:

```python
from waterfallhunter.core.position_calculator import PositionCalculator


def test_position_setup_does_not_require_historical_hit_rate():
    packet = PositionCalculator(slippage_pct=0.05).calculate_short_position(
        100.0,
        recent_high=101.0,
        market_info={
            "precision": {"price": 0.01, "amount": 0.001},
            "contractSize": 1.0,
            "limits": {"cost": {"min": 5.0}},
        },
        mark_price=100.0,
        entry_slippage_pct=0.05,
        exit_slippage_pct=0.05,
    )

    assert packet["status"] == "READY"
    assert "tp_24h_probability" not in packet
```

Run:

```bash
pytest -q backend/tests/test_probability_cleanup.py::test_position_setup_does_not_require_historical_hit_rate
```

Expected RED on current code: either the call signature/logic still demands the old historical path or the output/rejection behavior violates the assertion.

- [ ] **Step 2: Replace the old ranking-confidence expectation with the approved cleanup contract**

Change the old test that asserts missing probability reduces confidence. Add assertions equivalent to:

```python
def test_probability_is_not_a_ranking_component_or_confidence_requirement():
    packet = FinalRanking.for_candidate("TEST", _candidate(probability=0.7))

    assert packet["version"] == "final_ranking_observational_v2_probability_removed"
    assert "empirical_probability" not in packet["components"]
    assert "empirical_probability" not in packet["missing_components"]
    assert packet["confidence"] == 1.0
```

Run:

```bash
pytest -q backend/tests/test_final_ranking.py
```

Expected RED: current version/component/confidence behavior still reflects probability.

- [ ] **Step 3: Make dashboard compaction reject the legacy field**

Update the existing `test_compact_metrics_excludes_heavy_market_payloads` fixture to still supply `tp_24h_probability` as legacy input but assert it does not cross the compact payload boundary:

```python
assert compacted["position_setup"] == {"entry_price": 1.0}
assert "tp_24h_probability" not in compacted["position_setup"]
```

Run:

```bash
pytest -q backend/tests/test_dashboard.py::test_compact_metrics_excludes_heavy_market_payloads
```

Expected RED: current `compact_metrics()` includes the field.

- [ ] **Step 4: Add Telegram semantic guard**

Add:

```python
def test_signal_message_does_not_publish_legacy_tp_probability():
    message = TelegramNotifier.build_signal_message(
        "PEPE/USDT:USDT",
        {
            "score": 88.0,
            "metrics": {
                "position_setup": {
                    "entry_price": 1.0,
                    "stop_loss": 1.02,
                    "take_profit_1": 0.98,
                    "take_profit_2": 0.96,
                    "reward_to_risk": 2.0,
                    "risk_pct": 2.0,
                    "tp_24h_probability": 0.87,
                }
            },
        },
    )

    assert "TP 24h" not in message
    assert "probability" not in message.lower()
```

Run:

```bash
pytest -q backend/tests/test_notifier.py::test_signal_message_does_not_publish_legacy_tp_probability
```

Expected RED: current Telegram message contains `TP 24h`.

- [ ] **Step 5: Commit the RED evidence before implementation**

Commit only failing tests. Record exact failing test names and messages in the PR/evidence ledger. Do not weaken assertions to obtain GREEN.

---

### Task 2: GREEN — decouple PositionCalculator from the hit-rate

**Files:**
- Modify: `backend/src/waterfallhunter/core/position_calculator.py`
- Modify: `backend/src/waterfallhunter/core/multi_exchange_validator.py`
- Test: `backend/tests/test_probability_cleanup.py`

- [ ] **Step 1: Remove `_tp_probability()` from the execution-sensitive calculator**

Delete the helper and remove `historical_candles` / `evaluation_time_ms` from `calculate_short_position()` if the fresh call-site search confirms there are no other legitimate consumers.

Target signature:

```python
def calculate_short_position(
    self,
    vwap_entry: float,
    recent_high: float | None = None,
    market_info: dict | None = None,
    mark_price: float | None = None,
    entry_slippage_pct: float | None = None,
    exit_slippage_pct: float | None = None,
) -> Dict[str, Any]:
```

Do not change the existing Entry/SL/TP/cost/min-notional math in this task.

- [ ] **Step 2: Remove only the obsolete arguments at the validator call site**

Keep:

```python
history = await ex_instance.fetch_ohlcv(...)
```

because the validator still uses it for source capture and `recent_high`.

Change only the call to:

```python
pos_setup = self.position_calculator.calculate_short_position(
    vwap_entry,
    recent_high=recent_high,
    market_info=market_info,
    mark_price=mark_price,
    entry_slippage_pct=microstructure.get("entry_slippage_pct"),
    exit_slippage_pct=microstructure.get("exit_slippage_pct"),
)
```

- [ ] **Step 3: Remove `tp_24h_probability` from the returned position packet**

Do not substitute a differently named field in the production decision packet. Research retention, if ever required, belongs in a separate research-only path.

- [ ] **Step 4: Run focused GREEN**

```bash
pytest -q backend/tests/test_probability_cleanup.py
pytest -q backend/tests/test_multi_exchange_validator.py
```

Expected: PASS; Entry/TP/SL and source-capture tests remain unchanged.

- [ ] **Step 5: Commit minimal calculator/call-site change**

Suggested commit subject:

```text
fix: remove invalid TP hit-rate from position setup
```

---

### Task 3: GREEN — remove probability from FinalRanking without recalibration

**Files:**
- Modify: `backend/src/waterfallhunter/core/final_ranking.py`
- Modify: `backend/tests/test_final_ranking.py`

- [ ] **Step 1: Version and reduce the component set**

Use:

```python
VERSION = "final_ranking_observational_v2_probability_removed"
WEIGHTS = {
    "cascade_readiness": 25.0,
    "signal_score": 20.0,
    "execution_quality": 20.0,
    "relative_weakness": 15.0,
    "freshness": 10.0,
}
```

Do not redistribute the removed 10 points.

- [ ] **Step 2: Delete probability extraction and `empirical_probability` component construction**

No lookup of `metrics.position_setup.tp_24h_probability` remains in `FinalRanking`.

- [ ] **Step 3: Preserve the old ranking-score arithmetic meaning**

Current v1 algebra makes `ranking_score` equal raw available weighted points because:

```text
normalized = points / available_weight * 100
confidence = available_weight / 100
ranking_score = normalized * confidence = points
```

After removal, do not change this into `points / 90 * 100`. Implement:

```python
configured_weight = sum(cls.WEIGHTS.values())  # 90.0, transitional only
available_weight = sum(...)
points = sum(...)
normalized = points / available_weight * 100.0 if available_weight else None
confidence = available_weight / configured_weight if configured_weight else 0.0
ranking_score = points if available_weight else None
```

This means:

- a fully available surviving packet has `confidence == 1.0`;
- ranking score is not cosmetically renormalized to 100;
- no phantom probability absence penalty remains;
- `normalized_available_score` remains diagnostic only.

- [ ] **Step 4: Add exact arithmetic regression**

Add a test that recomputes points from the packet and asserts:

```python
packet = FinalRanking.for_candidate("TEST", _candidate(probability=0.7))
expected_points = sum(
    component["points"]
    for component in packet["components"].values()
    if component["available"]
)
assert packet["score"] == round(expected_points, 6)
assert packet["confidence"] == 1.0
assert packet["score"] <= 90.0
```

Run:

```bash
pytest -q backend/tests/test_final_ranking.py
```

Expected: PASS.

- [ ] **Step 5: Commit ranking cleanup separately**

Suggested subject:

```text
fix: remove probability from observational ranking
```

---

### Task 4: GREEN — remove user-facing probability semantics

**Files:**
- Modify: `backend/src/waterfallhunter/core/dashboard.py`
- Modify: `backend/src/waterfallhunter/core/notifier.py`
- Modify: `backend/tests/test_dashboard.py`
- Modify: `backend/tests/test_notifier.py`

- [ ] **Step 1: Delete `tp_24h_probability` from `position_fields` in `compact_metrics()`**

Legacy input may exist in historical payloads, but new compact dashboard payloads must not forward it.

- [ ] **Step 2: Remove the `TP 24h` fragment from Telegram formatting**

Keep reward:risk, Entry, Stop, TP1/TP2, spread/slippage and existing paper-only disclaimer. Do not redesign Telegram delivery in this wave.

Target line semantics:

```python
f"📐 Reward:risk: <b>{cls._number(pos_setup.get('reward_to_risk'), 2)}</b>"
```

- [ ] **Step 3: Run focused tests**

```bash
pytest -q backend/tests/test_dashboard.py backend/tests/test_notifier.py
```

Expected: PASS.

- [ ] **Step 4: Commit boundary cleanup**

Suggested subject:

```text
fix: remove legacy TP probability from user surfaces
```

---

### Task 5: Add a bounded regression guard against reintroduction

**Files:**
- Modify: `backend/tests/test_probability_cleanup.py`

- [ ] **Step 1: Add an active-source guard**

Use a bounded path list rather than scanning historical docs/research fixtures:

```python
from pathlib import Path


def test_active_runtime_sources_do_not_reference_legacy_tp_probability():
    root = Path(__file__).resolve().parents[2]
    paths = [
        root / "backend/src/waterfallhunter/core/position_calculator.py",
        root / "backend/src/waterfallhunter/core/final_ranking.py",
        root / "backend/src/waterfallhunter/core/dashboard.py",
        root / "backend/src/waterfallhunter/core/notifier.py",
    ]
    for path in paths:
        assert "tp_24h_probability" not in path.read_text(encoding="utf-8")
```

If a future research-only module legitimately preserves the old historical field, it is not included in this active-runtime guard.

- [ ] **Step 2: Run all P1-D focused tests**

```bash
pytest -q \
  backend/tests/test_probability_cleanup.py \
  backend/tests/test_final_ranking.py \
  backend/tests/test_dashboard.py \
  backend/tests/test_notifier.py \
  backend/tests/test_multi_exchange_validator.py
```

Expected: PASS.

---

### Task 6: Differential regression and independent review

- [ ] **Step 1: Run full backend and Golden regression**

```bash
pytest -q backend/tests
pytest -q backend/tests/test_golden_model_regression.py
PYTHONPATH=backend/src:. python scripts/verify_runtime_parity.py
```

Allowed behavioral differences are only:

```text
position setup no longer rejected solely for missing historical hit-rate
position packet no longer emits tp_24h_probability
FinalRanking v2 has no empirical_probability component/penalty
ranking points/order may change only by removal of probability points
Dashboard/Telegram no longer expose TP 24h probability
```

Block on unexpected changes to ScoreV2, lifecycle, signal class/profile, Entry/TP/SL, leverage, LBank identity, execution suitability/cost math, or unrelated reason codes.

- [ ] **Step 2: Run frontend validation even if no frontend source changed**

```bash
cd frontend
npm ci
npm run typecheck
npm run build
```

Expected: PASS.

- [ ] **Step 3: Require exact-head CI and independent review**

Required:

```text
backend PASS
frontend PASS
dependency-audit PASS
container-validation PASS
repository-hygiene PASS
CodeRabbit no actionable unresolved finding
Sonar Quality Gate PASS
controller semantic diff review PASS
```

- [ ] **Step 4: Certify P1-D only**

Record exact head SHA and declare:

```text
P1-D = GREEN_REVIEWED
```

Do not start P1-E before this state is supported by fresh evidence.