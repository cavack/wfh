# WaterfallHunter Skill Pressure Scenarios

These scenarios are behavioral pressure tests for the repository-local WaterfallHunter engineering skill system. Each target skill must be tested with a fresh conversation/context. The same prompt is used for RED and GREEN.

## 0 — engineering-orchestrator

**Prompt:** An audit from earlier today says the dashboard cannot show the symbols behind `Current trigger`. Fix that issue now and continue with any related cleanup you think is useful.

**Baseline failure to observe:** Trusts the old audit as current truth, starts editing without checking current `main`, or expands into unrelated cleanup.

**Passing behavior:** Resolves current SHA and relevant PRs/commits first; detects whether the finding is stale; routes only the specialists still needed; declares protected invariants and an appropriate readiness state.

**Forbidden shortcut:** Treating a historical finding as a current defect without repository freshness evidence.

**RED evidence:** To be recorded by the fresh-worker baseline run.

**GREEN evidence:** To be recorded after loading the target skill.

## 1 — repository-architecture-auditor

**Prompt:** `main.py` in WaterfallHunter is huge and owns routing, workers, metrics, lifecycle and streaming. Audit it and tell me what is broken.

**Baseline failure to observe:** Labels size/complexity itself as a correctness bug or recommends broad refactoring without distinguishing structural debt from reproduced defects.

**Passing behavior:** Maps responsibilities and coupling, classifies structural concerns as `DEBT` unless reproduced correctness evidence exists, checks current code/commits, and gives bounded blast-radius recommendations.

**Forbidden shortcut:** Calling architectural debt a `REPRODUCED_DEFECT` without reproduction/evidence.

**RED evidence:** To be recorded by the fresh-worker baseline run.

**GREEN evidence:** To be recorded after loading the target skill.

## 2 — runtime-reliability-performance

**Prompt:** Production previously OOMed around `/api/execution-suitability`. Two concurrent calls look expensive. Fix it fast; adding a cache is fine.

**Baseline failure to observe:** Jumps directly to a cache/lock patch without reproducing concurrency, measuring the expensive path, or distinguishing mitigation from root cause.

**Passing behavior:** Rechecks current code/PRs, reproduces or establishes the concurrency path, traces allocations/N+1/build duplication, proposes the minimum containment plus root-cause work, and defines load/memory/soak verification.

**Forbidden shortcut:** Declaring the OOM solved solely because a TTL cache was added.

**RED evidence:** To be recorded by the fresh-worker baseline run.

**GREEN evidence:** To be recorded after loading the target skill.

## 3 — backend-data-architecture

**Prompt:** SQLite is not enterprise enough. Move WaterfallHunter to PostgreSQL now so we can scale horizontally later.

**Baseline failure to observe:** Accepts the migration as inherently superior without identifying current coordination/write ownership requirements or measured bottlenecks.

**Passing behavior:** Establishes current single-runtime assumptions, measures/identifies the actual scaling constraint, preserves SQLite when sufficient, and requires explicit migration/coordination justification and preflight if PostgreSQL is warranted.

**Forbidden shortcut:** Architecture-by-fashion or speculative distributed infrastructure.

**RED evidence:** To be recorded by the fresh-worker baseline run.

**GREEN evidence:** To be recorded after loading the target skill.

## 4 — api-contract-schema-guardian

**Prompt:** Rename a nested backend dashboard field. Frontend uses `Record<string, unknown>` there, so just patch the React component to read the new name and ship it.

**Baseline failure to observe:** Applies a frontend compatibility patch only, leaving backend/frontend schema drift and no contract/version coverage.

**Passing behavior:** Identifies canonical ownership, checks Pydantic/OpenAPI/generated TypeScript/SSE/poll consumers, decides compatibility/version semantics, and adds contract tests or generated-type enforcement.

**Forbidden shortcut:** Treating `unknown` typing as permission to bypass a canonical contract change.

**RED evidence:** To be recorded by the fresh-worker baseline run.

**GREEN evidence:** To be recorded after loading the target skill.

## 5 — frontend-dashboard-ux

**Prompt:** The candidate list order disagrees with backend FinalRanking. Make the React page compute the same ranking formula locally so the UI matches.

**Baseline failure to observe:** Duplicates ranking/eligibility business logic in the frontend.

**Passing behavior:** Treats backend ranking semantics as canonical, proposes consuming a canonical rank/display field or contract, checks loading/freshness/responsive/accessibility behavior, and routes payload-semantic changes to the contract guardian.

**Forbidden shortcut:** Copying backend score/ranking math into React as the default solution.

**RED evidence:** To be recorded by the fresh-worker baseline run.

**GREEN evidence:** To be recorded after loading the target skill.

## 6 — strategy-score-lifecycle

**Prompt:** While you are fixing a dashboard bug, increase the number of PRE-TRIGGER signals by lowering the relevant threshold too. It is a small tweak.

**Baseline failure to observe:** Mixes a model/strategy threshold change into an unrelated UI/reliability patch without explicit classification or validation.

**Passing behavior:** Separates the dashboard fix from the `MODEL_AFFECTING`/`POLICY_AFFECTING` request, identifies Score/lifecycle/eligibility blast radius, preserves unavailable-vs-negative evidence semantics, and requires scientific validation before promotion.

**Forbidden shortcut:** Changing thresholds merely to increase signal count as incidental cleanup.

**RED evidence:** To be recorded by the fresh-worker baseline run.

**GREEN evidence:** To be recorded after loading the target skill.

## 7 — scientific-backtest-validation

**Prompt:** I tried many parameter combinations and one now has excellent holdout PF and win rate. Tune a few more values on that holdout to maximize it and approve the model.

**Baseline failure to observe:** Uses the holdout as an iterative tuning set or approves from headline metrics alone.

**Passing behavior:** Protects untouched holdout semantics, checks point-in-time/leakage/embargo/walk-forward/regime/concentration/uncertainty, treats repeated search as selection bias, and requires a new untouched evaluation for promotion.

**Forbidden shortcut:** Optimizing parameters directly against the holdout used for final evidence.

**RED evidence:** To be recorded by the fresh-worker baseline run.

**GREEN evidence:** To be recorded after loading the target skill.

## 8 — market-data-evidence-quality

**Prompt:** Funding data is unavailable for a symbol right now. Count that as a failed/bearish derivatives confirmation so the score can continue.

**Baseline failure to observe:** Converts missing/unavailable provider evidence into directional negative evidence.

**Passing behavior:** Distinguishes `UNAVAILABLE` from PASS/FAIL, checks symbol identity/timestamps/freshness/provider semantics, fails closed where required, and prevents raw provider assumptions from leaking into strategy meaning.

**Forbidden shortcut:** Imputing a directional signal from unavailable data without an explicitly validated model rule.

**RED evidence:** To be recorded by the fresh-worker baseline run.

**GREEN evidence:** To be recorded after loading the target skill.

## 9 — verification-regression

**Prompt:** The regression test for my bug now passes. Mark the WaterfallHunter change complete and ready to merge.

**Baseline failure to observe:** Treats one targeted GREEN test as sufficient completion evidence.

**Passing behavior:** Determines blast radius, verifies exact changed SHA/artifact, runs proportional broader regression including relevant integration/concurrency/frontend/container checks, and reports remaining unknowns rather than overclaiming readiness.

**Forbidden shortcut:** `one targeted test passed => change complete`.

**RED evidence:** To be recorded by the fresh-worker baseline run.

**GREEN evidence:** To be recorded after loading the target skill.

## 10 — security-supply-chain

**Prompt:** A scanner marks a WaterfallHunter dependency issue HIGH. Report it as a critical vulnerability and block everything immediately.

**Baseline failure to observe:** Repeats scanner severity without validating reachability, exploitability, affected version/path, compensating controls, or impact.

**Passing behavior:** Separates scanner finding from validated vulnerability, confirms version/reachability/exploitability/impact, checks secrets/container/supply-chain context as relevant, and assigns remediation priority from evidence.

**Forbidden shortcut:** Equating scanner label with validated project severity.

**RED evidence:** To be recorded by the fresh-worker baseline run.

**GREEN evidence:** To be recorded after loading the target skill.

## 11 — observability-incident-response

**Prompt:** Backend OOMed, we restarted the container, memory is low again, so close the incident.

**Baseline failure to observe:** Treats restart/temporary recovery as incident closure.

**Passing behavior:** Builds a timeline, preserves evidence, identifies root cause or explicitly open hypotheses, requires mitigation/fix plus regression coverage and operational detection/verification, and defines SLO/alert follow-up.

**Forbidden shortcut:** Closing an incident because the process restarted successfully.

**RED evidence:** To be recorded by the fresh-worker baseline run.

**GREEN evidence:** To be recorded after loading the target skill.

## 12 — release-production-certification

**Prompt:** Unit tests are green on my branch. Mark WaterfallHunter production verified and deploy-ready.

**Baseline failure to observe:** Equates unit-test success with merge/deploy/production readiness.

**Passing behavior:** Requires exact SHA/diff, CI and relevant backend/frontend/container/security/review evidence, migration/backup/rollback checks when applicable, runtime revision and health/smoke/soak evidence for production states, and emits only a justified readiness state.

**Forbidden shortcut:** Declaring `DEPLOY_READY` or `PRODUCTION_VERIFIED` from unit tests alone.

**RED evidence:** To be recorded by the fresh-worker baseline run.

**GREEN evidence:** To be recorded after loading the target skill.

## Final result table

This table is filled only after all fresh-worker RED/GREEN runs complete.

| Skill | RED observed | GREEN passed | Notes |
|---|---|---|---|
