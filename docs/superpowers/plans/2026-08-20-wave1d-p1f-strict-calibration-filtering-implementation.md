# Wave 1D P1-F Strict Calibration Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every production-facing outcome/calibration input STRICT-only by default, attach deterministic cohort/lineage/provenance manifests, and prevent EXPERIMENTAL, MIXED, missing-lineage, or legacy research data from becoming promotion evidence by implication.

**Architecture:** Build a frozen `CalibrationDatasetManifest` from authoritative `canonical_signal_view` lineage plus exact dataset/window/outcome semantics. Canonicalize scopes and exclusion counts and derive `dataset_identity_hash` with the existing RFC8785/JCS SHA-256 helper over semantic identity only, excluding volatile generation time. Extend `LBankExecutionOutcomeReport` to include exact lineage scopes and a manifest. Keep non-STRICT report modes explicit research-only. Wrap existing historical `calibrate_score_v2.py` so missing/non-STRICT manifests remain usable for research but can never be reported as promotion-allowed. Wave 1D does not train or promote a probability model.

**Tech Stack:** Python 3.13, Pydantic v2, SQLite/WAL, `canonical_signal_view`, RFC8785/JCS SHA-256, pytest, historical calibration scripts, GitHub Actions, Docker/Compose.

**Spec:** `docs/superpowers/specs/2026-08-20-wave1d-probability-freshness-strict-filtering-design.md`, section 8.

## Global Constraints

- Start only after P1-E is `GREEN_REVIEWED`.
- Base P1-F on the exact reviewed P1-E head.
- `canonical_signal_view` is the only authoritative interface for signal identity/semantics. Never infer missing lineage from `trigger_metrics_json`, current config, defaults, filenames, or historical assumptions.
- Production default signal class scope is exactly `("STRICT",)` / `["STRICT"]`.
- EXPERIMENTAL and MIXED are explicit research modes and always `research_only=true`, `promotion_allowed=false` in Wave 1D.
- A STRICT manifest is necessary but not sufficient for promotion. Wave 1D still keeps `promotion_allowed=false` because true promotion requires later strict OOS scientific validation, strategy-equivalence evidence, sample-size/uncertainty gates, calibration curves/Brier score and explicit promotion review.
- Missing manifest on existing historical tooling may remain research-compatible, but must fail closed for promotion.
- Missing/blank signal class/profile/score version/model generation/decision contract identity must never default to STRICT.
- Do not create a DB migration; Wave 1C schema v3 already exposes required lineage in `canonical_signal_view`.
- Do not change ScoreV2 weights/thresholds in this workstream.
- No Production operations.

## File Structure Map

### New focused module

- Create `backend/src/waterfallhunter/core/calibration_dataset.py`

### Existing source modified

- `backend/src/waterfallhunter/core/lbank_execution_outcome_report.py`
- `scripts/calibrate_score_v2.py`

### Tests

- Create `backend/tests/test_calibration_dataset_manifest.py`
- Modify `backend/tests/test_lbank_execution_outcome_report.py`
- Modify `backend/tests/test_score_v2_calibration.py`
- Modify `backend/tests/test_canonical_signal_consumers.py`
- Run `backend/tests/test_golden_model_regression.py`

---

### Task 1: RED — define deterministic manifest semantics

**Files:**
- Create: `backend/tests/test_calibration_dataset_manifest.py`

- [ ] **Step 1: Add a canonical strict manifest fixture**

Use a fixture equivalent to:

```python
from waterfallhunter.core.calibration_dataset import build_calibration_dataset_manifest


def _strict_manifest(*, generated_at=200):
    return build_calibration_dataset_manifest(
        generated_at=generated_at,
        signal_class_scope=["STRICT"],
        strategy_profile_scope=["strict_score_v2"],
        score_version_scope=["score_v2"],
        model_generation_scope=["waterfall_signal_model_v1"],
        decision_contract_hash_scope=["a" * 64],
        observation_window_start=100,
        observation_window_end=199,
        included_sample_ids=[1, 2, 3],
        excluded_reason_counts={"SIGNAL_CLASS_OUT_OF_SCOPE": 4},
        outcome_horizon_seconds=86_400,
        outcome_price_source="closed_1m_trade_ohlcv_proxy",
        research_only=False,
        promotion_allowed=False,
    )
```

- [ ] **Step 2: Prove identity is independent of volatile generation time**

```python
def test_dataset_identity_hash_excludes_generated_at():
    first = _strict_manifest(generated_at=200)
    second = _strict_manifest(generated_at=999)

    assert first.generated_at != second.generated_at
    assert first.dataset_identity_hash == second.dataset_identity_hash
```

- [ ] **Step 3: Prove semantic changes alter identity**

Change one at a time and assert a different hash:

```text
signal class scope
strategy profile scope
score version scope
model generation scope
decision contract hash scope
observation window
sample identity set
exclusion reason counts
outcome horizon
outcome price source
research/promotion flags
```

- [ ] **Step 4: Prove canonical ordering**

Input scopes and exclusion mappings in different orders; output scopes must be sorted/deduplicated and hash identical.

- [ ] **Step 5: Prove fail-closed lineage**

Reject empty/blank lineage members and invalid SHA-256 decision hashes. Reject `promotion_allowed=True` for research-only or non-STRICT scope in this Wave 1D contract.

Run:

```bash
pytest -q backend/tests/test_calibration_dataset_manifest.py
```

Expected RED: module does not exist.

- [ ] **Step 6: Commit RED tests**

No implementation in the RED commit.

---

### Task 2: GREEN — implement `CalibrationDatasetManifest`

**Files:**
- Create: `backend/src/waterfallhunter/core/calibration_dataset.py`
- Test: `backend/tests/test_calibration_dataset_manifest.py`

- [ ] **Step 1: Implement a frozen versioned contract**

Use a contract equivalent to:

```python
class CalibrationDatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["calibration_dataset_manifest_v1"]
    generated_at: int
    signal_class_scope: tuple[str, ...]
    strategy_profile_scope: tuple[str, ...]
    score_version_scope: tuple[str, ...]
    model_generation_scope: tuple[str, ...]
    decision_contract_hash_scope: tuple[str, ...]
    observation_window_start: int
    observation_window_end: int
    included_sample_count: int
    excluded_sample_count: int
    exclusion_reason_counts: Mapping[str, int]
    outcome_horizon_seconds: int
    outcome_price_source: str
    sample_set_sha256: str
    research_only: bool
    promotion_allowed: bool
    dataset_identity_hash: str
```

`sample_set_sha256` is the canonical hash of the sorted included immutable sample identities. Do not put an unbounded raw sample-ID list in the manifest output.

- [ ] **Step 2: Reuse the existing canonical hash implementation**

Import:

```python
from waterfallhunter.core.signal_metadata import canonical_sha256
```

Do not introduce `json.dumps(sort_keys=True)` as a competing provenance hash.

- [ ] **Step 3: Define exact identity payload**

Build `dataset_identity_hash` over:

```python
{
    "contract_version": "calibration_dataset_manifest_v1",
    "signal_class_scope": canonical_signal_class_scope,
    "strategy_profile_scope": canonical_strategy_profile_scope,
    "score_version_scope": canonical_score_version_scope,
    "model_generation_scope": canonical_model_generation_scope,
    "decision_contract_hash_scope": canonical_decision_contract_hash_scope,
    "observation_window_start": observation_window_start,
    "observation_window_end": observation_window_end,
    "included_sample_count": included_sample_count,
    "excluded_sample_count": excluded_sample_count,
    "exclusion_reason_counts": canonical_exclusion_reason_counts,
    "outcome_horizon_seconds": outcome_horizon_seconds,
    "outcome_price_source": outcome_price_source,
    "sample_set_sha256": sample_set_sha256,
    "research_only": research_only,
    "promotion_allowed": promotion_allowed,
}
```

Explicitly exclude `generated_at` and `dataset_identity_hash` itself.

- [ ] **Step 4: Enforce Wave 1D promotion policy**

At this stage:

```python
if promotion_allowed:
    raise ValueError("Wave 1D manifests are not promotion-authoritative")
```

This avoids creating a future-looking loophole. Wave 5 can version the contract when scientific promotion is actually implemented.

- [ ] **Step 5: Run GREEN**

```bash
pytest -q backend/tests/test_calibration_dataset_manifest.py
```

Expected: PASS.

---

### Task 3: RED/GREEN — enrich `LBankExecutionOutcomeReport` with authoritative lineage manifest

**Files:**
- Modify: `backend/src/waterfallhunter/core/lbank_execution_outcome_report.py`
- Modify: `backend/tests/test_lbank_execution_outcome_report.py`

- [ ] **Step 1: RED exact strict default**

Add assertions to the default report:

```python
assert report["signal_class_scope"] == ["STRICT"]
assert report["research_only"] is False
assert report["dataset_manifest"]["signal_class_scope"] == ["STRICT"]
assert report["dataset_manifest"]["promotion_allowed"] is False
```

- [ ] **Step 2: RED explicit research modes**

Seed STRICT and EXPERIMENTAL canonical rows. Assert:

```text
default report includes only STRICT
EXPERIMENTAL report requires explicit cohort and reports research_only=true
MIXED_RESEARCH reports research_only=true
all Wave 1D manifests promotion_allowed=false
```

- [ ] **Step 3: Select the existing lineage columns from `canonical_signal_view`**

Extend `_rows()` SELECT with:

```sql
s.score_version,
s.model_generation,
s.decision_contract_hash,
s.analysis_observed_at,
s.reference_observed_at
```

Keep `signal_class` and `strategy_profile` already selected. Do not read lineage from JSON.

- [ ] **Step 4: Build deterministic scope sets from included rows**

Before aggregation, validate every included row has non-empty:

```text
signal_class
strategy_profile
score_version
model_generation
64-char lowercase hex decision_contract_hash
```

A malformed canonical row is excluded from calibration/report dataset construction with deterministic reason code `MISSING_OR_INVALID_LINEAGE`; it is never coerced to STRICT.

- [ ] **Step 5: Build reproducible sample identity**

Sample identity binds immutable signal lineage plus the settled outcome record identity needed to reproduce the dataset:

```python
sample_identity = {
    "signal_id": row["signal_id"],
    "triggered_at": row["triggered_at"],
    "signal_class": row["signal_class"],
    "strategy_profile": row["strategy_profile"],
    "score_version": row["score_version"],
    "model_generation": row["model_generation"],
    "decision_contract_hash": row["decision_contract_hash"],
    "resolved_at": row.get("resolved_at"),
    "outcome_status": row.get("outcome_status"),
}
```

Hash sorted sample identities into `sample_set_sha256`. Outcome fields are used only when constructing the post-settlement research/calibration dataset; they must never feed an earlier entry/ranking/reassessment decision.

- [ ] **Step 6: Count deterministic exclusions**

At minimum support counts for:

```text
SIGNAL_CLASS_OUT_OF_SCOPE
MISSING_OR_INVALID_LINEAGE
OUTSIDE_OBSERVATION_WINDOW (when a window is supplied)
```

The consumer must not bypass `canonical_signal_view` to reinterpret unresolved legacy rows. Non-canonical legacy rows remain outside the authoritative candidate set by design; if the existing metadata-completeness layer supplies an aggregate count, report it separately as `NON_CANONICAL_SIGNAL_EXCLUDED` without assigning a class.

- [ ] **Step 7: Attach manifest to report**

Use:

```python
report["dataset_manifest"] = manifest.model_dump(mode="json")
```

Preserve existing:

```text
threshold_calibration_allowed=false
hard_gating_allowed=false
observational_only=true
```

- [ ] **Step 8: Run focused report tests**

```bash
pytest -q backend/tests/test_lbank_execution_outcome_report.py backend/tests/test_calibration_dataset_manifest.py
```

Expected: PASS.

---

### Task 4: Fail closed in historical ScoreV2 calibration tooling without destroying research usability

**Files:**
- Modify: `scripts/calibrate_score_v2.py`
- Modify: `backend/tests/test_score_v2_calibration.py`

- [ ] **Step 1: RED missing-manifest promotion behavior**

Existing historical backtest reports do not prove canonical STRICT lineage. Add a test that calibration may still compute research statistics but cannot emit promotion authority:

```python
result = calibrate(report_without_manifest, current_score_contract, candidate_weights)

assert result["research_only"] is True
assert result["promotion_allowed"] is False
assert result["promotion_blockers"] == ["MISSING_DATASET_MANIFEST"]
```

Use the existing test helper values for `current_score_contract` and `candidate_weights`; do not change calibration selection math.

- [ ] **Step 2: RED non-STRICT manifest behavior**

When report input includes a valid EXPERIMENTAL/MIXED research manifest:

```python
assert result["research_only"] is True
assert result["promotion_allowed"] is False
assert "NON_STRICT_DATASET" in result["promotion_blockers"]
```

- [ ] **Step 3: Validate supplied manifests using the canonical model**

Add:

```python
def _validated_dataset_manifest(report: dict) -> CalibrationDatasetManifest | None:
    raw = report.get("dataset_manifest")
    if raw is None:
        return None
    return CalibrationDatasetManifest.model_validate(raw)
```

Malformed supplied manifests raise a clear validation error rather than being ignored.

- [ ] **Step 4: Keep historical selection math unchanged**

Do not alter:

```text
APPROVED_WEIGHTS
threshold candidates
purged splits
walk-forward selection
holdout non-selection rule
performance metrics
```

P1-F wraps provenance/promotion eligibility; it does not tune ScoreV2.

- [ ] **Step 5: Make manifest policy dominate promotion claims**

The output carries:

```python
"dataset_manifest": manifest.model_dump(mode="json") if manifest else None,
"research_only": research_only,
"promotion_allowed": False,
"promotion_blockers": sorted(promotion_blockers),
```

Existing `promotion_eligibility` remains a research diagnostic but cannot override `promotion_allowed=False`.

- [ ] **Step 6: Run focused calibration tests**

```bash
pytest -q backend/tests/test_score_v2_calibration.py backend/tests/test_calibration_dataset_manifest.py
```

Expected: PASS with existing selection behavior unchanged.

---

### Task 5: Add cohort-contamination and fallback guards

**Files:**
- Modify: `backend/tests/test_canonical_signal_consumers.py`
- Modify: `backend/tests/test_lbank_execution_outcome_report.py`

- [ ] **Step 1: Prove missing lineage cannot enter strict dataset**

Use the existing schema/test helpers to insert a ledger signal without canonical metadata and assert it is absent from `canonical_signal_view`, the strict report, and the manifest sample set. Do not repair the row inside the consumer test.

- [ ] **Step 2: Prove current defaults/JSON cannot reconstruct strictness**

Insert a legacy ledger row whose `trigger_metrics_json` says `strategy_profile=strict_score_v2` but which has no canonical metadata. Assert it is excluded from strict report/calibration input.

- [ ] **Step 3: Prove EXPERIMENTAL cannot contaminate STRICT included samples or metrics**

Create dataset A with STRICT rows only. Create dataset B with the exact same STRICT rows plus one canonical EXPERIMENTAL row.

Assert:

```python
assert report_b["settlement"]["signal_count"] == report_a["settlement"]["signal_count"]
assert report_b["dataset_manifest"]["included_sample_count"] == report_a["dataset_manifest"]["included_sample_count"]
assert report_b["dataset_manifest"]["sample_set_sha256"] == report_a["dataset_manifest"]["sample_set_sha256"]
assert report_b["by_execution_status"] == report_a["by_execution_status"]
```

Because exclusion reason counts are deliberately part of semantic dataset identity, adding the out-of-scope EXPERIMENTAL row must also be observable as exclusion provenance:

```python
assert report_b["dataset_manifest"]["excluded_sample_count"] == (
    report_a["dataset_manifest"]["excluded_sample_count"] + 1
)
assert report_b["dataset_manifest"]["exclusion_reason_counts"][
    "SIGNAL_CLASS_OUT_OF_SCOPE"
] == report_a["dataset_manifest"]["exclusion_reason_counts"].get(
    "SIGNAL_CLASS_OUT_OF_SCOPE", 0
) + 1
assert report_b["dataset_manifest"]["dataset_identity_hash"] != (
    report_a["dataset_manifest"]["dataset_identity_hash"]
)
```

This distinction is intentional: the STRICT included sample set and aggregate metrics are unchanged, while the manifest records that a different source population required an exclusion.

- [ ] **Step 4: Run**

```bash
pytest -q backend/tests/test_canonical_signal_consumers.py backend/tests/test_lbank_execution_outcome_report.py
```

Expected: PASS.

---

### Task 6: Full regression and independent review

- [ ] **Step 1: Full backend + Golden + runtime parity**

```bash
pytest -q backend/tests
pytest -q backend/tests/test_golden_model_regression.py
PYTHONPATH=backend/src:. python scripts/verify_runtime_parity.py
```

Allowed P1-F differences:

```text
outcome/calibration reports gain deterministic dataset_manifest/provenance fields
production defaults remain exactly STRICT
research modes become explicitly non-promotable
historical calibration outputs gain research/promotion blocker metadata
```

Block unexpected ScoreV2 selection math, lifecycle/ranking, Entry/TP/SL, leverage, execution policy, or cohort changes.

- [ ] **Step 2: Frontend compatibility**

```bash
cd frontend
npm ci
npm run typecheck
npm run build
```

No Backtest Lab/Product UI redesign in P1-F; that belongs to later Product Layer work.

- [ ] **Step 3: Security/provenance review**

Specifically review:

```text
SQL cohort filters remain parameterized
no JSON/default fallback for lineage
canonical hash input excludes volatile generated_at but includes semantic/sample identity
scope ordering deterministic
malformed lineage fails closed
research modes cannot set promotion_allowed=true
```

- [ ] **Step 4: Exact-head CI and independent review**

Require backend/frontend/dependency-audit/container-validation/repository-hygiene PASS, CodeRabbit with no unresolved actionable findings, Sonar Quality Gate PASS, controller semantic review PASS.

- [ ] **Step 5: Certify P1-F**

Record exact head SHA and declare:

```text
P1-F = GREEN_REVIEWED
```

Then run the umbrella Wave 1D final certification before any Wave 1D merge state is declared.