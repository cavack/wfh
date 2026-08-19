# WaterfallHunter Development Execution Ledger

Baseline: `652f99446ed523c0a602798dde4457bab7983373`

Wave 0 branch: `program/wave0-foundations-v1`

Wave 1A branch: `feat/wave1a-canonical-contracts-v1`

Worktree: isolated development checkout; Production source and state are excluded.

## Program gates

| Gate | Status | Evidence |
| --- | --- | --- |
| Source authority read | PASSED | Requirements v6, Final Design v6.1, Production Baseline Audit, Master Orchestrator v7 read in full |
| GitHub main freshness | PASSED | Current `main` equals design baseline |
| Baseline reconciliation | NO_DESIGN_IMPACT | No commits after the design baseline |
| Backend baseline | PASSED | 340 tests, 9 pre-existing deprecation warnings |
| Frontend baseline | PASSED | Node 20 typecheck and production build |
| Dependency baseline | PRE_EXISTING_SECURITY_FINDING_FIXED | Baseline required four exceptions; updated lock has npm: 0 and Python: 0 known vulnerabilities without exceptions |
| Compose config | PASSED | Configuration parses without Production mutation |
| Production image build | CI_PASSED | PR #22 built revision-labelled backend/frontend/watchdog artifacts and tested image-contained backend code without Production mutation |
| Static/security analysis | PASSED_WITH_REVIEW_FOLLOWUP | Wave 0 SonarCloud/CodeQL/CodeFactor passed. Wave 1A Sonar quality gate passed with 0 security hotspots but reports 10 new non-gating issues awaiting detailed adjudication; CodeRabbit review was explicitly triggered on draft PR #23. |

## Workstreams

| ID | Workstream | Dependency | Model impact | Status |
| --- | --- | --- | --- | --- |
| W0-A | Runtime Fingerprint | baseline | NO_MODEL_IMPACT | SOURCE_GATE_PASSED; legacy capture reserved |
| W0-B | Golden Regression Corpus tooling | baseline, canonical hashing | NO_MODEL_IMPACT | CANONICAL_FIXTURES_PASSED; legacy evidence blocked |
| W0-C | Artifact/deployment provenance | W0-A contract | NO_MODEL_IMPACT | TOOLING_PASSED; running digest reserved |
| W0-D | CI/runtime artifact parity | W0-C chain | NO_MODEL_IMPACT | CI_PASSED |
| W1-A | Canonical domain contracts | Wave 0 | SEMANTIC_INFRA | UNDER_REVIEW |
| W1-B | Migration framework/readiness | W1-A | SEMANTIC_INFRA | NOT_STARTED |
| W1-C | Unified signal metadata/cohort purity | W1-B | SEMANTIC_INFRA | NOT_STARTED |
| W1-D | Probability/freshness/strict filtering | W1-C | SEMANTIC_INFRA | NOT_STARTED |
| W2 | Typed API, dashboard, Telegram, observability | Wave 1 | mixed | NOT_STARTED |
| W3 | Execution/risk/portfolio/backtest | Wave 2 | MODEL_AFFECTING where noted | NOT_STARTED |
| W4 | Observational intelligence | Wave 3 | OBSERVATIONAL_MODEL_CHANGE | NOT_STARTED |
| W5 | Scientific promotion | clean strict dataset | MODEL_AFFECTING | BLOCKED |
| W6 | Certification | all prior waves | mixed | NOT_STARTED |

## Controller rulings

1. Existing ScoreV2 and balanced-signal plans remain historical implementation evidence. Their real-data-only, paper-only, conservative same-bar, and validator-ownership rules remain binding.
2. Their old `ARMED`-requires-trigger semantics are superseded only in Lifecycle V2 shadow work; current model behavior is preserved until Golden Corpus and OOS gates pass.
3. No Production DB, backup, migration, deployment, restart, Telegram message, or merge is authorized.
4. The canonical fixture corpus is not a substitute for real-data replay, OOS evidence, or the legacy-runtime corpus.
5. W1-A is contract vocabulary only: no active consumer imports/cutover, no ScoreV2/lifecycle/ranking/execution semantic change.
6. A green quality gate does not by itself clear new static-analysis issues; substantive findings must be inspected, fixed, or explicitly adjudicated before `MERGE_READY`.

## Wave 0 review evidence

- Draft PR: <https://github.com/cavack/wfh/pull/22>
- Backend: 346 passed; 9 pre-existing deprecation warnings.
- Frontend: Node 26 typecheck and production build passed.
- Dependency audit: backend, watchdog, and npm passed with zero known findings and no audit exceptions.
- Artifact parity: Python 3.13 and Node 26 declarations match digest-only image inputs; container validation passed.
- Independent analysis: SonarCloud initially found seven issues; all were fixed without suppressions and the rerun quality gate passed. CodeQL reported no new alerts.
- Model impact: no scoring, threshold, lifecycle, trigger, or execution-level changes; canonical fixture replay remained exact.
- Remaining hard gate: legacy-runtime evidence capture requires separate Production authorization before model-affecting work.

## Wave 1A canonical-contract evidence

- Draft stacked PR: <https://github.com/cavack/wfh/pull/23>
- Base: `program/wave0-foundations-v1` at `497ed954b09c158fcbf02df47a0f196eda5d61ab`.
- Code head before this ledger-only update: `e37f9ddc97666dbb5a3c0331253b4a2503d1dc1c`.
- Model impact classification: `SEMANTIC_INFRA`.
- Active consumer cutover: none.
- Production mutation: none.

### TDD RED evidence

1. Initial vocabulary RED: `3 failed, 346 passed` — all failures were the intentionally missing `waterfallhunter.core.contracts` module.
2. Signal/execution packet RED: `5 failed, 349 passed` — failures were absent `SignalDecisionPacket` / `ExecutionPlan` contracts.
3. Position/notification RED: `5 failed, 354 passed` — failures were absent `PositionState`, `PositionAmendment`, and `NotificationEvent`.
4. Independent review fix RED: `2 failed, 361 passed` — concrete packets incorrectly accepted mismatched `contract_type` / `contract_version`; test proved the provenance weakness before the fix.

### Final code verification at `e37f9dd...`

- Backend full suite: `363 passed, 9 warnings`.
- Runtime parity: `runtime declarations are aligned`.
- Frontend Node 26: typecheck and production build passed.
- Dependency audit: Python and npm jobs passed.
- Container validation: revision-labelled production artifacts built; exact backend artifact family tested; OCI revision labels verified.
- Repository hygiene/secret scan: passed.
- SonarQube Cloud quality gate: passed; `0 Security Hotspots`; 10 new non-gating issues remain visible in the PR decoration and are not yet treated as resolved.
- CodeRabbit: status success existed; draft review was skipped automatically, then a one-off `@coderabbitai review` was explicitly triggered for detailed review.
- Manual contract review finding fixed: each concrete packet now locks its canonical `contract_type` and `contract_version` with `Literal` validation.
- Security diff scope: the only new runtime source module is `backend/src/waterfallhunter/core/contracts.py`; it performs validation only, introduces no network/file/subprocess/credential/order-execution path, and keeps all models frozen/extra-forbid. Full dedicated Codex Security helper is not exposed in this session; external CodeQL/Sonar plus manual diff review are the available coverage.
- Model semantic diff: none expected or accepted; new contracts are not imported by active scoring/lifecycle/ranking/execution consumers.

### Wave 1A remaining review gate

`W1-A` remains `UNDER_REVIEW` until the current PR's 10 Sonar issues and the explicitly triggered CodeRabbit review are inspected/adjudicated. It is not merged and is not yet declared `MERGE_READY`.
