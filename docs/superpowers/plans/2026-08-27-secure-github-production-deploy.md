# Automatic Signal-Only Production Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically deploy each CI-certified `main` revision to Ubuntu with database backup/migration and Telegram signal delivery activation while keeping WaterfallHunter strictly `SIGNAL_ONLY` and `LIVE_TRADING_ENABLED=false`.

**Architecture:** `CI` remains the exact-artifact validation gate. A `workflow_run` Production workflow binds to the successful `main` CI run's immutable SHA and invokes a host-side locked deployment script over pinned-host-key SSH. The script performs backup-before-migration, managed migration preflight/apply/postflight, release-scoped Telegram cutover, Compose build/update, readiness/revision certification, and bounded rollback behavior.

**Tech Stack:** GitHub Actions, Bash, OpenSSH, Git, Docker Compose, SQLite backup/migration CLI, FastAPI health endpoints.

**Spec:** `docs/superpowers/specs/2026-08-27-secure-github-production-deploy-design.md`

## Global Constraints
- Product/runtime boundary is `SIGNAL_ONLY`.
- `LIVE_TRADING_ENABLED=false` is mandatory; no order execution path is enabled.
- Production deploy triggers only from successful `CI` `workflow_run` events for `main`.
- No `workflow_dispatch` or dry-run path.
- Database backup must complete before migration apply.
- Telegram delivery is enabled with a release timestamp cutover; credentials remain host-owned.
- SSH uses pinned known-host verification; `StrictHostKeyChecking=no` is forbidden.
- Persistent volumes are never deleted/recreated by deploy.

---

### Task 1: Lock canonical SIGNAL_ONLY terminology

**Files:**
- Modify: `backend/src/waterfallhunter/core/contracts.py`
- Modify: product/runtime consumers and tests that reference `ExecutionMode.PAPER_ONLY`
- Modify: user-facing frontend/config/docs copy containing `PAPER_ONLY`, `paper-only`, or `paper trading`
- Create: `backend/tests/test_signal_only_terminology.py`

**Interfaces:**
- Produces: `ExecutionMode.SIGNAL_ONLY = "SIGNAL_ONLY"` and no product/runtime API response emits `PAPER_ONLY`.

- [ ] **Step 1: Add failing contract/terminology tests**

Assert `ExecutionMode.SIGNAL_ONLY.value == "SIGNAL_ONLY"`, SignalDecision defaults to `SIGNAL_ONLY`, and repository product/runtime source contains none of the deprecated terms (`PAPER_ONLY`, `paper-only`, `paper trading`) outside explicitly grandfathered historical quotation fixtures if any are unavoidable.

- [ ] **Step 2: Run RED**

Run focused canonical-contract/config/backtest/deployment-certification tests and verify failure on the old `PAPER_ONLY` contract.

- [ ] **Step 3: Implement minimal terminology migration**

Rename the enum/default/literals and update affected runtime consumers, frontend labels, Compose/config comments, runbooks, and current design/plan text. Keep `LIVE_TRADING_ENABLED=false` and no order placement behavior unchanged.

- [ ] **Step 4: Run GREEN**

Run the focused suites plus repository terminology scan.

### Task 2: Deployment contract tests — RED

**Files:**
- Create: `backend/tests/test_production_deployment_contract.py`

**Interfaces:**
- Tests future files `.github/workflows/deploy-production.yml` and `scripts/deploy_production.sh` before they exist.

- [ ] **Step 1: Assert automatic workflow contract**

Test that the workflow uses `workflow_run` for workflow `CI`, filters branch `main`, has a success conclusion guard, has no `workflow_dispatch`, uses `environment: production`, and passes `${{ github.event.workflow_run.head_sha }}` as the only deployment SHA.

- [ ] **Step 2: Assert SSH and mutation safety**

Require pinned `known_hosts`, `StrictHostKeyChecking=yes`, no runtime `ssh-keyscan`, no `docker compose down -v`, no plaintext secret values, and no `LIVE_TRADING_ENABLED=true`.

- [ ] **Step 3: Assert deploy-script ordering contract**

Require lock → exact SHA ancestry → Compose/live-trading invariant → image build → SQLite backup → migration preflight → migration apply → Telegram cutover update → Compose up → `/livez` → `/readyz` → OCI revision verification.

- [ ] **Step 4: Verify RED in CI**

Open/update the PR with test-only commit and confirm focused/backend CI fails because production workflow/script are missing.

### Task 3: Host automatic deployment implementation — GREEN

**Files:**
- Create: `scripts/deploy_production.sh`
- Modify: `backend/tests/test_production_deployment_contract.py`

**Interfaces:**
- Consumes: `WFH_DEPLOY_SHA`, `WFH_DEPLOY_ROOT=/srv/waterfallhunter/app` and existing host `.env`.
- Produces: certified deployment or non-zero exit; never enables live trading.

- [ ] **Step 1: Implement strict boundary and locking**

Use `set -Eeuo pipefail`; validate 40-hex SHA; acquire exclusive `flock`; fetch origin and require `git merge-base --is-ancestor "$WFH_DEPLOY_SHA" origin/main`; require `.env`; reject any effective `LIVE_TRADING_ENABLED` value other than false.

- [ ] **Step 2: Build target artifacts before database mutation**

Checkout detached target SHA and build backend/frontend/watchdog with `VCS_REF=$WFH_DEPLOY_SHA` and bounded build failure behavior.

- [ ] **Step 3: Backup Production SQLite before migration**

Use the target backend image with the persistent `waterfall_data` volume mounted and Python/SQLite backup API (or repository backup tooling) to create a timestamped backup outside the live DB file, verify integrity/checksum, and abort if backup certification fails.

- [ ] **Step 4: Run managed migration**

Against `/app/data/waterfall_registry.db`, execute target artifact `python -m waterfallhunter.migrate_database --preflight`, then `--apply --source-revision "$WFH_DEPLOY_SHA"`; require JSON success and postflight managed schema verification.

- [ ] **Step 5: Enable Telegram signal delivery with current release cutover**

Require existing non-empty `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID`; update only `TELEGRAM_SIGNAL_DELIVERY_ENABLED=true` and `TELEGRAM_SIGNAL_DELIVERY_CUTOVER_AT=<deployment_epoch>` in `.env`, preserving a pre-deploy `.env` backup for rollback.

- [ ] **Step 6: Start and certify runtime**

Run `docker compose up -d --remove-orphans`; poll `/api/livez` and `/api/readyz` with bounded retries; inspect backend/frontend/watchdog OCI revision labels and require the exact target SHA; verify `LIVE_TRADING_ENABLED=false` inside effective runtime config.

- [ ] **Step 7: Rollback rules**

On failure, restore previous Telegram settings. If migration was not applied, checkout/rebuild previous SHA. If migration was applied, only source/container rollback when previous runtime schema compatibility is positively verified; otherwise stop and preserve backup/evidence rather than guessing.

- [ ] **Step 8: Run GREEN**

Run deployment contract tests and `bash -n scripts/deploy_production.sh`.

### Task 4: Automatic GitHub Actions workflow — GREEN

**Files:**
- Create: `.github/workflows/deploy-production.yml`
- Modify: `backend/tests/test_production_deployment_contract.py`

**Interfaces:**
- Consumes: successful `CI` `workflow_run` on `main` and Production environment SSH secrets.
- Produces: one deployment of exactly `workflow_run.head_sha`.

- [ ] **Step 1: Add workflow trigger and guards**

Use `on.workflow_run.workflows: [CI]`, `types: [completed]`, branch `main`, and job condition `github.event.workflow_run.conclusion == 'success'`.

- [ ] **Step 2: Configure least privilege and concurrency**

Set `permissions: contents: read`; `environment: production`; Production concurrency with `cancel-in-progress: false` so deployments serialize rather than interrupt each other.

- [ ] **Step 3: Configure pinned SSH**

Write private key mode 600 and exact `WFH_PROD_KNOWN_HOSTS`; use `StrictHostKeyChecking=yes` and `UserKnownHostsFile=...`; never use runtime `ssh-keyscan`.

- [ ] **Step 4: Execute exact target script**

Checkout the exact `workflow_run.head_sha` locally and stream that revision's `scripts/deploy_production.sh` over SSH with `WFH_DEPLOY_SHA` fixed to the same SHA. Do not deploy `HEAD`, branch names, or caller input.

- [ ] **Step 5: Run GREEN**

Focused tests must pass and workflow syntax must be valid.

### Task 5: Deployment/notification runbook

**Files:**
- Create: `docs/operations/automatic-production-deployment.md`
- Modify: `.env.example`
- Modify: `docker-compose.yml` comments/copy as needed

**Interfaces:**
- Produces: setup/recovery instructions and canonical SIGNAL_ONLY wording.

- [ ] **Step 1: Document Production environment setup**

Document the five GitHub SSH secrets, deploy-user permissions, canonical application path, Docker volume assumptions, host-owned Telegram credentials, and known-host fingerprint verification.

- [ ] **Step 2: Document automatic migration and rollback boundaries**

Describe backup-before-migration, migration CLI, incompatible-schema stop condition, backup location/verification, and manual recovery procedure.

- [ ] **Step 3: Document Telegram cutover**

Explain automatic `TELEGRAM_SIGNAL_DELIVERY_ENABLED=true` and release timestamp cutover, with explicit statement that Telegram sends signals only and never authorizes orders.

- [ ] **Step 4: Normalize SIGNAL_ONLY copy**

Update current product/runtime docs/config/UI references from paper-trading boundary language to signal-only language without claiming that historical simulation/backtest mechanics are live execution.

### Task 6: Full validation and review

**Files:** review fixes only.

- [ ] **Step 1: Run backend suite and runtime parity**

Require full backend GREEN with `LIVE_TRADING_ENABLED=false`.

- [ ] **Step 2: Run frontend typecheck/build/tests**

Require all available frontend gates GREEN.

- [ ] **Step 3: Run container/dependency/hygiene gates**

Match `.github/workflows/ci.yml`, including exact artifact family validation and credential-pattern scan.

- [ ] **Step 4: Review automatic-deploy attack/failure paths**

Confirm no arbitrary revision input, no PR-triggered Production deploy, no host-key bypass, no destructive volume command, no credentials in source, no live-trading enablement, and no Telegram backlog release before the deployment cutover.

- [ ] **Step 5: CodeRabbit/review closure**

Resolve actionable findings with RED→GREEN changes and rerun exact-head checks.

### Task 7: Merge and automatic activation

- [ ] Merge only after all required CI/review gates are green and Production environment secrets/host deploy account are provisioned.
- [ ] The merge-to-main CI run must complete successfully.
- [ ] Confirm `deploy-production` starts automatically from that successful CI run without manual dispatch.
- [ ] Verify deployment evidence: exact SHA, DB backup/checksum, migration result, Telegram cutover, `/livez`, `/readyz`, OCI labels, `LIVE_TRADING_ENABLED=false`, and `SIGNAL_ONLY` runtime/product boundary.
