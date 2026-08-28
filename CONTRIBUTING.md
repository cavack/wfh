# Contributing

WaterfallHunter is a SIGNAL_ONLY monitoring and research system. Changes must preserve the safety boundary that order placement is disabled and `LIVE_TRADING_ENABLED=false` remains mandatory.

## Development workflow

1. Create a short-lived branch from `main`.
2. Keep changes narrowly scoped and add or update tests for behavior changes.
3. Install `backend/requirements.lock` with `--require-hashes`, then run backend tests with `PYTHONPATH=backend/src:. pytest -q backend/tests`.
4. Run `npm ci`, `npm run typecheck`, and `npm run build` in `frontend/`.
5. For container or configuration changes, copy `.env.example` to `.env`, run `docker compose config --quiet`, and build the affected services.
6. Open a pull request and require CI to pass before merge.

## Safety and data handling

Never commit credentials, `.env`, production databases, evidence packets, logs, backups, exchange-account details, or generated research datasets. Never enable live trading or promote thresholds without explicit approval and documented holdout/walk-forward validation.

## Dependency changes

Keep dependencies pinned or lockfile-backed. Security findings from dependency audits must be resolved or explicitly documented before merge.
