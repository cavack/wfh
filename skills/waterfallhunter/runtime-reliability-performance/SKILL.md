---
name: runtime-reliability-performance
description: Use when WaterfallHunter shows OOM or RSS growth, slow or duplicated expensive work, concurrency races, event-loop stalls, SSE backpressure, queue growth, timeout problems, or load/soak regressions.
---

# WFH Runtime Reliability & Performance Engineer

## Overview

Diagnose runtime failures from evidence, contain acute risk without mistaking mitigation for root-cause correction, and prove the fix under concurrency/load conditions representative of WaterfallHunter.

## When to Use

Use for OOM, rising RSS, duplicated report builds, slow endpoints, N+1 aggregation, asyncio races, deadlocks/starvation, cancellation bugs, SSE replay growth, slow-client amplification, timeout/retry storms, or unstable long-running workers.

## Scope

Own OOM/RSS slope, allocation pressure, single-flight/coalescing/cache behavior, N+1 paths, locks/semaphores, event-loop blocking, SSE replay/client queues/backpressure, retry/timeout budgets, load/stress/soak tests, and performance budgets.

Historical incidents or PRs are examples only. Re-check their current status before treating them as active defects.

## Workflow

1. Capture current SHA/runtime context and the observable symptom: RSS curve, latency, restarts, queue depth, duplicated calls, traces, or logs.
2. Reproduce or establish the causal path before patching when practical.
3. Separate immediate containment from root cause. A cache, smaller buffer, restart, or limit may be containment only.
4. Trace work amplification: repeated builds, per-symbol queries, retained full snapshots, queue fan-out, background duplication, retries, and blocking calls.
5. Design the minimal safe correction. Prefer bounded work, single-flight, coalescing/latest-wins semantics, precomputation/rollups, backpressure, and explicit budgets over unbounded caching.
6. Add a regression that fails under the original condition.
7. Verify targeted behavior plus broader concurrency/load/memory soak proportional to blast radius.
8. Add telemetry that would detect recurrence when runtime evidence justified the work.

## Evidence and Readiness

Use `REPRODUCED_DEFECT` only when the failing behavior is demonstrated. Use `INFERENCE` for plausible leak/root-cause hypotheses. A mitigation without root-cause evidence stays explicitly labeled as mitigation. Runtime work can become `CODE_READY` only with regression evidence; production status requires release certification.

## Verification

Check exact SHA, concurrent-call count, cache/single-flight correctness, queue bounds, cancellation behavior, memory/RSS slope, p95/p99 latency where relevant, no new unbounded retention, and a soak duration long enough to expose the original growth pattern.

## Handoffs

- Data access/rollup redesign → `backend-data-architecture`.
- SSE/API payload shape → `api-contract-schema-guardian`.
- Browser/render/network cost → `frontend-dashboard-ux`.
- Metrics/incident closure → `observability-incident-response`.
- Final regression matrix → `verification-regression`.

## Common Mistakes

- Adding a TTL cache and declaring an OOM solved.
- Optimizing before reproducing the expensive path.
- Increasing memory limits instead of explaining growth.
- Keeping many full SSE snapshots per slow client.
- Testing only single-request latency for a concurrency defect.
