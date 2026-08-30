# Dashboard

The main dashboard is a Decision Terminal, not a research laboratory.

## Primary order

1. `ENTRY_READY` — maximum 3, actionable.
2. `FORMING` — maximum 6, explicitly “do not enter yet”.
3. Recently changed decisions.
4. Searchable/filterable/paginated all-candidates table.

Each decision card can show symbol, readiness, lifecycle, entry zone, stop, TP levels, leverage recommendation, evidence freshness/coverage, OI, funding, taker/CVD flow, liquidation/cascade evidence, liquidity, cross-exchange agreement, anti-chase state, reasons/blockers, and optional AI advisory.

## Research separation

Replay, recorder health, historical outcomes, lifecycle shadow, funnel diagnostics, and manual Backtest Lab remain secondary/collapsed research surfaces. They never imply entry eligibility.

## Failure semantics

When no entry is ready the terminal reports `NO ENTRY READY SIGNALS` and dominant blockers instead of presenting a Top-3 observational list as an entry cue.

## Transport diagrams

See [D11 Dashboard / API / SSE](diagrams/11-dashboard-api-sse.md) for bootstrap, stream, replay, fallback, and lazy research loading, and [D12 Notification Delivery](diagrams/12-notification-delivery.md) for the downstream durable notification boundary.
