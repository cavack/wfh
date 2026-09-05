# WaterfallHunter — Unified Master Plan

Status: MASTER DESIGN — supersedes the fragmented 2026-09-03 dashboard-only design/plan
Date: 2026-09-03
Canonical repository: `cavack/wfh`
Current design baseline: `209fff11e434dda58d3e380f181f23a111813cc2`
DR repository: `cavack/wfh-dr` (private)
Production execution policy: SIGNAL_ONLY / no live order placement

## 1. Mission

Turn WaterfallHunter into one coherent, professional system that is:

- operationally stable enough to evaluate the full candidate universe on time;
- capable of producing a useful quantity of short signals without hiding runtime defects;
- progressively calibrated from high-recall to higher-quality profiles;
- scientifically measurable through continuous paper outcomes and immutable provenance;
- presented through an institutional English-first Decision Terminal;
- maintainable through explicit repository/backend/frontend ownership boundaries;
- recoverable through a separate encrypted off-host DR vault.

This document is the single master design. Older narrower plans are subordinate to it.
## 2. Evidence taxonomy and current control-plane facts

`VERIFIED_FACT`: `wfh/main` is currently `209fff11e434dda58d3e380f181f23a111813cc2` and protected by required backend, frontend, dependency-audit, container-validation, and repository-hygiene checks.

`VERIFIED_FACT`: repository governance standardization from PR #118 is already merged. Do not redo it as backlog.

`VERIFIED_FACT`: host ↔ GitHub connectivity is already operational through authenticated HTTPS for writes, a repo-specific read-only SSH fallback, and GitHub Actions → Production SSH deployment.

`VERIFIED_FACT`: the runtime uses systemd orchestration plus Docker `restart: unless-stopped` and a periodic health-recovery timer; simple `Restart=always` on the oneshot wrapper is not the correct design.

`VERIFIED_FACT`: PR #117 is the active dashboard/runtime correction branch and must be reconciled before overlapping implementation.

`REPRODUCED_DEFECT`: the observed production universe has suffered a throughput/freshness capacity mismatch, with many candidates older than the 180-second analysis target and no `ENTRY_READY` at the incident snapshot.

`REPRODUCED_DEFECT`: the former full-state dashboard stream sent multi-megabyte snapshots repeatedly; PR #117 reduces that path through a bounded projection and on-demand raw diagnostics.

`DEBT`: `backend/src/waterfallhunter/main.py` remains a multi-responsibility orchestration module above four thousand lines. Size alone is not treated as a correctness defect.

`PROPOSAL`: use progressive tightening for model quality gates while preserving engineering/data/safety gates.
## 3. Senior recheck ledger — corrections to earlier assumptions

This section is normative: older chat conclusions are superseded where they conflict with these rechecks.

### 3.1 Repository and host connectivity

`VERIFIED_FACT`: HTTPS authenticated write access from the host is working. A fresh `git push --dry-run` succeeded and the synthetic ref was confirmed absent afterward.

`VERIFIED_FACT`: the repository-specific `github-ssh` fallback authenticates successfully and resolves the same current `main` SHA as HTTPS. It remains a read-oriented fallback; HTTPS/`gh` is the normal write path.

`VERIFIED_FACT`: Production checkout is detached at `1e71b92ca3ba32c55ab6d8ab5de7ce93473c0a69`; GitHub `main` is `209fff11e434dda58d3e380f181f23a111813cc2`. The intervening main commit is repository-governance documentation, not a runtime/model change.

### 3.2 Repository governance

`VERIFIED_FACT`: GitHub Community Health reports 100%. README, LICENSE, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, PR template, CODEOWNERS, issue forms, Dependabot and repository governance documentation are present.

`VERIFIED_FACT`: `main` requires backend, frontend, dependency-audit, container-validation and repository-hygiene checks; force pushes and deletion are disabled; linear history and conversation resolution are required; admin enforcement is enabled.

`VERIFIED_FACT`: Private Vulnerability Reporting, Dependabot security updates, secret scanning and push protection are enabled.

`POLICY_NOTE`: required approving review count is currently zero. In the present single-owner workflow this avoids an impossible human-approval gate. If another maintainer is added, require at least one independent/code-owner approval as a separate repository-policy change.

### 3.3 Runtime recovery

`VERIFIED_FACT`: the six Compose services are currently healthy. Alertmanager uses the Compose-generated name `waterfallhunter-alertmanager-1`, so a prefix-only `waterfall-*` inventory previously under-counted it.

`VERIFIED_FACT`: `waterfallhunter.service` is intentionally `Type=oneshot`; Docker services use `restart: unless-stopped`.

`VERIFIED_FACT`: the minute health-recovery timer has a bounded recovery policy: three consecutive failures before recovery, a 600-second cooldown, and no more than three recoveries per hour.

`CORRECTION`: the system does have bounded recovery for crashes and health-endpoint-detectable hangs. The unresolved gap is semantic liveness when the API remains responsive while universe freshness/backlog is outside the operational SLO.

### 3.4 Current production freshness

A fresh read-only sample on 2026-09-03 reproduced the capacity problem:

- 160 tracked candidates;
- 107 `LATE`, 53 `NO_TRADE`, 0 `ENTRY_READY`;
- 106/160 analysis ages above 180 seconds;
- median analysis age about 1117.7 seconds; max about 4151.7 seconds;
- `/api/candidates` response about 2,487,952 bytes and about 10.688 seconds for the sampled request;
- backend resource snapshot about 90.8% CPU and 1.814 GiB / 2 GiB memory.

`REPRODUCED_DEFECT`: `/api/health` simultaneously reported `status=healthy` and near-zero `hunter_progress_age_seconds`, despite the majority of the universe violating the 180-second candidate-freshness target. Progress of some work is therefore not equivalent to universe freshness.

With approximately 27 seconds/evaluation and concurrency 12, the theoretical best-case throughput is about 26.7 evaluations/minute and a 160-symbol full pass is about six minutes. Maintaining a three-minute maximum age for all 160 candidates would require roughly 53.3 evaluations/minute (equivalent to concurrency ~24 at the same service time), which is unsafe to obtain by simply doubling concurrency under the current memory/CPU pressure.

### 3.5 PR #117

`VERIFIED_FACT`: PR #117 is open, mergeable, and its exact head is `59834fa0e56c4707ebd9b482a0f2965bc697cdd5`.

`CORRECTION`: green CI does not make #117 merge-ready. Five current, non-outdated review threads remain unresolved:

1. P1 — stalled SSE fallback can keep receiving a retained live-client cache unless the stalled EventSource is retired or polling forces bounded refresh;
2. P1 — recent-transition query can become approximately quadratic on long same-decision tails;
3. P2 — WebSocket order-book evidence can expire while awaiting REST trades and must be revalidated/refreshed;
4. P2 — raw diagnostics can remain permanently cached/stale after first load;
5. P2 — raw all-candidate aggregation is synchronous inside an async handler and can block the event loop.

These five findings are mandatory RED→GREEN work before #117 may be called `MERGE_READY`.

`VERIFIED_FACT`: every file changed by PR #104 is also in PR #117 and #117 explicitly includes the safe observational technical reference-plan behavior. PR #104 is therefore a supersession candidate, but close it only after #117 lands successfully.

### 3.6 Dirty and historical work

`VERIFIED_FACT`: active unpublished work exists and must be preserved before cleanup:

- `mission-continuity-v1-20260902`: four modified files, +108 lines locally beyond the published PR head;
- `fix-decision-freshness-plan-20260902`: nine tracked files modified plus five untracked source/test files; approximately +308/-24 tracked diff;
- `reference-plan-ui-20260902`: code clean but has untracked frontend test results.

`DEBT`: local branch `main` is currently checked out by stale worktree `watch-fairness-20260902` at `bf90a704...`, five commits behind `origin/main`. It does not change Production, but it is an operator-confusion hazard and must be reconciled/removed after preserving anything needed.

No dirty worktree may be deleted as part of general cleanup until its patch/untracked-source inventory is durably captured and dispositioned.
## 4. Repository, GitHub, Actions, and Host Hygiene

This phase is mandatory, evidence-gated, and non-destructive by default. Cleanup means reducing obsolete state while preserving provenance, rollback, research evidence, and all non-WaterfallHunter host data.

### 4.1 Current inventory

`VERIFIED_FACT`: GitHub currently has 30 open PRs, 6 open non-PR issues, 88 branches, and 27 active workflows.

`DEBT`: the active workflow set contains multiple clearly historical/temporary names (`Temporary`, `one-shot`, `tmp-*`, Wave patchers). Naming alone does not authorize deletion; each workflow must first be checked for current references, scheduled/manual use, unique evidence, and replacement coverage.

`VERIFIED_FACT`: the most recent 100 Actions runs contain 33 failures. Historical failed runs are evidence, not garbage by default; deletion/retention is governed separately from workflow-source cleanup.

`VERIFIED_FACT`: project-scoped disk inventory is approximately 4.8 GiB under `/srv/wfh-worktrees` and 13 GiB under `/srv/waterfallhunter/runtime`.

Large cleanup candidates include old release/recovery copies and test/evidence worktrees, but size alone is never sufficient deletion evidence.
### 4.2 GitHub cleanup contract

Every open Issue and PR is reconciled against current `main`, current open work, and unique commits before disposition. Allowed dispositions are `KEEP_ACTIVE`, `MERGE_CANDIDATE`, `SUPERSEDED_CLOSE`, `DEPENDABOT_DECIDE`, or `HISTORICAL_CLOSE`.

Closing a PR/Issue requires a short evidence comment naming the superseding PR/commit or why no remaining work is unique. Do not delete discussion history.

Remote branches may be deleted only after their PR is merged/closed, `git cherry`/compare proves no required unique work remains, no host worktree has unpublished changes tied to the branch, and no release/DR process references it.

Temporary/one-shot workflow files may be removed or disabled only after proving the canonical CI/deploy/security workflow supersedes them. Keep CI, guarded Production deploy, required security/dependency checks, and any still-used scheduled workflow.

Actions artifacts/runs use a retention policy, not ad-hoc deletion: preserve release/DR/security/migration evidence required for audit and rollback; shorten retention for reproducible build/test artifacts only after their authoritative replacement is established.

Repository labels, templates, environments, secrets, topics, releases, Dependabot PRs, merge settings, rules/protection, and stale branches are included in the audit. Secret values are never printed; an obsolete secret/environment is removed only after zero live workflow references are proven.
### 4.3 Host cleanup allowlist and hard denylist

Cleanup is restricted to explicit WaterfallHunter-owned roots. The default cleanup allowlist is `/srv/wfh-worktrees` plus individually classified generated artifacts under `/srv/waterfallhunter/runtime`.

`/srv/waterfallhunter/app` is the canonical Production checkout and is not a bulk-cleanup target. It may receive only normal Git/release-managed changes after exact revision verification.

Hard `DO_NOT_TOUCH` paths include `/root/.vscode-server`, `/root/.vscode-server-insiders`, `/root/.ssh`, `/etc`, `/usr`, `/bin`, `/sbin`, `/lib*`, `/boot`, `/home` content unrelated to WFH, and direct files under `/var/lib/docker`. No generic system cleanup or package/cache purge belongs to this mission.

Never run broad `rm -rf /srv/*`, `docker system prune`, filesystem-level Docker deletion, or wildcard deletion spanning unclassified paths. Docker cleanup uses the Docker CLI and only project-scoped objects proven unreferenced.

The Production `waterfall_data` volume is critical and never deleted by hygiene work. Grafana, Prometheus, and Alertmanager volumes are also preserved unless a separately approved backup/recreate operation explicitly owns them.
### 4.4 Deletion barrier

Before removing any host worktree/artifact, generate a dry-run inventory containing path, bytes, Git SHA/branch where applicable, dirty/untracked status, remote-push status, owning PR/issue, runtime/reference use, proposed disposition, and rollback/recovery source.

A worktree is removable only when it is clean or its unique patch is durably preserved, no live PR/mission needs it, no process has it as a working directory, and Git confirms its branch/commit is recoverable remotely or intentionally archived.

A runtime artifact is removable only when it is reproducible or superseded, is not the current/previous certified rollback target, is not the only DR/migration/research evidence, and is not referenced by an active override, lock, service, workflow, or certification record.

For Docker images, preserve all running image IDs plus at least the current certified rollback image set. Remove only unreferenced older project-tagged images after checking containers and release overrides. Never prune project volumes as image cleanup.

After each cleanup batch: re-run `git worktree list`, repository/branch inventory, Docker service health, `/livez`/`/readyz`/`/healthz`, dashboard smoke, disk usage, and recovery state. Cleanup is complete only when behavior and rollback ability remain unchanged.
## 5. Runtime-first ordering

The model is not recalibrated while Production freshness is materially outside its evidence contract. A stale universe can distort both apparent signal scarcity and false-negative analysis.

`PROPOSAL`: Phase 1 first closes PR #117's five current review findings; Phase 2 then proves an attainable universe-freshness SLO under bounded resource use. Only after trustworthy point-in-time evidence is restored may strategy promotion analysis proceed.

The health model must distinguish process liveness, endpoint readiness, hunter progress, universe freshness and provider quality. An HTTP-successful `/api/health` is insufficient when most candidates exceed the analysis-age SLO.

Concurrency is a controlled variable, not the default fix. Any increase requires measured per-evaluation memory/CPU/service-time headroom and a soak demonstrating bounded RSS and queue behavior.

## 6. Dashboard target architecture

The UI is English-first and institutional in tone. Current release remains single-language, but shell/layout primitives must not block future locale/RTL support.

Four product workspaces are canonical: `Decision`, `Candidates`, `Research & Lab`, and `Operations`.

`Decision` answers what is actionable now and why. `Candidates` exposes the canonical server ordering plus exploration filters. `Research & Lab` owns backtest/replay/outcomes/raw diagnostics. `Operations` owns system/provider/freshness/revision/DR health.

Only canonical backend contracts determine ordering, decision, eligibility, evidence meaning and trade-plan authority. Client code may filter/search/display but must not recreate ScoreV2/ENTRY_READY/lifecycle/Anti-Chase formulas.
## 7. Progressive model-tightening contract

The latest owner decision supersedes a strict-first calibration posture. Development starts from the easiest scientifically defensible quality profile to maximize observed signal recall, then tightens progressively to improve quality.

This does **not** authorize weakening evidence-integrity or execution-safety gates. Stale/invalid data, corrupted provenance, invalid lifecycle, extreme Anti-Chase, unusable execution and required safety-plan failures stay fail-closed.

Three versioned challenger tiers are computed from the same causal evidence: `RECALL`, `BALANCED`, `PRECISION`. Production keeps one separately promoted champion; the three challengers remain research/shadow until validated.

Tier differences may include entry-readiness threshold, component weights, quality/confirmation gates, K-of-N topology and coverage/timing thresholds. Every difference is explicit in versioned policy metadata.

Tightening should be monotonic where feasible: BALANCED explains which RECALL cases it rejects; PRECISION explains which BALANCED cases it rejects. This supports gate-contribution and false-positive/false-negative analysis without redesigning the model later.

No tier may convert `UNAVAILABLE` into bearish evidence. No frontend tier formula exists.

Promotion requires purged/embargoed walk-forward selection, realistic costs, untouched final evaluation, uncertainty/concentration/regime checks and parameter-neighborhood stability.

## 8. Continuous paper/self-improvement semantics

The desired self-improvement loop is implemented as automated evidence generation and challenger proposal, not autonomous mutation of Production policy.

Every durable canonical/challenger signal can feed a deterministic paper portfolio with configurable starting capital, fees/slippage/funding, position capacity and outcome attribution. It never places real orders.

Automated analysis may identify rejected winners, accepted losers, gate contribution, weight/threshold sensitivity and propose a new immutable challenger policy version. Scientific validation remains the promotion boundary.
## 9. AI, Telegram, and recovery semantics

AI Advisor remains advisory-only. Product and Operations surfaces must expose whether it is configured, reachable, current and failing, while keeping credentials secret. AI output cannot create or veto canonical deterministic signals unless repository policy is separately redesigned.

Telegram interactive capability and proactive signal delivery are separate. Durable signal delivery stays default-off until explicit enablement; implementation work must preserve persistence-before-notification, cutover, retry, rate-limit and dead-letter semantics.

The existing recovery stack is retained: systemd oneshot orchestration, Docker `unless-stopped`, and bounded periodic recovery. New work targets semantic liveness that can remain HTTP-healthy while universe freshness is degraded; a second independent restart supervisor is not introduced.

## 10. DR repository role and provenance

`cavack/wfh-dr` is a private off-host Disaster Recovery vault, not a development mirror and not a source of application truth.

Current encrypted Release assets prove chunk/ciphertext/plaintext integrity and support independent restore, while the current bundle manifest itself does not bind source Git/runtime revision or SQLite logical audit identity.

`PROPOSAL`: evolve provenance so the remotely retained certification/manifest chain binds exact Production revision, backup timestamps, SQLite schema/user version, schema/logical-content hash and table/object counts in addition to AES-256-GCM/chunk hashes.

The latest DR Release is not called restore-certified merely because it exists. Each certified Release must be tied to an exact restore workflow run/report for that tag.

Branch protection is currently unavailable for the private DR repository under the present GitHub plan. Treat this as a platform limitation and compensate with minimal code surface, explicit workflow verification, immutable Releases and independently checked restore evidence.

## 11. Acceptance philosophy

Completion is evidence-based, not checklist theater. Each phase is re-opened from fresh current state after implementation: current SHA, diff, remote PR/issues, tests, review threads, runtime behavior and failure modes are all rechecked.

A previous PASS is historical evidence when the artifact or environment changed. A failed or unavailable check is reported explicitly; it is never silently replaced by inference.
