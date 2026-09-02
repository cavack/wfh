# WaterfallHunter Research Challenger Registry

Every challenger is preregistered before final evaluation. These are hypotheses, not production facts or authorized policy changes.

## H1 — Multi-horizon order flow deterioration

- mechanism: A transition from crowded buying to persistent aggressive sell flow may precede waterfall continuation/reversal failure more reliably than a single taker ratio snapshot.
- point_in_time_requirement: Only trades observable before the candidate decision timestamp; rolling windows must use venue timestamps and causal receipt/freshness checks.
- falsifier: No stable incremental OOS net-R/precision value after existing timing, derivatives and cascade evidence; unstable sign across regimes/symbols.
- promotion_gate: Survives ablation, purged WFO, concentration checks, untouched final OOS and live shadow without increasing stale/unavailable evidence.

## H2 — Futures/spot/mark/index basis stress

- mechanism: Rapid futures-versus-spot or mark/index divergence can expose leverage-driven price discovery and liquidation feedback before/inside cascades.
- point_in_time_requirement: Synchronized same-economic-contract timestamps; never forward-fill across freshness boundaries or mix incompatible index/contract definitions.
- falsifier: Incremental edge disappears after spread/slippage/market-volatility controls or is confined to one venue/event.
- promotion_gate: Stable sign and contribution across held-out symbols/regimes with cost-adjusted benefit and no identity violations.

## H3 — OI × funding × crowding leverage stress

- mechanism: Rising or stressed open interest combined with long crowding/funding and deteriorating taker flow may identify fragile leveraged positioning.
- point_in_time_requirement: Funding/OI/long-short fields must be timestamped and available before the decision; units and sampling intervals must be normalized per venue.
- falsifier: Interaction adds no robust value beyond existing derivatives points, or gains vanish under lagged/stale-safe reconstruction.
- promotion_gate: Positive marginal OOS value, broad regime support and defensible causal provenance.
