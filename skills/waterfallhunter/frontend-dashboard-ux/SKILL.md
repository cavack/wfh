---
name: frontend-dashboard-ux
description: Use when changing WaterfallHunter Next.js or React behavior, dashboard information hierarchy, mobile or responsive UI, SSE/poll UX, accessibility, RTL/i18n foundations, rendering performance, or visual regression coverage.
---

# WFH Frontend Engineering & Dashboard UX

## Overview

Build a responsive, evidence-first dashboard that consumes canonical backend semantics rather than reimplementing trading/ranking logic in React.

## When to Use

Use for Next.js/React changes, dashboard layout, state management, SSE/poll connection UX, mobile behavior, information hierarchy, accessibility, RTL/i18n foundations, rendering/network performance, or visual regression.

Declare one or more modes: `ENGINEERING`, `UX`, `ACCESSIBILITY`, `PERFORMANCE`.

## Scope

Own frontend state/rendering, interaction and information architecture, responsive/mobile behavior, accessibility semantics, client transport behavior, locale/layout foundations, and browser performance. Backend ranking, eligibility, scoring, and evidence meaning remain canonical server concerns.

## Workflow

1. Resolve the current frontend contract and the actual user task/state that is confusing or failing.
2. Separate transport state (`connecting`, stream open, polling, offline) from data freshness (`none`, fresh, stale) when connection semantics matter.
3. Prefer normalized state and selector-level updates over rerendering large full snapshots when data volume warrants it.
4. Consume canonical backend rank/eligibility/display fields; do not copy Score/FinalRanking formulas into React as the default fix.
5. Design information hierarchy around what matters now, why, and evidence quality; move deep research/ops detail behind appropriate sections rather than deleting evidence.
6. Validate mobile/touch, keyboard/focus, semantic markup/ARIA, reduced motion, and loading/empty/error/stale states.
7. Measure parse/render/network/GC cost for realtime paths and add visual/E2E coverage proportional to impact.

## Evidence and Readiness

Visual preference is `PROPOSAL` unless tied to explicit user requirements or usability evidence. UI correctness defects should be reproduced. Frontend code is not `CODE_READY` until type/build and relevant browser tests pass.

## Verification

Check typecheck/build, component/unit behavior where present, Playwright user flows, SSE fallback/reconnect states, responsive breakpoints, accessibility, screenshot regression when visual behavior changes, and that business logic was not duplicated client-side.

## Handoffs

Payload/semantic changes → `api-contract-schema-guardian`. Runtime stream/backpressure problems → `runtime-reliability-performance`. Model/ranking semantics → `strategy-score-lifecycle`. Wider verification → `verification-regression`.

## Common Mistakes

- Copying backend ranking logic into React.
- Showing “live” merely because the socket opened before valid data arrived.
- Hiding unavailable evidence instead of explaining it.
- Solving desktop layout while breaking mobile/touch.
- Adding state libraries without a demonstrated state/update problem.
