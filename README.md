# WaterfallHunter

WaterfallHunter is a SIGNAL_ONLY USDT perpetual-futures waterfall detector. It normalizes exchange evidence, builds one canonical decision packet per symbol, separates lifecycle from entry timing, records outcomes/replay evidence, and exposes a decision-first read-only dashboard.

> **Safety status:** `LIVE_TRADING_ENABLED=false` is the project invariant. WaterfallHunter does not place orders. Only canonical `ENTRY_READY` is an actionable signal state; research rankings, experimental features, historical evidence, replay, and diagnostics cannot create or veto a signal.

## Components

- `backend/` — FastAPI evaluator, evidence recorder, lifecycle persistence, replay, outcome ledger, execution analysis, and API.
- `frontend/` — Next.js canonical Decision Terminal; research/validation panels are secondary and collapsed by default.
- `watchdog/` — service-health watcher and optional notification bridge.
- `deploy/` — Prometheus, Alertmanager, and Grafana configuration.
- `scripts/` — backtesting and calibration tools.
- `docs/` — evidence, replay, and operational-design documentation.
- `research/` — curated research notes only; generated datasets and backtest outputs are intentionally excluded.

## Canonical documentation

- [Project handoff](docs/PROJECT_HANDOFF.md) — cold-start briefing for a new developer or AI session.
- [Architecture](docs/ARCHITECTURE.md) — runtime topology and data flow.
- [Model](docs/MODEL.md) — fixed market rules and evidence families.
- [Decision engine](docs/DECISION_ENGINE.md) — canonical entry states and readiness semantics.
- [Dashboard](docs/DASHBOARD.md) — Decision Terminal information architecture.
- [Data and database](docs/DATA_AND_DATABASE.md) — SQLite ownership and schema lineage.
- [Operations](docs/OPERATIONS.md) / [Deployment](docs/DEPLOYMENT.md) / [Backup & restore](docs/BACKUP_RESTORE.md).
- [Telegram](docs/TELEGRAM.md) and [AI advisory](docs/AI_ADVISORY.md).
- [Developer onboarding](docs/DEVELOPER_ONBOARDING.md) and [Troubleshooting](docs/TROUBLESHOOTING.md).

## Current operational boundaries

- SIGNAL_ONLY: no order placement or cancellation.
- No production-threshold promotion without walk-forward and holdout validation.
- Historical downloads and the natural live outcome ledger remain separate.
- Execution suitability cannot replace the volume proxy until promotion criteria pass.
- Lifecycle persistence and stale-trigger safety must be audited before any hard gate.
- Any future order-execution capability requires a separate design, approval, implementation, and risk-control boundary; it is outside this runtime.
- AI output is advisory only and cannot veto or downgrade a canonical decision. Gemini is the only configured AI advisory provider; if it is unavailable, deterministic logic continues without a local-model fallback.

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

Stable developer commands:

```bash
make help
make validate
make clean-install-check   # release-candidate only; requires a clean committed SHA
```

Backend directly:

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

Production secrets and state live outside Git. The Production runtime remains `SIGNAL_ONLY` with `LIVE_TRADING_ENABLED=false`. A normal push to protected `main` runs CI only and never deploys. After successful exact-SHA CI and the required release/backup/migration/rollback certification, an operator explicitly dispatches the `CI` workflow on `main` with `deploy_production=true`; the workflow reruns the required checks before deploying that exact revision, backing up and migrating the managed SQLite database, activating release-scoped Telegram signal delivery, and certifying health/readiness plus OCI revision identity. The application database is stored in the `waterfall_data` volume and is not part of this repository.

## Repository governance

Changes should be made on short-lived branches and merged through reviewed pull requests after CI passes. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development and safety checklist. Ownership rules live in `.github/CODEOWNERS`.

## Project roadmap

Current work focuses on improving evidence quality, lifecycle correctness, replay fidelity, operational stability, and scientifically valid signal evaluation without adding an order-execution path.
