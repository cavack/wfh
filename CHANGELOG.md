# Changelog

WaterfallHunter uses release-oriented entries. Git history remains the forensic source for older implementation detail.

## Unreleased

### Added
- Canonical Decision Terminal with one actionable `ENTRY_READY` state.
- Cascade Intelligence evidence inside the canonical decision engine.
- Durable canonical decision events and Telegram delivery path.
- Canonical repository/host handoff, operations, backup, and recovery documentation.

### Changed
- Product terminology standardized to `SIGNAL_ONLY` / `NO ORDER EXECUTION`.
- Research and validation surfaces are secondary to the Decision Terminal.

### Safety
- `LIVE_TRADING_ENABLED=false` remains mandatory.
- No order placement or cancellation path is enabled.
