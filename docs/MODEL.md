# Model

## Fixed domain rules

- Direction: SHORT only.
- Market: linear USDT perpetual futures only.
- Universe: current catalogue eligibility and economic-contract identity rules in backend discovery/validation.
- Cross-exchange evidence must refer to the same economic contract.
- PRE-TRIGGER/ARMED timing is preferred to chasing an extended move.
- Anti-chase is mandatory.
- Missing/stale data lowers coverage or blocks only where explicitly mandatory.

## Evidence priority

Price structure and timing, OI, aggressive trade flow/CVD, funding/crowding, observed liquidation flow, liquidity/order-book conditions, cross-exchange agreement, and relative weakness feed one canonical packet.

Cascade Intelligence uses observed public/exchange-native evidence. An estimated future liquidation zone must be labelled estimated; it is never represented as a venue-observed heatmap fact.

## Quantity versus quality

Weak optional evidence reduces readiness instead of creating universal all-red gates. Objective safety conditions remain hard invalidators. The UI exposes at most 3 `ENTRY_READY` and 6 nearest `FORMING` setups.

## Calibration boundary

`entry_readiness` is a versioned evidence/readiness score, not a guaranteed probability. New evidence or thresholds require replay, walk-forward/holdout evaluation, and explicit promotion evidence before becoming authoritative.
