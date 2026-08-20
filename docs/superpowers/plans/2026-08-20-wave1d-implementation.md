# Wave 1D Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Final Design v6.1 workstreams P1-D Probability Cleanup, P1-E Freshness Contracts, and P1-F Strict Outcome / Calibration Filtering without inventing predictive semantics, weakening cohort purity, or touching Production before the independent approval gates.

**Architecture:** Wave 1D is an execution umbrella over three sibling Final Design workstreams. Implementation is intentionally serialized for TDD/review attribution: P1-D first, then P1-E, then P1-F. Each slice has its own focused plan, RED/GREEN evidence, full regression, independent review, and certification gate. The slices converge before P2 Typed API.

**Tech Stack:** Python 3.13 CI/runtime-parity contract, FastAPI, Pydantic v2, SQLite/WAL managed schema v3, Next.js/TypeScript, pytest, GitHub Actions, Docker/Compose, SonarQube Cloud, CodeRabbit.

**Spec:** `docs/superpowers/specs/2026-08-20-wave1d-probability-freshness-strict-filtering-design.md`

## Global Constraints

- Canonical repository: `cavack/wfh`.
- The approved Wave 1D design is the specification; Audit/Product Requirements are requirement inventory, while Final Design v6.1 controls architecture/dependency order.
- Do not implement Wave 1D source changes on top of the existing deep Wave 0→1C PR stack. First merge the already-certified stack into `main` under explicit `MERGE_APPROVAL`, then branch P1-D from the resulting fresh `main`.
- Existing merge order is `#22 → #23 → #24 → #25 → #31 → #32 → #34`; after each parent merge, retarget the child to `main`, re-run fresh diff/CI/review/mergeability checks, then merge only if GREEN. PR #35 is independent and is not part of this chain.
- `LIVE_TRADING_ENABLED=false` remains invariant.
- LBank USDT Perpetual remains the user-facing execution source of truth.
- `margin_mode=ISOLATED`; Cross Margin remains forbidden.
- No probability proxy may replace `calibrated_probability`; valid current value remains `None`.
- No new Final Signal Score weighting, ranking feature, freshness threshold, lifecycle threshold, execution policy, leverage policy, or AI policy is authorized by Wave 1D.
- P1-D/P1-E/P1-F are sibling architecture workstreams; the serial order below is an implementation/review strategy, not a new architectural dependency.
- No new Production schema migration is planned in Wave 1D. If a new persisted Production table/column is found necessary, stop and return to design review.
- No Production backup, DB write, migration/classification, deployment, Docker build/restart/up/down, service restart, package install, Telegram send, or live trading occurs in this plan.
- `DESIGN_APPROVAL != MERGE_APPROVAL != BACKUP_EXECUTION_APPROVAL != MIGRATION_APPROVAL != DEPLOYMENT_APPROVAL`.
- Production remains `LEGACY_RUNTIME_UNVERIFIED_REVISION` until a future verified deployment; never assign a retrospective Git SHA.
- Every source task follows RED → exact failure → minimal GREEN → focused regression → full regression → independent review → fix/re-review.
- Golden/model fixture changes require enumerated expected semantic differences. Never normalize a fixture merely to make CI green.

## Plan Decomposition

1. `docs/superpowers/plans/2026-08-20-wave1d-p1d-probability-cleanup-implementation.md`
2. `docs/superpowers/plans/2026-08-20-wave1d-p1e-freshness-contracts-implementation.md`
3. `docs/superpowers/plans/2026-08-20-wave1d-p1f-strict-calibration-filtering-implementation.md`

---

### Task 0: Establish the executable baseline

- [ ] **Step 1: Freshly verify the repository immediately before the first merge mutation**

Required evidence:

```text
main SHA
main branch protection and required checks
PR #22/#23/#24/#25/#31/#32/#34 heads, bases, Draft state, mergeability
current CI/status checks for the exact head being merged
```

Expected result: no unexplained drift from the certified Wave 1C chain. Any drift is reconciled before merge.

- [ ] **Step 2: Merge the Wave 0→1C stack only after explicit `MERGE_APPROVAL`**

For each PR in order:

```text
fresh verify parent/main
mark ready only if required and justified
merge parent
retarget child base to main
fresh compare + CI + Sonar/CodeRabbit/review
merge child only when GREEN
```

Expected result: Wave 1C source and docs land on `main` without flattening child deltas incorrectly.

- [ ] **Step 3: Establish a fresh post-merge baseline**

Run/read:

```bash
pytest -q backend/tests
PYTHONPATH=backend/src:. python scripts/verify_runtime_parity.py
cd frontend && npm ci && npm run typecheck && npm run build
```

Also require GitHub required checks and container-validation on the exact merged `main`.

Expected result: post-Wave1C `main` is GREEN and becomes the sole branch point for P1-D.

---

### Task 1: Execute P1-D Probability Cleanup

- [ ] Follow every task in `2026-08-20-wave1d-p1d-probability-cleanup-implementation.md`.
- [ ] Branch from the fresh post-Wave1C `main`, not PR #36 or the old stacked feature chain.
- [ ] Do not start P1-E until P1-D focused tests, full regression, Golden differential review, static/security checks, CodeRabbit, and controller review are GREEN.

Expected P1-D intentional semantic delta:

```text
remove invalid tp_24h_probability runtime dependency
remove its ranking component and confidence penalty
remove its dashboard/Telegram exposure
version the observational ranking contract
no replacement probability or recalibration
```

---

### Task 2: Execute P1-E Freshness Contracts

- [ ] Follow every task in `2026-08-20-wave1d-p1e-freshness-contracts-implementation.md`.
- [ ] Base P1-E on the certified P1-D head.
- [ ] Preserve P1-D ranking behavior exactly; P1-E is not authorized to recalibrate ranking.
- [ ] Do not start P1-F until the independent analysis/reference freshness matrix and full regression are GREEN.

Expected P1-E intentional semantic delta:

```text
analysis freshness and reference freshness become independent canonical facts
missing/stale data fails closed with explicit status/qualifiers
EvidenceQualityPacket aligns with v1.1 contract
no new numeric freshness threshold is invented
```

---

### Task 3: Execute P1-F Strict Outcome / Calibration Filtering

- [ ] Follow every task in `2026-08-20-wave1d-p1f-strict-calibration-filtering-implementation.md`.
- [ ] Base P1-F on the certified P1-E head.
- [ ] Use `canonical_signal_view` lineage fields; never fall back to legacy JSON/current defaults.
- [ ] Keep EXPERIMENTAL/MIXED explicit research-only and non-promotable.

Expected P1-F intentional semantic delta:

```text
production-facing outcome/calibration inputs default exactly to STRICT
calibration/report datasets carry deterministic lineage/cohort/provenance manifests
missing lineage fails closed
research cohorts cannot become promotion evidence by declaration
```

---

### Task 4: Wave 1D final certification

- [ ] **Step 1: Run the exact focused suites for all three slices**

```bash
pytest -q \
  backend/tests/test_probability_cleanup.py \
  backend/tests/test_final_ranking.py \
  backend/tests/test_dashboard.py \
  backend/tests/test_notifier.py \
  backend/tests/test_freshness_contracts.py \
  backend/tests/test_canonical_contracts.py \
  backend/tests/test_stale_trigger_safety.py \
  backend/tests/test_calibration_dataset_manifest.py \
  backend/tests/test_lbank_execution_outcome_report.py \
  backend/tests/test_score_v2_calibration.py \
  backend/tests/test_canonical_signal_consumers.py
```

Expected: all pass.

- [ ] **Step 2: Run full backend + deterministic Golden regression**

```bash
pytest -q backend/tests
pytest -q backend/tests/test_golden_model_regression.py
PYTHONPATH=backend/src:. python scripts/verify_runtime_parity.py
```

Expected: all pass; Golden differences are limited to the explicitly approved P1-D/P1-E semantics and are documented before any fixture update.

- [ ] **Step 3: Run frontend and artifact-family verification**

```bash
cd frontend
npm ci
npm run typecheck
npm run build
```

Require GitHub `container-validation` to build revision-labelled production artifacts and test the exact backend artifact family.

- [ ] **Step 4: Independent review gates**

Require on exact final head:

```text
GitHub required checks PASS
CodeRabbit review with zero unresolved actionable findings
Sonar Quality Gate PASS and hotspots reviewed
controller semantic review
security diff review for contract/filter/hash/query changes
```

- [ ] **Step 5: Certify development-side state**

Only if every gate above is GREEN, update execution evidence and declare exactly:

```text
W1-D = MERGE_READY_PENDING_MERGE_APPROVAL
```

This state is not Production certification and grants no merge/deploy/migration/backup authority.

## Post-Wave1D Boundary

After a later explicit Wave 1D `MERGE_APPROVAL`, the next planned Production-facing window is still gated separately:

```text
fresh read-only Production preflight
→ BACKUP_EXECUTION_APPROVAL
→ online SQLite backup + SHA256 + restore/integrity/FK/critical-count/rollback verification
→ MIGRATION_APPROVAL
→ managed schema migration + deterministic legacy classification
→ post-migration verification
→ DEPLOYMENT_APPROVAL
→ deploy verified W1C+W1D artifact
→ readiness/runtime/provenance verification
```

No host command belongs to Wave 1D implementation preparation itself.