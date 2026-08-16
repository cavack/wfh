# WaterfallHunter

WaterfallHunter is an observational monitoring and research system for USDT perpetual futures. It collects exchange evidence, evaluates a staged waterfall setup, records natural signal outcomes, replays production decision packets, and exposes the results through a read-only dashboard.

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

- No order placement.
- No production-threshold promotion without walk-forward and holdout validation.
- Historical downloads and the natural live outcome ledger remain separate.
- Execution suitability cannot replace the volume proxy until promotion criteria pass.
- Lifecycle persistence and stale-trigger safety must be audited before any hard gate.
- Canary trading requires separate explicit approval and additional risk controls.

## Local development

Requirements: Docker with Compose, or Python 3.12 and Node.js 20 for running components directly.

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
python -m pip install -r backend/requirements.txt
PYTHONPATH=backend/src pytest -q backend/tests
```

Frontend:

```bash
cd frontend
npm ci
npm run build
```

CI runs both checks for every push and pull request.

## Deployment

Production secrets and state live outside Git. Copy `.env.example` to `.env`, provide only the optional credentials you need, keep `LIVE_TRADING_ENABLED=false`, and deploy through Docker Compose. The application database is stored in the `waterfall_data` volume and is not part of this repository.

## Project roadmap

1. Complete natural-outcome and real-execution evidence sufficiency.
2. L4 — waterfall calibration with walk-forward and holdout validation.
3. L5 — historical outcome and net EV validation.
4. Audit lifecycle persistence and stale-trigger safety.
5. L6 — final ranking and controlled operational promotion.
6. L7 — dashboard completion.
7. Canary trading only after separate approval.

## Security

Do not open public issues containing credentials, exchange-account details, production evidence, database files, or server addresses. See [SECURITY.md](SECURITY.md) for reporting guidance.
