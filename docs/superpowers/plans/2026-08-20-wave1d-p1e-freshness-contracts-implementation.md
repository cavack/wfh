# Wave 1D P1-E Freshness Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make analysis freshness and LBank reference-price freshness independent, explicit, reproducible, and fail-closed without inventing a new global age threshold or turning freshness into predictive evidence.

**Architecture:** Introduce a small pure freshness domain helper that validates timestamps/ages and represents each axis as `LIVE | STALE | UNAVAILABLE`. Status is supplied from already-authoritative source freshness verdicts, not inferred from a new Wave 1D threshold. Preserve the scanner's existing 90-second LBank reference TTL as the reference-source policy while exposing stale snapshots rather than collapsing them to `(None, None)`. Capture and retain `analysis_observed_at` independently in live metrics. Align `EvidenceQualityPacket` to Final Design contract version 1.1, enforce timestamp/age pair integrity, expose both freshness axes in dashboard payloads, and provide deterministic decision qualifiers for later typed decision assembly. Analysis freshness can block a new strict confirmation; reference freshness controls authoritative execution levels and execution eligibility but must not erase an otherwise valid deterministic confirmation.

**Tech Stack:** Python 3.13, Pydantic v2, FastAPI payload formatting, pytest, existing LBank scanner reference TTL policy, GitHub Actions, Docker/Compose.

**Spec:** `docs/superpowers/specs/2026-08-20-wave1d-probability-freshness-strict-filtering-design.md`, section 7.

## Global Constraints

- Start only after P1-D is `GREEN_REVIEWED`.
- Base P1-E on the exact reviewed P1-D head.
- Do not create a new numeric analysis freshness threshold.
- `LBankCatalogScanner.reference_ttl_seconds = 90.0` is an existing source policy and may be preserved; do not silently change it.
- Freshness is evidence quality / eligibility semantics, not directional predictive evidence.
- Do not modify FinalRanking weights or use `EvidenceQualityPacket` as a new ranking component.
- Initial signal identity/class/profile/metadata timestamps remain immutable.
- A later stale reference does not rewrite historical signal metadata or change a deterministic confirmed signal into rejected.
- Missing/stale reference makes execution levels non-authoritative and blocks execution eligibility at that observation boundary; the decision can remain `CONFIRMED` with `EXECUTION_LEVELS_UNAVAILABLE`/`STALE_REFERENCE` qualifiers as applicable.
- Missing/stale analysis cannot create a new strict confirmation; `STALE_ANALYSIS` is reserved for actual stale analysis, while unavailable analysis uses `INSUFFICIENT_EVIDENCE`.
- No schema migration; Wave 1C `signal_metadata` already persists analysis/reference observation timestamps.
- No Production operations.

## File Structure Map

### New focused module

- Create `backend/src/waterfallhunter/core/freshness.py`

### Existing source modified

- `backend/src/waterfallhunter/core/contracts.py`
- `backend/src/waterfallhunter/discovery/lbank_scanner.py`
- `backend/src/waterfallhunter/main.py`
- `backend/src/waterfallhunter/core/dashboard.py`

### Tests

- Create `backend/tests/test_freshness_contracts.py`
- Modify `backend/tests/test_canonical_contracts.py`
- Modify `backend/tests/test_lbank_scanner.py`
- Modify `backend/tests/test_dashboard.py`
- Modify `backend/tests/test_stale_trigger_safety.py`
- Run `backend/tests/test_golden_model_regression.py`

---

### Task 1: RED — define independent freshness axes and timestamp invariants

**Files:**
- Create: `backend/tests/test_freshness_contracts.py`

- [ ] **Step 1: Add the four-state matrix before implementation**

Tests must express statuses independently:

```python
import pytest

from waterfallhunter.core.contracts import DecisionQualifier
from waterfallhunter.core.freshness import (
    FreshnessStatus,
    assess_freshness_pair,
)


@pytest.mark.parametrize(
    ("analysis", "reference", "confirmation_eligible", "levels_authoritative", "qualifiers"),
    [
        (FreshnessStatus.LIVE, FreshnessStatus.LIVE, True, True, ()),
        (
            FreshnessStatus.STALE,
            FreshnessStatus.LIVE,
            False,
            True,
            (DecisionQualifier.STALE_ANALYSIS,),
        ),
        (
            FreshnessStatus.LIVE,
            FreshnessStatus.STALE,
            True,
            False,
            (
                DecisionQualifier.EXECUTION_LEVELS_UNAVAILABLE,
                DecisionQualifier.STALE_REFERENCE,
            ),
        ),
        (
            FreshnessStatus.STALE,
            FreshnessStatus.STALE,
            False,
            False,
            (
                DecisionQualifier.EXECUTION_LEVELS_UNAVAILABLE,
                DecisionQualifier.STALE_ANALYSIS,
                DecisionQualifier.STALE_REFERENCE,
            ),
        ),
    ],
)
def test_freshness_axes_are_independent(
    analysis,
    reference,
    confirmation_eligible,
    levels_authoritative,
    qualifiers,
):
    result = assess_freshness_pair(
        analysis_status=analysis,
        reference_status=reference,
    )
    assert result.strict_confirmation_eligible is confirmation_eligible
    assert result.execution_levels_authoritative is levels_authoritative
    assert result.strict_execution_eligible is (
        confirmation_eligible and levels_authoritative
    )
    assert result.qualifiers == qualifiers
```

Add explicit `UNAVAILABLE` cases:

```text
analysis UNAVAILABLE + reference LIVE
  -> strict_confirmation_eligible=false
  -> INSUFFICIENT_EVIDENCE

analysis LIVE + reference UNAVAILABLE
  -> strict_confirmation_eligible=true
  -> execution_levels_authoritative=false
  -> strict_execution_eligible=false
  -> EXECUTION_LEVELS_UNAVAILABLE

both UNAVAILABLE
  -> confirmation false, levels false
  -> EXECUTION_LEVELS_UNAVAILABLE + INSUFFICIENT_EVIDENCE
```

Run:

```bash
pytest -q backend/tests/test_freshness_contracts.py
```

Expected RED: module/types do not exist.

- [ ] **Step 2: Add age derivation and invalid timestamp tests**

Required case:

```python
assert freshness_axis(
    status="LIVE",
    observed_at=100,
    evaluated_at=125,
).age_seconds == 25.0
```

Reject:

```text
negative observed_at
negative evaluated_at
observed_at > evaluated_at
bool timestamps
NaN/inf timestamps
status LIVE/STALE with missing observed_at
status UNAVAILABLE with a fabricated observed_at/age
```

Expected RED until the pure validator exists.

- [ ] **Step 3: Commit RED tests**

Record exact failures; no source change in this commit.

---

### Task 2: GREEN — implement the pure freshness domain helper

**Files:**
- Create: `backend/src/waterfallhunter/core/freshness.py`
- Test: `backend/tests/test_freshness_contracts.py`

- [ ] **Step 1: Implement explicit statuses**

Use a frozen, finite contract equivalent to:

```python
from enum import Enum
from pydantic import BaseModel, ConfigDict

from waterfallhunter.core.contracts import DecisionQualifier


class FreshnessStatus(str, Enum):
    LIVE = "LIVE"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class FreshnessAxis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: FreshnessStatus
    observed_at: float | None
    evaluated_at: float
    age_seconds: float | None
    reason: str | None = None
```

Use strict validation that rejects bool/non-finite/negative values and requires age to equal `evaluated_at - observed_at` within deterministic floating-point tolerance.

- [ ] **Step 2: Implement a constructor that never invents status from age**

Target API:

```python
def freshness_axis(
    *,
    status: FreshnessStatus | str,
    observed_at: int | float | None,
    evaluated_at: int | float,
    reason: str | None = None,
) -> FreshnessAxis:
    ...
```

Rules:

```text
LIVE/STALE require observed_at
UNAVAILABLE requires observed_at=None and age_seconds=None
no threshold parameter
no default threshold
no inference "age > N => STALE"
```

- [ ] **Step 3: Implement deterministic pair consequences**

Use a frozen result containing at least:

```python
class FreshnessAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_status: FreshnessStatus
    reference_status: FreshnessStatus
    strict_confirmation_eligible: bool
    execution_levels_authoritative: bool
    strict_execution_eligible: bool
    qualifiers: tuple[DecisionQualifier, ...]
```

Qualifier/consequence rules:

```text
analysis STALE
  -> STALE_ANALYSIS
  -> strict_confirmation_eligible=false

analysis UNAVAILABLE
  -> INSUFFICIENT_EVIDENCE
  -> strict_confirmation_eligible=false

reference STALE
  -> STALE_REFERENCE + EXECUTION_LEVELS_UNAVAILABLE
  -> execution_levels_authoritative=false
  -> strict_execution_eligible=false
  -> does not by itself erase deterministic confirmation

reference UNAVAILABLE
  -> EXECUTION_LEVELS_UNAVAILABLE
  -> execution_levels_authoritative=false
  -> strict_execution_eligible=false
  -> does not by itself erase deterministic confirmation

LIVE/LIVE
  -> no freshness qualifier
```

Canonicalize qualifier ordering using enum value sorting, consistent with `DecisionStatus`.

- [ ] **Step 4: Run GREEN**

```bash
pytest -q backend/tests/test_freshness_contracts.py
```

Expected: PASS.

---

### Task 3: Align `EvidenceQualityPacket` to v1.1 without adding a parallel contract

**Files:**
- Modify: `backend/src/waterfallhunter/core/contracts.py`
- Modify: `backend/tests/test_canonical_contracts.py`

- [ ] **Step 1: RED the approved version and timestamp-pair rules**

Update `_valid_evidence_packet()` to use:

```python
_envelope("evidence_quality", "1.1")
```

Add tests for reference timestamp/age pair integrity.

Invalid combinations:

```text
reference_observed_at set + reference_age_seconds None
reference_observed_at None + reference_age_seconds set
```

Age-at-evaluation consistency is tested through the canonical freshness builder because `EvidenceQualityPacket` does not carry a separate dedicated `evaluated_at` field beyond envelope generation semantics.

- [ ] **Step 2: Bump only the EvidenceQuality contract version**

Change:

```python
contract_version: Literal["1.1"]
```

Do not add unapproved predictive fields. Keep the Final Design field set:

```text
coverage/completeness
analysis observed_at + age
reference observed_at + age
timestamp alignment
coverage dimensions
missing/stale sources
uncertainty reasons
```

- [ ] **Step 3: Add a model validator for reference pair integrity**

Equivalent behavior:

```python
if (self.reference_observed_at is None) != (self.reference_age_seconds is None):
    raise ValueError("reference observation timestamp and age must be present together")
```

- [ ] **Step 4: Run focused contract tests**

```bash
pytest -q backend/tests/test_canonical_contracts.py backend/tests/test_freshness_contracts.py
```

Expected: PASS.

---

### Task 4: Preserve the existing LBank reference TTL while exposing STALE explicitly

**Files:**
- Modify: `backend/src/waterfallhunter/discovery/lbank_scanner.py`
- Modify: `backend/tests/test_lbank_scanner.py`

- [ ] **Step 1: RED a structured reference snapshot**

Add tests for the existing `reference_ttl_seconds=90.0` policy.

Required behavior:

```text
valid price + age <= existing TTL -> LIVE
valid price + age > existing TTL -> STALE with original observed_at retained
missing/invalid price or missing timestamp -> UNAVAILABLE
```

- [ ] **Step 2: Add `get_reference_snapshot()` without breaking `get_live_reference()`**

Target returned shape:

```python
{
    "status": "LIVE" | "STALE" | "UNAVAILABLE",
    "price": float | None,
    "observed_at": float | None,
    "age_seconds": float | None,
    "source": "lbank",
    "policy": "lbank_reference_ttl_v1",
    "ttl_seconds": self.reference_ttl_seconds,
}
```

`get_live_reference()` remains a compatibility wrapper that returns `(price, observed_at)` only for `LIVE` and `(None, None)` otherwise.

This is not a new threshold: it exposes the scanner's existing 90-second rule instead of hiding its stale state.

- [ ] **Step 3: Run scanner tests**

```bash
pytest -q backend/tests/test_lbank_scanner.py
```

Expected: PASS.

---

### Task 5: Capture analysis observation independently and stop reference freshness from erasing analysis state

**Files:**
- Modify: `backend/src/waterfallhunter/main.py`
- Modify: `backend/src/waterfallhunter/core/dashboard.py`
- Modify: `backend/tests/test_dashboard.py`
- Modify: `backend/tests/test_stale_trigger_safety.py`

- [ ] **Step 1: RED the dashboard split**

Add a test where analysis exists but the LBank reference snapshot is STALE. Required output:

```python
assert candidate["analysis_observed_at"] == 1_700_000_000
assert candidate["analysis_age_seconds"] is not None
assert candidate["analysis_status"] == "LIVE"
assert candidate["reference_observed_at"] == 1_699_999_800
assert candidate["reference_age_seconds"] is not None
assert candidate["reference_status"] == "STALE"
assert candidate["last_price"] is None  # stale reference cannot be authoritative
assert candidate["metrics"] is not None  # analysis is not erased by reference status
```

Also test the inverse: fresh reference + unavailable analysis never becomes analysis LIVE.

Current code should RED because reference `is_live` controls whether metrics survive.

- [ ] **Step 2: Store `analysis_observed_at` in the compact live-analysis packet**

`evaluate_candidate()` already captures:

```python
analysis_observed_at = int(time.time())
```

Carry that exact boundary into the metrics handed to `_store_live_metrics()`:

```python
metrics = {
    **metrics,
    "analysis_observed_at": analysis_observed_at,
}
```

Do not replace it with persistence time or current dashboard render time.

- [ ] **Step 3: Add approved compact fields**

Allow `compact_metrics()` to carry `analysis_observed_at` and the explicit source freshness status/reason produced for the current analysis. Do not expose raw provider payloads.

- [ ] **Step 4: Make `get_formatted_candidates()` evaluate axes independently**

Use `scanner.get_reference_snapshot(symbol)` for reference status/age.

For analysis:

```text
completed current validator result with accepted source freshness -> LIVE
no completed analysis/pending/failed non-stale analysis -> UNAVAILABLE
explicit stale-source verdict from the validator/source packet -> STALE
```

Do not infer STALE from a newly invented age threshold. Always expose `analysis_age_seconds` when a LIVE or STALE analysis timestamp exists; `UNAVAILABLE` has no fabricated observation timestamp.

Do not condition `metrics` existence on reference being LIVE.

- [ ] **Step 5: Apply freshness consequences without collapsing decision axes**

At the current decision boundary:

```text
analysis LIVE is required to create a new strict deterministic confirmation
analysis STALE/UNAVAILABLE prevents a new strict confirmation
reference LIVE is required for authoritative execution levels and strict execution eligibility
reference STALE/UNAVAILABLE adds execution-level qualifiers but does not by itself delete an otherwise valid deterministic confirmation
```

This preserves the Final Design distinction:

```text
signal_class = STRICT
lifecycle_state = TRIGGERED
decision_status.primary = CONFIRMED
decision_status.qualifiers may include EXECUTION_LEVELS_UNAVAILABLE / STALE_REFERENCE
```

Experimental research behavior remains non-trade-eligible and must not be silently promoted.

- [ ] **Step 6: Run focused tests**

```bash
pytest -q \
  backend/tests/test_freshness_contracts.py \
  backend/tests/test_dashboard.py \
  backend/tests/test_stale_trigger_safety.py \
  backend/tests/test_lbank_scanner.py \
  backend/tests/test_canonical_contracts.py
```

Expected: PASS.

---

### Task 6: Protect ranking and metadata from freshness side effects

**Files:**
- Modify tests only unless a regression is found.
- Test: `backend/tests/test_final_ranking.py`
- Test: `backend/tests/test_signal_metadata_persistence.py`

- [ ] **Step 1: Assert P1-E does not recalibrate FinalRanking**

Use fixed candidate fixtures from the P1-D head and assert the same ranking packet values before/after freshness-contract plumbing when the legacy ranking inputs are unchanged.

P1-E must not replace the transitional ranking `freshness` weight with `EvidenceQualityPacket` or analysis freshness.

- [ ] **Step 2: Assert later freshness does not mutate immutable metadata**

Persist a signal with known `analysis_observed_at` / `reference_observed_at`, then evaluate a later stale freshness snapshot and assert the `signal_metadata` row remains byte-for-byte unchanged.

- [ ] **Step 3: Run**

```bash
pytest -q backend/tests/test_final_ranking.py backend/tests/test_signal_metadata_persistence.py
```

Expected: PASS.

---

### Task 7: Full regression and independent review

- [ ] **Step 1: Full backend + Golden + runtime parity**

```bash
pytest -q backend/tests
pytest -q backend/tests/test_golden_model_regression.py
PYTHONPATH=backend/src:. python scripts/verify_runtime_parity.py
```

Allowed P1-E differences:

```text
new explicit analysis/reference freshness fields/statuses
reference stale state retained as stale metadata instead of collapsed to absent
analysis metrics no longer erased solely because reference is unavailable/stale
freshness qualifiers/reasons separate confirmation from execution-level authority
EvidenceQualityPacket version 1.1
```

Block unexpected ScoreV2, ranking weighting, signal class/profile, lifecycle, Entry/TP/SL, leverage, or execution-cost changes.

- [ ] **Step 2: Frontend build compatibility**

```bash
cd frontend
npm ci
npm run typecheck
npm run build
```

No broad frontend redesign in this slice; P2 Typed API remains later.

- [ ] **Step 3: Exact-head review gates**

Require GitHub required checks, container-validation, CodeRabbit, Sonar, controller review and security/contract review all GREEN.

- [ ] **Step 4: Certify P1-E**

Record exact head SHA and declare:

```text
P1-E = GREEN_REVIEWED
```

Only then may P1-F start.