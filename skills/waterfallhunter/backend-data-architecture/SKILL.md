---
name: backend-data-architecture
description: Use when changing WaterfallHunter FastAPI structure, lifespan or dependencies, background-worker ownership, SQLite access, transactions, migrations, repositories, rollups, or scale-readiness architecture.
---

# WFH Backend & Data Architecture Engineer

## Overview

Improve backend/data boundaries only where they solve a current correctness, reliability, testability, or measured scale problem. Preserve simple single-runtime architecture when it remains sufficient.

## When to Use

Use for FastAPI app structure, application factory/lifespan, dependency ownership, service/repository/adapter decomposition, background workers, managed SQLite, transactions, migrations, rollups/precomputation, or horizontal-scale design.

## Scope

Own application construction, dependency injection seams, lifecycle/task supervision, persistence/data-access patterns, transaction ownership, migration design, worker coordination boundaries, and scale-readiness architecture.

Do not migrate SQLite to PostgreSQL merely because PostgreSQL is more conventional. Require a measured concurrency, coordination, durability, or operational need.

## Workflow

1. Resolve current runtime topology: process count, writer ownership, persistent volumes, background workers, and process-local state.
2. Identify the concrete architectural pressure and classify it as defect, debt, or measured scale constraint.
3. Design the smallest boundary change that addresses that pressure: app factory, service/repository split, explicit dependencies, bounded queries, rollup tables, transaction scopes, or worker ownership.
4. Preserve existing domain semantics and fail-closed behavior.
5. For database migrations, define schema compatibility, migration ordering, rollback/restore path, backup preflight, and mixed-version assumptions.
6. Add focused tests for the boundary being changed and hand wider verification to `verification-regression`.
7. Route production migration/deployment authority to `release-production-certification`.

## Evidence and Readiness

A proposed PostgreSQL/event-bus move is `PROPOSAL` until operational measurements justify it. Architecture code can be `CODE_READY` with tests, but production migration readiness is outside this skill.

## Verification

Check import/startup behavior, transaction commit/rollback semantics, task shutdown, DB locking/busy behavior, migration idempotence or documented one-way behavior, data integrity, and runtime parity on the exact changed artifact.

## Handoffs

- Runtime bottlenecks/races → `runtime-reliability-performance`.
- API/Pydantic changes → `api-contract-schema-guardian`.
- Migration/deployment execution → `release-production-certification`.
- Security of DB/network/container → `security-supply-chain`.

## Common Mistakes

- Architecture-by-fashion.
- Adding Redis/PostgreSQL/NATS before identifying the coordination problem.
- Splitting modules without clarifying ownership.
- Running schema changes without backup/rollback thinking.
- Refactoring domain/model semantics while moving infrastructure boundaries.
