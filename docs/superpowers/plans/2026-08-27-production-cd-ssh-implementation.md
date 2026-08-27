# Guarded GitHub-to-Ubuntu CD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a manually authorized GitHub Actions path that deploys an exact CI-green `main` SHA to the Ubuntu Docker Compose host with read-only schema preflight, bounded health verification, and automatic application rollback.

**Architecture:** GitHub Actions verifies the requested revision and successful CI, then connects over pinned-host-key OpenSSH to the configured Production host. A first-party Python orchestrator performs remote revision/env/image preflight, builds the exact source revision, runs migration preflight only, cuts over the three application services, verifies health/revision labels, and restores previous images/revision on failure.

**Tech Stack:** GitHub Actions, OpenSSH, Python 3 standard library, Git, Docker Compose, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-production-cd-ssh-design.md`

## Global Constraints

- `LIVE_TRADING_ENABLED=false` remains mandatory.
- This implementation must not run Production migration `--apply`.
- This implementation must not enable Telegram delivery or live trading.
- No automatic deploy-on-merge; trigger remains `workflow_dispatch`.
- SSH host-key checking must remain strict and use pinned known-host material.
- Deployment must require an exact current `origin/main` SHA with a successful CI push run.
- Any post-cutover failure must attempt application rollback and still return non-zero.

---

### Task 1: Add reusable safe remote Compose deployment skill

**Files:**
- Create: `.agents/skills/safe-remote-compose-deployment/SKILL.md`

**Interfaces:**
- Consumes: remote Git/Compose deployment tasks.
- Produces: reusable agent guidance for exact-revision, preflight, cutover, verification, rollback, and secret-handling decisions.

- [ ] **Step 1:** Write the concise `SKILL.md` with `name`/`description` frontmatter and the invariants from the design.
- [ ] **Step 2:** Self-check that the description contains only triggering conditions and that the body forbids host-key bypass, secret printing, implicit migration, and unverified cutover.
- [ ] **Step 3:** Commit as `docs: add safe remote compose deployment skill`.

### Task 2: Establish RED tests for the remote deployment orchestrator

**Files:**
- Create: `backend/tests/test_deploy_production_script.py`

**Interfaces:**
- Expected production module: `scripts.deploy_production`.
- Expected entry point: `deploy(target_sha: str, repo_dir: Path, runner: CommandRunner, health_timeout_seconds: int = 120) -> DeploymentResult`.
- Expected exception: `DeploymentError`.

- [ ] **Step 1:** Write tests for invalid SHA, dirty worktree, target-not-main, unsafe/missing `.env`, command ordering, preflight failure rollback, post-cutover rollback, and successful verification.
- [ ] **Step 2:** Run `PYTHONPATH=backend/src:. pytest -q backend/tests/test_deploy_production_script.py`.
- [ ] **Step 3:** Verify RED is caused only by missing `scripts.deploy_production`.
- [ ] **Step 4:** Commit as `test: define guarded production deploy contract`.

### Task 3: Implement the deployment orchestrator GREEN

**Files:**
- Create: `scripts/deploy_production.py`
- Test: `backend/tests/test_deploy_production_script.py`

**Interfaces:**
- `DeploymentError(RuntimeError)`.
- `CommandResult(returncode: int, stdout: str, stderr: str)`.
- `CommandRunner.run(args: Sequence[str], *, cwd: Path, check: bool = True) -> CommandResult`.
- `DeploymentResult(target_sha: str, previous_sha: str, rolled_back: bool, backend_image_id: str, frontend_image_id: str, watchdog_image_id: str)`.
- `deploy(...) -> DeploymentResult`.

- [ ] **Step 1:** Implement SHA/path/env parsing and exact-main/worktree preconditions.
- [ ] **Step 2:** Implement previous image capture/tag restoration helpers without printing secret material.
- [ ] **Step 3:** Implement checkout, Compose validation/build, and target-backend migration `--preflight` only.
- [ ] **Step 4:** Implement three-service cutover, bounded Docker-health polling, OCI revision-label checks, and backend/frontend smoke checks.
- [ ] **Step 5:** Implement rollback that restores canonical image tags + previous Git revision and restarts old application services when cutover occurred.
- [ ] **Step 6:** Add CLI `--target-sha`, `--repo-dir`, `--health-timeout-seconds` using only stdlib `argparse`.
- [ ] **Step 7:** Run the focused test and require GREEN.
- [ ] **Step 8:** Commit as `feat: add rollback-safe production deploy orchestrator`.

### Task 4: Establish RED workflow security contract

**Files:**
- Create: `backend/tests/test_production_deploy_workflow.py`

**Interfaces:**
- Expected workflow path: `.github/workflows/deploy-production.yml`.

- [ ] **Step 1:** Write text-level contract assertions requiring `workflow_dispatch`, `target_sha`, `DEPLOY_PAPER_ONLY`, `environment: production`, `contents: read`, `actions: read`, strict known-host checking, SSH secret names, concurrency, and absence of both `StrictHostKeyChecking=no` and migration `--apply`.
- [ ] **Step 2:** Run `PYTHONPATH=backend/src:. pytest -q backend/tests/test_production_deploy_workflow.py`.
- [ ] **Step 3:** Verify RED is caused by the missing workflow file.
- [ ] **Step 4:** Commit as `test: define production deploy workflow guardrails`.

### Task 5: Implement guarded GitHub Actions deployment workflow

**Files:**
- Create: `.github/workflows/deploy-production.yml`
- Test: `backend/tests/test_production_deploy_workflow.py`

**Interfaces:**
- Inputs: `target_sha`, `confirm`.
- Secrets: `WFH_DEPLOY_HOST`, `WFH_DEPLOY_USER`, `WFH_DEPLOY_PORT`, `WFH_DEPLOY_PATH`, `WFH_DEPLOY_SSH_KEY`, `WFH_DEPLOY_KNOWN_HOSTS`.
- Remote entry point: `python3 scripts/deploy_production.py --target-sha <sha> --repo-dir <path>`.

- [ ] **Step 1:** Add manual-only workflow with read-only permissions and single-deployment concurrency.
- [ ] **Step 2:** Validate confirmation token, SHA syntax, exact current `origin/main`, and a successful CI push run for the SHA through GitHub API/`gh`.
- [ ] **Step 3:** Install SSH key/known-host material with restrictive permissions and reject missing/unsafe deploy parameters.
- [ ] **Step 4:** Connect with `StrictHostKeyChecking=yes`, fetch exact `main`, and invoke the target revision's deployment orchestrator.
- [ ] **Step 5:** Run the workflow contract test and require GREEN.
- [ ] **Step 6:** Commit as `ci: add guarded production deployment workflow`.

### Task 6: Add operator setup/runbook documentation

**Files:**
- Create: `docs/operations/github-production-deployment.md`
- Modify: `docs/operations/release-v7-production.md`

**Interfaces:**
- Documents exact secret names, GitHub `production` environment protection, remote checkout prerequisites, manual dispatch procedure, schema-migration separation, health/rollback behavior, and failure recovery.

- [ ] **Step 1:** Document setup without embedding real host/IP/key values.
- [ ] **Step 2:** State explicitly that workflow readiness is not migration/deployment authority and that Production migration remains the existing separate certification path.
- [ ] **Step 3:** Link the release document to the new runbook.
- [ ] **Step 4:** Commit as `docs: document guarded GitHub production deployment`.

### Task 7: Full verification and PR

**Files:**
- No new production files unless verification exposes a defect.

- [ ] **Step 1:** Run focused deployment/workflow tests.
- [ ] **Step 2:** Run full backend suite with `LIVE_TRADING_ENABLED=false`.
- [ ] **Step 3:** Run frontend typecheck/build.
- [ ] **Step 4:** Run `docker compose config --quiet` and existing container-validation parity through GitHub CI.
- [ ] **Step 5:** Run dependency audit and repository hygiene through GitHub CI.
- [ ] **Step 6:** Open a Draft PR to `main`, inspect CodeRabbit/review threads, and fix actionable findings with RED→GREEN where behavioral.
- [ ] **Step 7:** Do not merge or dispatch the Production workflow until CI/review is green and a separate Production deployment request is explicit.