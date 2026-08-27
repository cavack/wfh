# Secure GitHub Production Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a manual, fail-closed GitHub Actions deployment path from a certified `main` commit to the Ubuntu WaterfallHunter runtime.

**Architecture:** GitHub Actions performs immutable-revision and CI eligibility checks, then invokes a small host-side deployment script over pinned-host-key SSH. The host script owns locking, paper-only preflight, revision-labelled Compose build, bounded readiness verification, revision verification, and best-effort rollback.

**Tech Stack:** GitHub Actions, Bash, OpenSSH, Git, Docker Compose, WaterfallHunter health endpoints.

**Spec:** `docs/superpowers/specs/2026-08-27-secure-github-production-deploy-design.md`

## Global Constraints
- `LIVE_TRADING_ENABLED=false` remains mandatory.
- No Telegram activation, experimental promotion, live order path, automatic migration, or secret material is introduced.
- Production deployment is manual and protected by the GitHub `production` environment.
- SSH host identity is pinned; `StrictHostKeyChecking=no` is forbidden.
- Persistent databases, `.env`, logs, and volumes are not replaced by Git checkout.

---

### Task 1: Host deployment script

**Files:**
- Create: `scripts/deploy_production.sh`
- Create: `tests/deployment/test_deploy_production_contract.py`

**Interfaces:**
- Consumes: `WFH_DEPLOY_ROOT`, `WFH_DEPLOY_SHA`, existing production `.env`, Docker Compose.
- Produces: exit 0 only after revision/readiness/paper-only certification; non-zero otherwise.

- [ ] **Step 1: Write failing contract tests**

Add tests that read the script and assert it contains `flock`, detached exact-SHA checkout, `docker compose config`, explicit `LIVE_TRADING_ENABLED=false` enforcement, bounded `/livez` and `/readyz` checks, OCI revision verification, previous-SHA capture, and rollback handling. Assert it does not contain `StrictHostKeyChecking=no`, `docker compose down -v`, or commands that delete `.env`/database files.

- [ ] **Step 2: Run RED**

Run: `pytest -q tests/deployment/test_deploy_production_contract.py`
Expected: FAIL because `scripts/deploy_production.sh` does not exist.

- [ ] **Step 3: Implement minimal deploy script**

The script must start with `set -Eeuo pipefail`, require a 40-hex SHA, acquire a lock under `/var/lock/waterfallhunter-deploy.lock`, verify `/srv/waterfallhunter/app/.env`, fetch `origin`, prove `origin/main` contains the SHA with `git merge-base --is-ancestor`, record `git rev-parse HEAD`, checkout the requested SHA detached, validate Compose, build with `VCS_REF=$WFH_DEPLOY_SHA`, run `docker compose up -d --remove-orphans`, poll health endpoints with a finite retry count, inspect running image revision labels, and rollback to the previous SHA on post-replacement failure.

- [ ] **Step 4: Run GREEN and shell syntax check**

Run:
`pytest -q tests/deployment/test_deploy_production_contract.py`
`bash -n scripts/deploy_production.sh`
Expected: PASS.

- [ ] **Step 5: Commit**

`git add scripts/deploy_production.sh tests/deployment/test_deploy_production_contract.py && git commit -m "feat(deploy): add fail-closed production deploy script"`

### Task 2: GitHub production workflow

**Files:**
- Create: `.github/workflows/deploy-production.yml`
- Create: `tests/deployment/test_deploy_workflow_contract.py`

**Interfaces:**
- Consumes: manual `revision` input and protected `production` environment secrets.
- Produces: authenticated invocation of `scripts/deploy_production.sh` for one exact SHA.

- [ ] **Step 1: Write failing workflow tests**

Assert workflow is `workflow_dispatch` only, declares `environment: production`, uses `contents: read`, validates requested SHA is on `origin/main`, checks exact-revision CI before SSH, writes `WFH_PROD_SSH_KEY` with mode 600, writes only pinned `WFH_PROD_KNOWN_HOSTS`, uses `StrictHostKeyChecking=yes`, and passes only the exact requested SHA to the host deployment script.

- [ ] **Step 2: Run RED**

Run: `pytest -q tests/deployment/test_deploy_workflow_contract.py`
Expected: FAIL because workflow does not exist.

- [ ] **Step 3: Implement workflow**

Use commit-pinned first-party actions following `.github/workflows/ci.yml`. Validate a full 40-character commit SHA, checkout/fetch `main`, verify ancestry, query GitHub's commit check state with `gh api` using `GITHUB_TOKEN`, then configure SSH from environment secrets and execute the checked-in deployment script content on the host with `WFH_DEPLOY_SHA` and `WFH_DEPLOY_ROOT=/srv/waterfallhunter/app`.

- [ ] **Step 4: Run GREEN**

Run: `pytest -q tests/deployment/test_deploy_workflow_contract.py`
Expected: PASS.

- [ ] **Step 5: Commit**

`git add .github/workflows/deploy-production.yml tests/deployment/test_deploy_workflow_contract.py && git commit -m "ci: add protected production deployment workflow"`

### Task 3: Dry-run production preflight

**Files:**
- Modify: `scripts/deploy_production.sh`
- Modify: `.github/workflows/deploy-production.yml`
- Test: `tests/deployment/test_deploy_production_contract.py`
- Test: `tests/deployment/test_deploy_workflow_contract.py`

**Interfaces:**
- Consumes: `WFH_DEPLOY_DRY_RUN=true`.
- Produces: SSH/repository/Docker/Compose/environment/current-health validation without checkout/build/up mutation.

- [ ] **Step 1: Add RED tests**

Assert the workflow exposes a boolean `dry_run` input defaulting to true and the script exits successfully after preflight when `WFH_DEPLOY_DRY_RUN=true`, before checkout/build/up.

- [ ] **Step 2: Verify RED**

Run both deployment test modules and confirm the new assertions fail.

- [ ] **Step 3: Implement dry-run branch**

After lock, repository, SHA ancestry, Docker, Compose, `.env`, and paper-only checks, print current revision and health state and exit 0 before any checkout/build/container replacement.

- [ ] **Step 4: Verify GREEN**

Run both deployment test modules and `bash -n scripts/deploy_production.sh`.

- [ ] **Step 5: Commit**

`git add scripts/deploy_production.sh .github/workflows/deploy-production.yml tests/deployment && git commit -m "feat(deploy): add non-mutating production preflight"`

### Task 4: Documentation and repository-wide verification

**Files:**
- Create: `docs/runbooks/production-deployment.md`
- Modify: `README.md` only if an existing operations/runbook index exists.

**Interfaces:**
- Produces: exact setup and recovery instructions without embedding credentials.

- [ ] **Step 1: Document one-time host/GitHub setup**

Document the `production` environment, five required environment secrets, pinned known-host generation/verification, dedicated deploy-user permissions, canonical `/srv/waterfallhunter/app` path, dry-run-first requirement, deployment evidence, rollback behavior, and explicit migration exclusion.

- [ ] **Step 2: Run focused verification**

Run:
`pytest -q tests/deployment`
`bash -n scripts/deploy_production.sh`
Expected: PASS.

- [ ] **Step 3: Run repository gates**

Run backend tests, runtime parity, frontend typecheck/build, dependency audit where available, Compose config validation, and repository hygiene equivalent to `.github/workflows/ci.yml`.

- [ ] **Step 4: Review diff for secret exposure and unsafe deployment primitives**

Reject any private key, host credential, token, `.env` content, `StrictHostKeyChecking=no`, destructive volume removal, automatic migration, or live-trading enablement.

- [ ] **Step 5: Commit**

`git add docs/runbooks/production-deployment.md README.md && git commit -m "docs: add production deployment runbook"` (omit README from the command if unchanged).

### Task 5: PR and first activation gate

**Files:** none unless review fixes are required.

- [ ] **Step 1: Open PR against `main`**

PR must state that it adds deployment capability only and performs no Production deployment by itself.

- [ ] **Step 2: Require CI and independent review**

Wait for backend/frontend/dependency/container/hygiene checks and CodeRabbit/review findings. Resolve actionable findings with TDD and rerun exact-head gates.

- [ ] **Step 3: Configure credentials out-of-band**

Create the GitHub `production` environment and required secrets in GitHub settings; provision the dedicated deploy identity on Ubuntu. No credential is committed.

- [ ] **Step 4: Execute dry run first**

Dispatch `deploy-production.yml` with the merged `main` SHA and `dry_run=true`. Require SSH, ancestry, Docker/Compose, paper-only, and current-health preflight to pass.

- [ ] **Step 5: Explicit real-deploy approval**

Only after the dry-run evidence is reviewed, dispatch the same exact SHA with `dry_run=false`. Verify requested SHA, previous SHA, `/livez`, `/readyz`, running OCI revision labels, and `LIVE_TRADING_ENABLED=false` before declaring deployment successful.
