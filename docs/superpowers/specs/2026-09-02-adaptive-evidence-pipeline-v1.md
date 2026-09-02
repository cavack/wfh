# Adaptive Evidence Pipeline v1 — Design Spec

## Goal

Reduce WaterfallHunter decision latency and stale/missing market evidence without changing ScoreV2, lifecycle semantics, eligibility, Anti-Chase, signal provenance, notification ordering, or execution policy.

## Verified production pressure

Baseline release: `460f557493f251bcd7ced27cd9f7736b607b037c`.

- Backend is healthy at a 2 GiB cgroup ceiling with restart count 0 after the runtime-memory release.
- Post-deploy global candidate analysis p95 commonly remains about 270–330 seconds, above the 180-second freshness objective.
- Production source selection frequently walks multiple venues before a complete packet is found.
- A live snapshot showed 111 of 129 analyzable candidates with at least one primary-source fallback and a mean 2.60 failed sources.
- Dominant fallback reasons were `insufficient fresh trades` and `stale orderbook snapshot`.
- The validator already owns a WebSocket manager, but PRE-TRIGGER retains liquidation-only streams and the microstructure path still fetches trades plus two additional order books through REST.
- Closed 15m/1h/4h candles are repeatedly re-fetched even though they cannot change before the next close.

## Safety invariants

`ENTRY_READY=78`, `FORMING=55`, and Anti-Chase `1.2 ATR` remain unchanged.
`LIVE_TRADING_ENABLED=false` remains mandatory.
No missing/stale evidence may be converted to directional evidence.
No cached observation may outlive its canonical freshness/closed-candle boundary.

## Wave A architecture

### 1. Continuous deadline scheduler

Replace the all-candidates `asyncio.gather()` barrier with a bounded in-flight set and per-symbol start-to-start deadlines. New candidates are immediately due. State priority remains `TRIGGERED → ARMED → PRE-TRIGGER → FUEL-RICH → WATCH`, but each state also receives a bounded target interval.

Initial runtime-only cadence targets:

- TRIGGERED: 15 s
- ARMED: 15 s
- PRE-TRIGGER: 30 s
- FUEL-RICH: 90 s
- WATCH: 150 s

These values are scheduling budgets, not model thresholds. Per-symbol single-flight is mandatory; no candidate may have two concurrent evaluations.

Maintenance work (active-universe refresh, expiration reconciliation, universe snapshot, heap trim and cache pruning) runs independently of evaluation completion, so a slow WATCH candidate cannot block a due PRE-TRIGGER candidate.

### 2. Hot evidence reuse

PRE-TRIGGER and ARMED keep full ticker/order-book/trade WebSocket evidence instead of liquidation-only evidence. Existing liquidation semantics stay intact.

The WebSocket manager keeps bounded recent order-book snapshots and a bounded rolling fresh-trade window. The microstructure analyzer may consume this preloaded packet only when it independently satisfies the existing freshness, sample-count and three-snapshot requirements; otherwise it falls back to the existing REST acquisition path.

### 3. Causal closed-candle cache

The candle analyzer caches only validated closed OHLCV series. A cache entry is reusable only when its newest closed candle covers the latest expected closed bucket for that timeframe. A boundary miss or exchange lag causes a real fetch; stale data is never promoted as fresh.

The cache is process-local, bounded, and stores at most 1024 series. It preserves exact source rows used by replay/evidence capture. No score calculation changes.

### 4. Runtime telemetry

Add low-cardinality Prometheus observations for:

- evaluation duration by lifecycle state;
- evidence-stage duration;
- primary-source attempt count;
- WebSocket/preloaded evidence hits and REST fallbacks;
- candle-cache hit/miss/eviction counts;
- in-flight evaluation count and due-candidate backlog.

`analysis_observed_at` continues to represent the start of the causal evaluation. Scheduler queue time and evaluation completion time are separately observable; the system must not fake freshness by rewriting the analysis timestamp late.

## Verification / release gate

Wave A is successful only if exact-head tests and CI pass, the deployed revision is exact, health remains green, restart/OOM counts remain zero, and a risk-proportional soak demonstrates materially improved freshness. The primary production target is global usable analysis p95 `<180s`; PRE-TRIGGER/ARMED should be materially lower.

## Conditional Wave B

A read-only CCXT Pro probe on the production library confirmed multi-symbol order-book/trade/ticker APIs. Their returns are incremental and exchange-specific, and dynamic unsubscribe capability is not uniform. Therefore shared multi-symbol FUEL-RICH pools are deliberately gated behind Wave A production measurements rather than mixed into the first correctness-sensitive change.

If Wave A does not hold global p95 below 180 seconds, Wave B will add capability-gated shared market-evidence pools, initially on exchanges with explicit multi-symbol subscribe and unsubscribe support, with bounded subscriber sets and per-exchange circuit breakers.

## Separate follow-up work

Decision-event snapshot churn and long-term production-evidence retention are real measured storage pressures, but they touch immutable decision/persistence semantics. They will use a separate backend/data design and release path after runtime freshness is stable.

Threshold/weight/gate/Anti-Chase optimization is also separate. It requires production-equivalent replay, development/walk-forward evaluation, embargo, sensitivity analysis, and an untouched holdout. No calibration is promoted by this runtime work.

## Blast radius

Wave A may modify the hunter scheduler, WebSocket evidence cache, microstructure acquisition adapter, candle analyzer cache, Prometheus telemetry, focused tests and documentation. It must not modify decision thresholds, score weights, lifecycle transition rules, EntryDecisionPolicy semantics, notification eligibility, immutable signal-ledger rules, or live-trading configuration.
