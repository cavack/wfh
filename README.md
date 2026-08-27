# WaterfallHunter

WaterfallHunter is a SIGNAL_ONLY observational monitoring and research system for USDT perpetual futures. It collects exchange evidence, evaluates a staged waterfall setup, records natural signal outcomes, replays production decision packets, and exposes the results through a read-only dashboard.

> **Safety status:** `LIVE_TRADING_ENABLED=false` is the project invariant. The current system does not place orders. Rankings, execution suitability, historical outcomes, experimental pre-triggers, and dashboard labels are observational until their promotion gates are satisfied.

## Components

- `backend/` — FastAPI evaluator, evidence recorder, lifecycle persistence, replay, outcome ledger, execution analysis, and API.
- `frontend/` — Next.js monitoring dashboard.
- `watchdog/` — service-health watcher and optional notification bridge.
- `deploy/` — Prometheus, Alertmanager, and Grafana configuration.
- `scripts/` — backtesting and calibration tools.
- `docs/` — evidence, replay, and operational-design documentation.
- `research/` — curated research notes only; generated datasets and backtest outputs are intentionally excluded.

## Current operational boundaries

- SIGNAL_ONLY: no order placement or cancellation.
- No production-threshold promotion without walk-forward and holdout validation.
- Historical downloads and the natural live outcome ledger remain separate.
- Execution suitability cannot replace the volume proxy until promotion criteria pass.
- Lifecycle persistence and stale-trigger safety must be audited before any hard gate.
- Any future trading integration would require a separate design, approval, implementation, and risk-control boundary; it is not part of this repository runtime.
- AI output is advisory only. Gemini is the only configured AI advisory provider; if it is unavailable, deterministic logic continues without a local-model fallback.

## Local development

Requirements: Docker with Compose, or Python 3.13 and Node.js 26 for running components directly.

```bash
cp .env.example .env
docker compose up --build
```

The services bind to loopback by default:

- Dashboard: `http://127.0.0.1:3000/dashboard/`
- Grafana: `http://127.0.0.1:3001/`

Never commit `.env`, runtime databases, evidence packets, logs, backups, or provider credentials.

## Validation

Backend:

```bash
python -m pip install --require-hashes -r backend/requirements.lock
PYTHONPATH=backend/src:. pytest -q backend/tests
```

Frontend:

```bash
cd frontend
npm ci
npm run typecheck
npm run build
```

Container configuration:

```bash
cp .env.example .env
docker compose config --quiet
docker compose build waterfall-backend frontend watchdog
```

CI runs backend tests, frontend typechecking/build, Python and npm dependency audits, container validation/build, and repository hygiene checks for pull requests. Dependabot configuration tracks Python, npm, GitHub Actions, and Docker dependency updates.

## Deployment

Production secrets and state live outside Git. The Production runtime remains `SIGNAL_ONLY` with `LIVE_TRADING_ENABLED=false`. After a successful `CI` run on `main`, the Production deployment workflow deploys that exact revision, backs up and migrates the managed SQLite database, activates release-scoped Telegram signal delivery, and certifies health/readiness plus OCI revision identity. The application database is stored in the `waterfall_data` volume and is not part of this repository.

## Repository governance

Changes should be made on short-lived branches and merged through reviewed pull requests after CI passes. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development and safety checklist. Ownership rules live in `.github/CODEOWNERS`.

## Project roadmap

Current work focuses on improving evidence quality, lifecycle correctness, replay fidelity, operational stability, and scientifically valid signal evaluation without adding an order-execution path.
