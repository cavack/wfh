# Free Cascade Intelligence Layer — Design

Date: 2026-08-27
Target repository: `cavack/wfh`
Baseline `main`: `1b1baa7e43a29869a79b29a8410069900e296e81`
Branch: `feat/free-cascade-intelligence-v1`

## 1. Outcome

Upgrade WaterfallHunter by adding a free, exchange-native **Cascade Intelligence** sensor layer underneath the existing decision system.

The new layer improves direct observation of long-liquidation cascades without replacing WaterfallHunter's existing ScoreV2, lifecycle, anti-chase, provenance, scientific validation, replay, outcome ledger, or deployment safety boundaries.

Version 1 is **observational only**. It does not change ScoreV2 weights, lifecycle transitions, ranking, eligibility, leverage, notification eligibility, or production execution policy.

Classification for v1: `SEMANTIC_INFRA / OBSERVATIONAL_EVIDENCE`.

Any later use of the new features for scoring, lifecycle transitions, ranking, or eligibility is a separate `MODEL_AFFECTING` change and must go through `strategy-score-lifecycle` plus `scientific-backtest-validation`.

## 2. Why this design

Current WaterfallHunter already has valuable pre-crash observations:

- derivatives normalization for funding, funding percentile/z-score, OI change/acceleration, taker ratio, and top-trader long/short ratio;
- microstructure sampling for spread, slippage, depth, trade-flow delta, footprint imbalance, depth churn, and a spoofing proxy;
- evidence freshness, unavailable semantics, lifecycle, anti-chase, replay, and scientific validation infrastructure.

The primary missing capability is **direct cascade mechanics**: real liquidation event flow, continuous trade delta, higher-frequency local order-book reconstruction, cross-exchange agreement, and bounded derived descriptors such as liquidation velocity and liquidity-vacuum pressure.

The design therefore adds a sensor layer instead of rewriting the decision engine.

## 3. Protected invariants

The implementation MUST preserve all of the following:

- `SIGNAL_ONLY` and `LIVE_TRADING_ENABLED=false`;
- no order placement or cancellation path;
- ScoreV2 weights and evidence semantics unchanged;
- Watch Score semantics unchanged;
- lifecycle state and transition semantics unchanged;
- strict/experimental eligibility boundaries unchanged;
- anti-chase behavior unchanged;
- FinalRanking semantics unchanged;
- immutable signal provenance unchanged;
- persistence-before-notification unchanged;
- scientific holdout/walk-forward rules unchanged;
- missing or stale cascade data is `UNAVAILABLE`/`PARTIAL`, never bearish or bullish evidence by default.

## 4. Free data sources

### 4.1 Binance USD-M perpetuals

Use public exchange-native market data only. No account API key is required for public market streams.

Target inputs:

- forced-liquidation events where supported by the public futures stream;
- aggregate/public trades with aggressor-side semantics;
- depth snapshot + incremental depth stream;
- mark/index/last prices;
- funding and funding history;
- open-interest history;
- existing taker/top-trader data already used by WaterfallHunter.

### 4.2 Bybit V5 linear perpetuals

Use the public linear WebSocket endpoint.

Target topics:

- `allLiquidation.{symbol}` for complete liquidation events;
- `publicTrade.{symbol}` for real-time trades and taker side;
- `orderbook.50.{symbol}` initially, with higher depths available only if measured need justifies them;
- `tickers.{symbol}` for market-state reconciliation.

The collector must process snapshot/delta order-book semantics exactly and reset the local book on a fresh snapshot.

### 4.3 OKX public market data

Use only public endpoints/channels that are documented as public for the exact instrument.

Target inputs:

- order book;
- trades;
- mark/last/ticker context;
- funding and open interest where public coverage exists.

If a comparable public liquidation feed is not available for the exact contract, liquidation capability for OKX is explicitly `UNAVAILABLE`. The system must not infer an OKX liquidation event stream from unrelated account/order channels.

### 4.4 Coinalyze free API — optional corroboration

Coinalyze is an optional free-tier historical/cross-exchange corroboration source for supported instruments. It may provide OI, funding, liquidation history, long/short ratios, and buy/sell-volume history subject to its current free-tier limits.

Coinalyze is not required for the runtime to start. Missing key/quota/coverage produces `UNAVAILABLE`, not a failed bearish/bullish signal.

### 4.5 Explicit non-requirements

Version 1 does not require paid CoinGlass, Hyblock, Kaiko, Amberdata, Nansen, CryptoQuant, Glassnode, or Santiment plans.

No brittle website scraping, browser automation, CAPTCHA bypass, or ToS-violating extraction is allowed.

## 5. Canonical contracts

Add an explicitly typed cascade-intelligence contract family.

### 5.1 `CascadeProviderStatus`

Required fields:

- `provider`
- `instrument_id`
- `status`: `PASS | PARTIAL | UNAVAILABLE | STALE | ERROR`
- `observed_at`
- `received_at`
- `age_seconds`
- `capabilities`
- `reason`

### 5.2 `LiquidationEvent`

Required fields:

- `provider`
- `instrument_id`
- `event_time`
- `side_liquidated`: `LONG | SHORT`
- `price`
- `quantity`
- `notional_usd`
- `source_event_id` when supplied by the venue
- `received_at`

Provider-side direction must be normalized carefully. The field expresses the position that was liquidated, not merely the aggressor/order side returned by the exchange.

### 5.3 `CascadeEvidencePacketV1`

Top-level fields:

- `contract_version = "cascade_evidence_v1"`
- `symbol`
- `instrument_identity`
- `observed_at`
- `status`
- `coverage_ratio`
- `providers`
- `liquidations`
- `trade_flow`
- `orderbook`
- `cross_exchange`
- `derived`
- `observational_only = true`
- `hard_gating_allowed = false`
- `promotion_allowed = false`

Important nested structures must be Pydantic models and generated to TypeScript. This packet must not become a permanent `dict[str, Any]` extension bag.

## 6. Derived observations in v1

All values below are descriptive observations, not calibrated probabilities.

### 6.1 Liquidation flow

For 30s / 1m / 5m windows where data permits:

- long-liquidation notional;
- short-liquidation notional;
- total liquidation notional;
- long-liquidation share;
- liquidation event count;
- liquidation notional velocity;
- liquidation notional acceleration;
- burst ratio versus the preceding rolling baseline.

### 6.2 Observed liquidation density map

Build a bounded histogram of **actually observed** liquidation events by price bucket.

Expose:

- bucket price range;
- observed long-liquidation notional;
- observed short-liquidation notional;
- event count;
- recency-weighted density;
- distance from current reference price.

This is deliberately named `observed_liquidation_density`, not `liquidation_heatmap`, because it does not reveal latent positions that have not liquidated yet.

### 6.3 Trade delta / CVD

From public trade streams:

- aggressive-buy notional;
- aggressive-sell notional;
- signed delta;
- rolling CVD for 30s / 1m / 5m;
- delta acceleration;
- sell-dominance ratio.

Each provider's taker-side convention must be normalized and tested independently.

### 6.4 Order-book pressure

From local reconstructed books:

- spread;
- bid/ask depth inside configurable bps bands;
- order-book imbalance;
- bid-depth depletion rate;
- ask-depth depletion rate;
- refill ratio after depletion;
- book churn/cancellation proxy;
- simulated sell impact for bounded notionals;
- liquidity-fragmentation context across providers.

The existing three-snapshot spoofing/churn observation remains separate. V1 does not claim to identify manipulative intent from cancellations alone.

### 6.5 Liquidity-vacuum descriptor

Expose a bounded descriptor, not a probability:

`liquidity_vacuum_score_observational`

It may combine normalized contemporaneous observations such as:

- falling bid depth;
- weak refill;
- widening spread;
- increasing sell impact;
- aggressive sell CVD;
- liquidation acceleration.

The exact formula is versioned and explicitly `promotion_allowed=false`. It cannot affect existing ScoreV2/lifecycle/ranking in v1.

### 6.6 Cross-exchange agreement

For each observation domain:

- number of fresh supporting providers;
- number of disagreeing providers;
- dispersion of price / CVD / depth / funding / OI where comparable;
- explicit disagreement status.

Provider disagreement is context, not something silently averaged away.

## 7. What v1 will NOT fake

The following are not directly knowable for free from public venue feeds with institutional precision and therefore must not be presented as exact facts:

- latent liquidation levels for positions that have not liquidated;
- exact future liquidation notional at each price;
- exact leverage distribution by entry price;
- exact whale-vs-retail leverage map;
- exact CoinGlass/Hyblock-style future liquidation heatmap;
- true spoofing/manipulation intent;
- calibrated probability of a 0.5%, 1%, or 2% cascade;
- calibrated recovery-vs-continuation probability.

Later research may add explicitly named estimates such as `estimated_liquidation_zone_v1`, but estimates must include provenance, assumptions, uncertainty, validation artifacts, and must not masquerade as direct exchange observations.

## 8. Runtime architecture

### 8.1 New package

Recommended package boundary:

```text
backend/src/waterfallhunter/cascade/
  contracts.py
  normalizer.py
  rolling.py
  engine.py
  service.py
  providers/
    base.py
    binance.py
    bybit.py
    okx.py
    coinalyze.py
```

Provider adapters own wire formats and reconnect behavior. The engine owns normalized rolling observations. API/dashboard code only consumes the canonical service contract.

### 8.2 Bounded symbol scope

Do not subscribe to every perpetual on every venue in v1.

The service subscribes only to the current bounded WaterfallHunter tracked/priority universe, with a configurable hard cap and deterministic subscription rotation when the cap is exceeded.

Initial design target: at most 40 actively streamed symbols per provider until soak measurements justify a higher limit.

This avoids replacing the former REST pressure problem with an uncontrolled WebSocket/memory problem.

### 8.3 Memory bounds

Every per-symbol buffer has both time and count bounds.

Initial targets:

- trade/liquidation raw ring: <= 10 minutes and <= 5,000 records per symbol/provider;
- order book: only configured depth levels, not unbounded history;
- derived rolling windows retained instead of full historical snapshots;
- no multi-megabyte cascade object copied into the existing SSE replay buffer.

A compact derived packet is exposed to dashboard/SSE consumers. Raw event material remains internal to the collector or a later dedicated recorder.

### 8.4 Persistence

V1 intentionally requires **no database migration**.

Runtime cascade intelligence is process-local observational state. This is the fastest safe integration and avoids coupling a first sensor iteration to production migration authority.

A later recorder phase may add append-only normalized event persistence for scientific replay after data volume, retention, and migration design are measured.

### 8.5 Lifecycle ownership

The cascade service is a supervised background service owned by application lifespan.

Requirements:

- deterministic startup/shutdown;
- heartbeat and reconnect with bounded exponential backoff + jitter;
- no duplicate collectors after reconnect;
- provider status visible in health/metrics;
- shutdown cancellation must not hang the API process.

## 9. Integration with existing WaterfallHunter logic

### 9.1 v1 decision semantics

No existing decision boundary changes.

The cascade packet may be attached as an observational nested field to candidate/dashboard evidence, but:

- ScoreV2 ignores it;
- Watch Score ignores it;
- FinalRanking ignores it;
- lifecycle ignores it;
- anti-chase ignores it;
- leverage ignores it;
- signal eligibility ignores it;
- Telegram eligibility ignores it.

This invariant receives regression coverage.

### 9.2 Future promotion

After sufficient live data is recorded, a separate research/promotion wave may test hypotheses such as:

- liquidation acceleration improves PRE-TRIGGER precision;
- negative CVD acceleration improves ARMED timing;
- bid-depth depletion + failed refill improves cascade continuation discrimination;
- cross-exchange liquidation agreement reduces single-venue false positives.

Only out-of-sample evidence may justify promotion into scoring or lifecycle logic.

## 10. API contract

Add a bounded read-only endpoint:

`GET /api/cascade-intelligence/{symbol}`

Response: `CascadeEvidencePacketV1`.

Optional bounded summary endpoint after the single-symbol endpoint is stable:

`GET /api/cascade-intelligence?limit=N`

Rules:

- unknown/unmapped symbol -> explicit 404/422 contract as selected by existing API conventions;
- mapped but no fresh data -> 200 with explicit `UNAVAILABLE`/`PARTIAL` packet;
- never return stale values as current;
- no caller-provided provider URL;
- no unbounded history query in v1.

## 11. Dashboard

Frontend modes: `ENGINEERING + UX + PERFORMANCE`.

Add a compact **Cascade Intelligence** evidence section to candidate investigation/detail UI, not a new competing ranking algorithm.

Display only canonical backend values:

- liquidation pressure / velocity;
- CVD direction and acceleration;
- bid-depth depletion / refill;
- liquidity-vacuum descriptor;
- provider coverage;
- cross-exchange agreement/disagreement;
- observed liquidation-density buckets when useful.

Always show whether the packet is `PASS`, `PARTIAL`, `STALE`, or `UNAVAILABLE`.

Do not call an observed density histogram a future liquidation heatmap.

## 12. Metrics and observability

Add bounded metrics such as:

- `waterfall_cascade_provider_connected{provider}`
- `waterfall_cascade_provider_reconnects_total{provider}`
- `waterfall_cascade_provider_errors_total{provider,reason}`
- `waterfall_cascade_event_lag_seconds{provider,kind}`
- `waterfall_cascade_active_symbols{provider}`
- `waterfall_cascade_events_total{provider,kind}`
- `waterfall_cascade_buffer_records{provider,kind}`
- `waterfall_cascade_packet_age_seconds`
- `waterfall_cascade_packet_build_duration_seconds`

Log payloads must not dump massive raw books/trade arrays on routine errors.

## 13. Failure semantics

- WebSocket disconnected -> provider `UNAVAILABLE` after freshness budget expires.
- Out-of-order sequence -> discard invalid delta state and wait for/resubscribe to a fresh snapshot.
- Timestamp in future/outside tolerance -> invalid observation.
- Unsupported symbol -> provider capability `UNAVAILABLE`.
- Provider disagreement -> `PARTIAL`/disagreement context, not forced consensus.
- Rate-limit/quota issue -> provider `UNAVAILABLE` with bounded retry.
- A failed cascade provider must not stop the existing hunter from operating with its current evidence paths.

## 14. Verification strategy

Implementation follows regression-first/TDD where feasible.

### Provider/parser tests

- Binance liquidation/trade/depth fixtures;
- Bybit `allLiquidation`, `publicTrade`, order-book snapshot/delta fixtures;
- OKX public book/trade fixtures;
- malformed messages;
- wrong instrument;
- out-of-order sequence;
- stale timestamps;
- reconnect/resubscribe idempotence;
- provider side/direction normalization.

### Derived-observation tests

- CVD arithmetic;
- liquidation velocity/acceleration;
- density buckets;
- depth depletion/refill;
- bounded impact simulation;
- explicit unavailable/partial propagation;
- deterministic packet generation for identical event sets.

### Regression invariants

- existing ScoreV2 output unchanged for the same canonical input;
- existing lifecycle transitions unchanged;
- existing FinalRanking unchanged;
- anti-chase unchanged;
- no new eligibility path;
- no live-order path;
- candidate packet without cascade data remains valid.

### API/frontend

- Pydantic/OpenAPI contract tests;
- generated TypeScript drift check;
- polling/SSE parity for any dashboard field added;
- frontend unit/component behavior;
- typecheck/build;
- Playwright for PASS/PARTIAL/UNAVAILABLE candidate states;
- mobile layout check.

### Runtime

- bounded reconnect test;
- 30–60 minute collector soak;
- verify per-provider active symbol cap;
- verify ring-buffer caps;
- verify no monotonic RSS growth attributable to raw event retention;
- verify existing dashboard/SSE payload remains bounded.

## 15. Acceptance criteria for v1

V1 is code-ready only if all are true on the exact changed artifact:

1. At least Binance and Bybit produce correctly normalized free cascade observations for a common supported USDT perpetual used in tests/fixtures.
2. The runtime remains functional with every cascade provider disabled/unavailable.
3. No API key is required for the mandatory Binance/Bybit public path.
4. The new packet has explicit freshness and provider provenance.
5. Liquidation events and taker side are normalized with regression fixtures.
6. Continuous order books recover correctly after a fresh snapshot.
7. Per-symbol/provider buffers are bounded.
8. ScoreV2/lifecycle/ranking/anti-chase/eligibility regressions prove no semantic change.
9. API contract and generated frontend types are synchronized.
10. Frontend displays cascade evidence without duplicating backend decision logic.
11. Focused tests plus the proportional repository verification matrix are green.
12. No production deployment/promotion claim is made merely from code-level success.

## 16. Implementation sequencing

### Slice A — canonical contracts + pure rolling engine

No network I/O. RED -> GREEN parser/math/availability tests first.

### Slice B — Bybit public provider

Implement full liquidation + trade + order-book path because Bybit exposes the most directly useful public liquidation topic.

### Slice C — Binance public provider

Add liquidation/trade/depth path and reuse existing funding/OI/taker normalization instead of duplicating it.

### Slice D — cascade service + read-only API

Add supervised ownership, freshness, bounded buffers, status, and API contract.

### Slice E — OKX corroboration + optional Coinalyze

Only documented public capabilities; unsupported liquidation capability stays unavailable.

### Slice F — dashboard evidence panel

Consume canonical packet only; no score/rank/client-side model logic.

### Slice G — soak + regression certification

Run exact-artifact focused, full regression, frontend, container/runtime and memory/soak checks proportional to the change.

## 17. Production boundary

This design does not authorize production deployment.

Implementation can progress on the feature branch after the written design is reviewed. Any merge/deployment/migration/production certification remains separately governed by the repository's release workflow and `release-production-certification` skill.
