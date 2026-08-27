---
name: engineering-orchestrator
description: Use when a WaterfallHunter task spans multiple engineering domains, depends on current repository state, or needs coordinated audit, implementation, verification, review, or release gating.
---

# WFH Engineering Orchestrator

## Overview

Coordinate WaterfallHunter engineering work without letting stale findings, overlapping ownership, or incidental model changes leak across domains. Use the smallest specialist set that can complete the task and keep evidence tied to the current repository state.

## When to Use

Use for cross-cutting requests such as audit-and-fix, repository-wide cleanup, multi-layer bugs, strategy changes that touch implementation, incidents that require a code fix, or work that may reach merge/deployment.

Do not use as a substitute for a specialist's domain analysis.

## Scope

At the start of repository-grounded work:

- resolve repository, target branch, current `main` SHA, and working branch;
- inspect relevant open PRs/issues and recent commits;
- identify source-of-truth files and runtime boundaries;
- classify material claims as `VERIFIED_FACT`, `REPRODUCED_DEFECT`, `INFERENCE`, `DEBT`, or `PROPOSAL`;
- declare protected invariants and expected blast radius.

Protected from incidental change: ScoreV2 weights/evidence semantics, lifecycle transitions, strict/experimental eligibility, anti-chase, signal provenance/ledger semantics, persistence-before-notification, scientific holdout/walk-forward rules, and production execution policy.

## Workflow

1. Restate the concrete outcome and classify it as explanatory, code-affecting, model-affecting, policy-affecting, or production-affecting.
2. Re-check current repository state before accepting any older audit or issue as current truth.
3. Build a task map and select only necessary specialists.
4. Assign one primary owner for each file or semantic boundary; sequence overlapping work instead of allowing conflicting edits.
5. Route model/eligibility changes to `strategy-score-lifecycle`; route promotion claims to `scientific-backtest-validation` too.
6. Route production-affecting work to `release-production-certification`.
7. Require `verification-regression` before any completion claim for code changes.
8. Re-read the exact final diff and summarize remaining uncertainty.

## Evidence and Readiness

Use only these non-production readiness states: `NOT_READY`, `ANALYSIS_COMPLETE`, `CODE_READY`, `MERGE_READY`.

Production readiness belongs exclusively to `release-production-certification`. Never infer it from local tests or a stale CI run.

## Verification

Confirm that current SHA was resolved, relevant PRs/issues were checked, each changed file has a primary owner, protected invariants were either preserved or explicitly escalated, exact changed artifacts were verified, and final claims distinguish repository state from production state.

## Handoffs

- Runtime/OOM/concurrency/SSE → `runtime-reliability-performance`.
- FastAPI/worker/DB architecture → `backend-data-architecture`.
- API/schema semantics → `api-contract-schema-guardian`.
- React/dashboard UX → `frontend-dashboard-ux`.
- Score/lifecycle/eligibility → `strategy-score-lifecycle`.
- Backtest/promotion evidence → `scientific-backtest-validation`.
- Data quality → `market-data-evidence-quality`.
- Security → `security-supply-chain`.
- Incident/telemetry → `observability-incident-response`.
- Completion evidence → `verification-regression`.
- Merge/deployment/production claims → `release-production-certification`.

## Common Mistakes

- Trusting an old audit without checking current `main`.
- Treating all requested cleanup as in-scope.
- Allowing two specialists to independently change the same semantic boundary.
- Hiding a threshold/model change inside a UI, reliability, or refactor task.
- Calling tests-passing equivalent to production verification.
