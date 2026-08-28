# Security policy

WaterfallHunter processes market data and may use optional third-party API credentials. Never commit secrets, runtime databases, production evidence, or account identifiers.

If you find a vulnerability, report it privately through GitHub's security-advisory feature for this repository. Include the affected component, reproduction steps, and expected impact. Do not include live credentials or exploit public infrastructure while preparing the report.

The repository is SIGNAL_ONLY. `LIVE_TRADING_ENABLED=false` is mandatory and the supported runtime does not place or cancel exchange orders. Any future order-execution capability requires a separately reviewed safety design and implementation outside the current runtime boundary.
