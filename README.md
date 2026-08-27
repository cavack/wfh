# WaterfallHunter

WaterfallHunter is a signal-only USDT perpetual-futures waterfall detector. It normalizes exchange evidence, builds one canonical decision packet per symbol, separates lifecycle from entry timing, records outcomes/replay evidence, and exposes a decision-first dashboard.

> **Safety status:** `LIVE_TRADING_ENABLED=false` is the project invariant. WaterfallHunter does not place orders. Only canonical `ENTRY_READY` is an actionable signal state; research rankings, experimental features, historical evidence, replay, and diagnostics cannot create or veto a signal.

## Components

- `backend/` — FastAPI evaluator, evidence recorder, lifecycle persistence, replay, outcome ledger, execution analysis, and API.
- `frontend/` — Next.js canonical Decision Terminal; research/validation panels are secondary and collapsed by default.
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
- AI output is advisory only and cannot veto/downgrade a canonical decision. If Gemini is unavailable, deterministic logic continues unchanged.

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

## Canonical signal semantics

The decision path is `evidence -> cascade intelligence -> canonical entry decision -> durable transition/event -> dashboard/Telegram`. The public decision states are `NO_TRADE`, `FORMING`, `ENTRY_READY`, `ACTIVE`, `LATE`, `INVALIDATED`, `EXPIRED`, and `UNAVAILABLE`. `ENTRY_READY` is the only proactively actionable state; `ACTIVE` and lifecycle `TRIGGERED` never imply an entry by themselves.

## Validation

For a release-candidate commit, run the isolated clean-install validator. It rejects a dirty worktree, exports the exact commit to a temporary directory, validates Compose, builds the exact production image family, runs the backend suite inside the built backend image, applies migrations to a throwaway SQLite database, and verifies OCI revision labels. It never starts Production services, mounts the Production database, or sends Telegram messages.

```bash
./scripts/validate_clean_install.sh
```

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

Production secrets and state live outside Git. Copy `.env.example` to `.env`, provide only the optional credentials you need, keep `LIVE_TRADING_ENABLED=false`, and deploy through Docker Compose. The application database is stored in the `waterfall_data` volume and is not part of this repository.

## Repository governance

Changes should be made on short-lived branches and merged through reviewed pull requests after CI passes. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development and safety checklist. Ownership rules live in `.github/CODEOWNERS`.

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

## License

This repository is publicly viewable but is not open-source licensed. See [LICENSE](LICENSE).
