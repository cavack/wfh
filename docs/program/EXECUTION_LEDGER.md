# WaterfallHunter Development Execution Ledger

Baseline: `652f99446ed523c0a602798dde4457bab7983373`

Wave 0 branch: `program/wave0-foundations-v1`

Wave 1A branch: `feat/wave1a-canonical-contracts-v1`

Wave 1B1 branch: `feat/wave1b-migration-readiness-v1`

Worktree: isolated development checkout; Production source and state are excluded.

## Program gates

| Gate | Status | Evidence |
| --- | --- | --- |
| Source authority read | PASSED | Requirements v6, Final Design v6.1, Production Baseline Audit, Master Orchestrator v7 read in full |
| GitHub main freshness | PASSED | Current `main` equalled the design baseline at the implementation-preparation freshness gate |
| Baseline reconciliation | NO_DESIGN_IMPACT | No commits after the design baseline at the freshness gate |
| Backend baseline | PASSED | 340 tests, 9 pre-existing deprecation warnings |
| Frontend baseline | PASSED | Node 20 typecheck and production build |
| Dependency baseline | PRE_EXISTING_SECURITY_FINDING_FIXED | Baseline required four exceptions; updated lock has npm: 0 and Python: 0 known vulnerabilities without exceptions |
| Compose config | PASSED | Configuration parses without Production mutation |
| Production image build | CI_PASSED | PR #22 built revision-labelled backend/frontend/watchdog artifacts and tested image-contained backend code without Production mutation |
| Static/security analysis | PASSED | Wave 0 static/security checks passed. Wave 1A and Wave 1B1 latest Sonar quality gates report 0 new issues and 0 security hotspots; substantive CodeRabbit findings were regression-tested and fixed, all inline threads are resolved, and the latest completed W1B1 incremental source review generated no actionable comments. |

## Workstreams

| ID | Workstream | Dependency | Model impact | Status |
| --- | --- | --- | --- | --- |
| W0-A | Runtime Fingerprint | baseline | NO_MODEL_IMPACT | SOURCE_GATE_PASSED; legacy capture reserved |
| W0-B | Golden Regression Corpus tooling | baseline, canonical hashing | NO_MODEL_IMPACT | CANONICAL_FIXTURES_PASSED; legacy evidence blocked |
| W0-C | Artifact/deployment provenance | W0-A contract | NO_MODEL_IMPACT | TOOLING_PASSED; running digest reserved |
| W0-D | CI/runtime artifact parity | W0-C chain | NO_MODEL_IMPACT | CI_PASSED |
| W1-A | Canonical domain contracts | Wave 0 | SEMANTIC_INFRA | MERGE_READY_PENDING_MERGE_APPROVAL |
| W1-B1 | Migration runner + DB readiness foundation | W1-A | SEMANTIC_INFRA | MERGE_READY_PENDING_MERGE_APPROVAL |
| W1-B2 | Runtime schema-ownership cutover | W1-B1 | SEMANTIC_INFRA | NOT_STARTED |
| W1-C | Unified signal metadata/cohort purity | W1-B2 | SEMANTIC_INFRA | BLOCKED_ON_W1_B2 |
| W1-D | Probability/freshness/strict filtering | W1-C | SEMANTIC_INFRA | NOT_STARTED |
| W2 | Typed API, dashboard, Telegram, observability | Wave 1 | mixed | NOT_STARTED |
| W3 | Execution/risk/portfolio/backtest | Wave 2 | MODEL_AFFECTING where noted | NOT_STARTED |
| W4 | Observational intelligence | Wave 3 | OBSERVATIONAL_MODEL_CHANGE | NOT_STARTED |
| W5 | Scientific promotion | clean strict dataset | MODEL_AFFECTING | BLOCKED |
| W6 | Certification | all prior waves | mixed | NOT_STARTED |

## Controller rulings

1. Existing ScoreV2 and balanced-signal plans remain historical implementation evidence. Their real-data-only, paper-only, conservative same-bar, and validator-ownership rules remain binding.
2. Their old `ARMED`-requires-trigger semantics are superseded only in Lifecycle V2 shadow work; current model behavior is preserved until Golden Corpus and OOS gates pass.
3. No Production DB, backup, migration, deployment, restart, Telegram message, live trading, or merge is authorized.
4. The canonical fixture corpus is not a substitute for real-data replay, OOS evidence, or the legacy-runtime corpus.
5. W1-A is contract vocabulary only: no active consumer imports/cutover, no ScoreV2/lifecycle/ranking/execution semantic change.
6. A green quality gate does not by itself clear static-analysis findings; substantive findings must be inspected, fixed, or explicitly adjudicated before `MERGE_READY`.
7. W1-B is split into B1 foundation and B2 schema-ownership cutover. W1-C cannot begin until B2 is independently verified.
8. Branch synchronization inside the development stack does not constitute `MERGE_APPROVAL` and must not merge any PR or update `main`.

## Wave 0 review evidence

- Draft PR: #22.
- Backend: 346 passed; 9 pre-existing deprecation warnings.
- Frontend: Node 26 typecheck and production build passed.
- Dependency audit: backend, watchdog, and npm passed with zero known findings and no audit exceptions.
- Artifact parity: Python 3.13 and Node 26 declarations match digest-only image inputs; container validation passed.
- Independent analysis: SonarCloud initially found seven issues; all were fixed without suppressions and the rerun quality gate passed. CodeQL reported no new alerts.
- Model impact: no scoring, threshold, lifecycle, trigger, or execution-level changes; canonical fixture replay remained exact.
- Remaining hard gate: legacy-runtime evidence capture requires separate Production authorization before model-affecting work.

## Wave 1A canonical-contract evidence

- Draft stacked PR: #23.
- Base: `program/wave0-foundations-v1` at `497ed954b09c158fcbf02df47a0f196eda5d61ab`.
- Verified code/test head before this ledger-only commit: `b0ddfa6de937841296b46107e6990a10b135ba5e`.
- Model impact classification: `SEMANTIC_INFRA`.
- Active consumer cutover: none.
- Production mutation: none.

### TDD RED evidence

1. Initial vocabulary RED: `3 failed, 346 passed` — intentionally missing `waterfallhunter.core.contracts`.
2. Signal/execution packet RED: `5 failed, 349 passed` — absent `SignalDecisionPacket` / `ExecutionPlan` contracts.
3. Position/notification RED: `5 failed, 354 passed` — absent `PositionState`, `PositionAmendment`, and `NotificationEvent`.
4. Contract identity review RED: `2 failed, 361 passed` — mismatched `contract_type` / `contract_version` accepted before fix.
5. Deep-immutability / payload-security review RED: `3 failed, 363 passed` — nested validated data remained mutable and delivery/secret payload keys were not fully rejected.
6. Concatenated/plural secret-key review RED: `7 failed, 366 passed` — `apitoken`, `accesstoken`, `authtoken`, `bearertoken`, `usersecret`, `tokens`, and `credentials` passed before hardening.

### Final verification at `b0ddfa6...`

- Backend full suite: `374 passed, 9 warnings`.
- Runtime parity: `runtime declarations are aligned`.
- Frontend Node 26 typecheck and production build: passed.
- Dependency audit: Python and npm jobs passed.
- Container validation: revision-labelled production artifacts built; exact backend artifact family tested; OCI revision labels verified.
- Repository hygiene/secret scan: passed.
- SonarQube Cloud: quality gate passed; `0 New issues`; `0 Security Hotspots`; no accepted/suppressed issue required.
- CodeRabbit: substantive findings on deep immutability, payload field isolation, and concatenated secret-like keys were fixed. All inline review threads are resolved. The latest completed incremental source review (`36a60af...` → `b69c3df...`) generated no actionable comments.
- Additional review coverage: explicit tests now cover non-finite JSON numbers, non-string object keys, and unsupported container values.
- Manual security diff scope: canonical contract code introduces validation/serialization only; no network/file/subprocess/credential/order-execution path and no active consumer cutover.
- Model semantic diff: none expected or accepted; no active scoring/lifecycle/ranking/execution behavior was modified.

### Wave 1A controller state

`W1-A = MERGE_READY_PENDING_MERGE_APPROVAL`.

This is an evidence state only. PR #23 remains Draft and unmerged. `MERGE_APPROVAL` has not been granted.

## Wave 1B1 migration/readiness foundation evidence

- Draft stacked PR: #24.
- Base branch: `feat/wave1a-canonical-contracts-v1`.
- Pre-stack-sync implementation head: `a57e92b693302531a56cfcdede164b2c62ce48c3`.
- Final reviewed source/test head before this ledger-only commit: `1e4c043a3649d93496fa4013289cc180fab1af3e`.
- Model impact classification: `SEMANTIC_INFRA`.
- Runtime schema-ownership cutover: none; reserved for W1-B2.
- Production migration/readiness probe: never executed.

### Implemented B1 scope

- first-party packaged migration discovery and canonical `NNNN_name.sql` identity;
- exact-byte SHA-256 migration checksums and canonical reconstruction of caller-supplied migration objects;
- immutable `schema_migrations` history with verified UPDATE/DELETE abort triggers;
- fail-closed history schema validation, including sole `version` primary key and required column constraints;
- `PRAGMA user_version` consistency and fail-closed state verification;
- per-migration atomic transaction and rollback;
- serialized pending re-check under `BEGIN IMMEDIATE` for concurrent runners;
- dedicated `db_readiness_probe` migration only;
- rollback-only deep readiness primitive with bounded busy timeout;
- URI-safe SQLite read/write probing for database paths containing reserved URI characters;
- optional integrity/FK checks, zero-residue verification, and typed `require_ready()` failure;
- schema-ownership inventory for the later B2 cutover.

### TDD / hardening evidence

- discovery foundation RED: missing migration module/package;
- runner RED: `6 failed, 370 passed` before `MigrationRunner` implementation;
- readiness RED: `8 failed, 376 passed` before `db_readiness` implementation;
- migration hardening RED: `2 failed, 393 passed` for migration identity/filename mismatch and missing-parent directory auto-creation;
- external review RED: `4 failed, 396 passed` for URI-special database paths and malformed migration-history reads;
- integrity/concurrency review RED: `8 failed, 400 passed` for incomplete history schema, weakened constraints, forged checksum/noncanonical migration identity, and concurrent-runner race;
- immutability review RED: `3 failed, 408 passed` for extra composite primary key, wrong-target immutability trigger, and non-aborting immutability trigger.

### Final source/test verification at `1e4c043...`

- Backend full suite: `411 passed, 9 warnings`.
- Runtime parity: `runtime declarations are aligned`.
- Frontend Node 26 typecheck and production build: passed.
- Dependency audit: Python and npm jobs passed.
- Container validation: revision-labelled production artifacts built; exact backend artifact family tested; OCI revision labels verified.
- Repository hygiene/secret scan: passed.
- SonarQube Cloud: quality gate passed; `0 New issues`; `0 Accepted issues`; `0 Security Hotspots`.
- CodeRabbit: URI handling, malformed history, schema completeness, checksum provenance, concurrent runners, composite-PK rejection, and immutable-trigger validation findings were fixed with regression tests. All inline review threads are resolved. Manual incremental review run `237943ef-3598-4f11-bcd2-6b17aef02464` over `249da967...` → `1e4c043...` generated no actionable comments.
- CodeRabbit docstring coverage remains a non-functional advisory warning; no behavior, safety, or integrity finding remains open.
- Model semantic diff: none expected or accepted; no scoring, lifecycle, ranking, execution-level, Telegram, or trading behavior was modified.
- Production mutation: none.

### B2 read-only inventory refresh

Repository-wide source searches reconfirm the existing runtime schema-mutation inventory. `CREATE TABLE` remains present across the catalog/ledger/outcome/lifecycle/evidence/replay/execution/provider/streaming/application stores, while explicit `ALTER TABLE` evolution remains concentrated in `core/db.py`, `core/lbank_signal_ledger.py`, `core/production_evidence.py`, and `core/lbank_execution_store.py`; `PRAGMA table_info` migration-like checks remain in `core/db.py`, `core/lbank_signal_ledger.py`, and `core/production_evidence.py` (plus tests). No B2 runtime cutover has started.

### Wave 1B1 controller state

`W1-B1 = MERGE_READY_PENDING_MERGE_APPROVAL`.

This is an evidence state only. PR #24 remains Draft and unmerged. `MERGE_APPROVAL` has not been granted. W1-B2 may proceed only as development-side planning/implementation under the approved safety gates; no Production migration is implied or authorized.

## Wave 1C unified signal metadata/cohort purity evidence

- Draft stacked PRs: #32 (P1-C1) and #34 (P1-C2/current continuation).
- Fresh design/main baseline during Task 10: `652f99446ed523c0a602798dde4457bab7983373`.
- P1-C1 reviewed head: `acfe88cab5a31f31f8fb70ebc8d7219b0f450db1`.
- Task 5 certified head: `0fb70fe5c1994d2da6f8ee59cd3e5147c8183af5`.
- Task 10 source head before this ledger-only commit: `0b60b2d5f6cde6cb375d2942ae8ef31561d39dbe`.
- Current model impact classification: `SEMANTIC_INFRA`.
- Runtime schema target: v3 via `0003_signal_metadata.sql`.
- Production migration/classification: never executed.

### Sequencing and drift reconciliation

The continuation checkpoint ended at temporary patcher commit `f557cea2e34a10266f9929187fe08c5025a14a13`. Fresh GitHub reconciliation showed the branch had advanced by 26 commits and that Tasks 6–9 had been implemented after a separately certified Task 5 state. Task 5 CI run `32371611995` at `0fb70fe5...` was GREEN (`520 passed`, 9 warnings; runtime/frontend/dependency/hygiene/container all PASS), so Task 6 did not start before Task 5 was genuinely GREEN.

The temporary `.github/workflows/wave1c2-task5-patch.yml` is removed from the current diff. Its resulting source edits were audited; no patcher workflow remains in the PR.

### Task 4–9 invariants

- future signals require explicit canonical metadata before persistence;
- catalogue CAS + ledger + metadata share one transaction and roll back together;
- missing/unknown lineage never defaults to STRICT;
- strict and experimental class/profile/score-version mappings are explicit and fail closed;
- decision lineage hashes use deterministic RFC8785/JCS SHA-256 over the deterministic decision contract;
- observation timestamps are captured at the observation/analysis boundary, not substituted with persistence time;
- legacy classification is persisted-evidence-only, deterministic, read-only in preview, hash-gated, `BEGIN IMMEDIATE`, INSERT-only, and never rewrites legacy ledger rows;
- unresolved/conflicting legacy rows receive no metadata and remain outside `canonical_signal_view`;
- outcome settlement reads canonical rows and carries explicit cohort identity;
- default reporting is STRICT-only; non-STRICT modes are explicitly research-only;
- startup verifies schema/completeness before workers and never migrates/classifies/repairs/backfills.

### TDD and review hardening

- Task 5 review RED: `4 failed, 535 passed` at `75c5f3eef9abc266f8f0170e05f7dd385b372f8b`, reproducing invalid metadata timestamp coercion plus canonical score-version invariant failures.
- Minimal fixes centrally enforced canonical class/profile/score-version mapping and rejected boolean/string/fractional/negative metadata timestamps.
- A subsequent full run exposed one stale experimental fixture: `1 failed, 538 passed`; the fixture was aligned to canonical `score_v2_watch_v1` without weakening validation.
- CodeRabbit current commit status on `0b60b2d5...`: SUCCESS.
- Inline review threads: 0 unresolved.
- A CodeRabbit suggestion to ignore `created_at` when comparing pre-existing legacy metadata was rejected because the approved continuation contract requires the pre-existing metadata row to match exactly, and the design permits repeated classification to be idempotent or fail-closed without rewrite.
- Shared score-version constants, complexity extraction, test connection hygiene, and extra classifier fixture cases were adjudicated as maintainability/test-depth advisories rather than demonstrated safety/model defects; no certification-time refactor was introduced solely for those advisories.

### Task 10 verification

Authoritative GitHub Actions run `32379224230` on Ubuntu / CPython 3.13.15, PR merge revision `05d64093043af598d6d7dcc212263f96133f1d72`:

- full backend: `539 passed, 9 warnings`;
- runtime parity: PASS;
- frontend typecheck/build: PASS;
- dependency audit: PASS;
- repository hygiene/secret scan: PASS;
- container validation: PASS, including Compose validation, revision-labelled backend/frontend/watchdog builds, exact backend artifact-family tests, and OCI revision-label verification.

Independent development worktree pinned exactly to `0b60b2d5...`:

- focused P1-C suite: `71 passed, 5 warnings`;
- Golden/model regression: `2 passed`; the canonical corpus test performs three deterministic replays per case and matched the baseline-bound expected outputs;
- no unexpected Golden difference in score, eligibility, lifecycle/reason behavior, ranking/order, leverage, or model-regression outputs.

A supplemental Windows/Python-3.13 full-backend run produced `538 passed, 1 failed`; the sole failure is `test_readiness_targets_exact_database_path_with_uri_special_characters[question?name.db]`, because `?` is not a valid Windows filename. The authoritative Linux/Python-3.13.15 CI passes the same complete suite `539/539`. No source or fixture was changed to mask that platform-specific limitation.

### Static/security evidence and known limitation

- Current CodeRabbit status: SUCCESS with zero unresolved inline threads.
- A prior DeepSource PR report on an older head/range reported Overall Grade A and Security A; its older Python inline findings were subsequently fixed/resolved.
- No fresh latest-head DeepSource Python rerun is exposed as current GitHub evidence.
- No fresh latest-head Sonar Quality Gate is exposed as current GitHub evidence.
- Those latest-head external static-analysis gates are therefore not silently assumed GREEN.
- CodeRabbit's docstring-coverage warning remains non-functional advisory evidence rather than a required branch-protection check.

### Controller review answers

1. Future signal without metadata: **No — fail-closed and atomic metadata persistence is required.**
2. Unresolved legacy in canonical view: **No — no metadata means exclusion by INNER JOIN.**
3. Missing lineage defaulting to STRICT: **No.**
4. Metadata failure leaving partial catalogue/ledger state: **No — transaction rolls back.**
5. Default reports including EXPERIMENTAL: **No — default is STRICT.**
6. Startup migrating/classifying/repairing: **No — startup is verification-only.**
7. Classifier using current defaults to reconstruct history: **No — persisted historical evidence only.**
8. Score/lifecycle/ranking/execution semantic change: **No unexpected change observed; Golden three-replay equality passed.**

### Wave 1C controller state

`W1-C = CERTIFIED_WITH_KNOWN_LIMITATIONS`.

The remaining limitation is evidence completeness for fresh latest-head external static-analysis reruns (Sonar / DeepSource Python), not a known functional, safety, or model-semantic regression. This state does not qualify as `MERGE_READY_PENDING_MERGE_APPROVAL` yet.

PR #34 remains Draft and unmerged. No Production backup, Production DB write, Production migration/classification/schema mutation, deployment, Docker/service restart/build on Production, server package install, Telegram test send, live trading, merge, or auto-merge was performed. `LIVE_TRADING_ENABLED=false` remains invariant.

### Task 10 external-review closure

The prior `CERTIFIED_WITH_KNOWN_LIMITATIONS` state is superseded by fresh latest-head evidence collected after the certification ledger commit.

- Source head before this final evidence-only ledger update: `c05c492a31991a33b3d4f980a167af76f259c92a`.
- The only source delta after `00a825d...` narrowed an already-validated error message; commit `c05c492...` changed one string literal and no persistence/model/control-flow semantics.
- Current GitHub Actions run `32386835967`: backend, frontend, dependency-audit, repository-hygiene, and container-validation all PASS.
- Backend on Ubuntu / CPython 3.13.15: `539 passed, 9 warnings`; runtime parity PASS; `LIVE_TRADING_ENABLED=false`.
- Exact-head focused P1-C suite on the isolated development worktree: `71 passed, 5 warnings`.
- Exact-head Golden/model regression: `2 passed`; canonical cases retain deterministic three-replay equality.

#### Independent review closure

- CodeRabbit run `2681d0d0-ea4f-4afc-8ca6-7a9ea50aaff0` found one Minor logging-accuracy issue only; it was fixed by `c05c492...`.
- Follow-up CodeRabbit run `c2ba33df-3980-4aa1-96bb-bef81c08f9b7` over `00a825d... -> c05c492...` generated no actionable comments.
- Current CodeRabbit check is PASS; no new unresolved inline review thread was introduced.
- CodeRabbit's docstring-coverage item remains a non-functional advisory, not a branch-protection or Task-10 safety/model gate.

#### Sonar/security gate closure

- `gh pr checks 32 --repo cavack/wfh` reports `SonarCloud Code Analysis` PASS for P1-C1, covering migration 3, metadata schema/view, and managed-schema foundation scope.
- SonarQube Cloud API for project `cavack_wfh`, pull request 32: Quality Gate `OK`; new security rating `1` (A), new reliability rating `1` (A), new maintainability rating `1` (A), new duplicated-lines density `0.0`, and new security hotspots reviewed `100.0%`.
- PR #32 unresolved Sonar vulnerabilities: `0`; TO_REVIEW security hotspots: `0`.
- `gh pr checks 34 --repo cavack/wfh` reports `SonarCloud Code Analysis` PASS for P1-C2/current Task-10 head, covering atomic persistence, future metadata producer, classifier, canonical consumers, reporting, and startup gate.
- SonarQube Cloud API for project `cavack_wfh`, pull request 34: Quality Gate `OK`; new security rating `1` (A), new reliability rating `1` (A), new maintainability rating `1` (A), new duplicated-lines density `0.0`, and new security hotspots reviewed `100.0%`.
- PR #34 unresolved Sonar vulnerabilities: `0`; TO_REVIEW security hotspots: `0`.
- A supplementary manual security-diff review found no reportable vulnerability in changed SQL/query construction, transaction boundaries, legacy read-only/hash-gated classification, metadata validation, canonical consumer filtering, or startup fail-closed behavior.
- A fresh DeepSource rerun was requested but is not used as a Task-10 gate; the approved implementation plan requires Sonar/security diff review and independent CodeRabbit/controller review, both now satisfied.

### Superseding Wave 1C controller state

`W1-C = MERGE_READY_PENDING_MERGE_APPROVAL`.

All development-side Task-10 gates are now satisfied. This is an evidence/certification state only. It does not authorize merge, Production backup, Production DB write, migration/classification, deployment, Production restart/build, Telegram send, package installation, or live trading. PR #34 remains Draft and unmerged; `MERGE_APPROVAL` has not been granted.
