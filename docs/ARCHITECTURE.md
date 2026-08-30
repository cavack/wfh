# Architecture

WaterfallHunter is a `SIGNAL_ONLY` USDT perpetual-futures cascade/short-signal system. It never places or cancels exchange orders.

## Runtime topology

`nginx -> frontend -> backend -> SQLite`, with `watchdog`, Prometheus, Grafana, and Alertmanager providing health and observability. Docker Compose is the application runtime; systemd asserts the canonical Compose stack after boot and performs bounded health recovery.

## Decision data flow

`market discovery -> normalized evidence -> cascade intelligence -> canonical entry decision -> immutable decision event -> dashboard / durable Telegram delivery`.

Lifecycle (`WATCH`, `FUEL-RICH`, `PRE-TRIGGER`, `ARMED`, `TRIGGERED`, `EXHAUSTED`, `INVALIDATED`) is evidence context. It is not the entry decision.

## Main components

- `backend/`: FastAPI, discovery, evidence normalization, cascade intelligence, lifecycle, decision engine, persistence, validation, and notifications.
- `frontend/`: Next.js Decision Terminal and secondary research/validation views.
- `watchdog/`: health watcher and alert receiver.
- `deploy/`: systemd, nginx, Prometheus, Grafana, and Alertmanager configuration.
- `scripts/`: validation, migration, backup, calibration, replay, and deployment tooling.

## Architecture diagrams

See the [Architecture Diagram Suite](diagrams/README.md), especially [D01 System Context](diagrams/01-system-context.md), [D02 Runtime Deployment Topology](diagrams/02-runtime-deployment-topology.md), [D03 End-to-End Data Pipeline](diagrams/03-end-to-end-data-pipeline.md), and [D17 Master Architecture Map](diagrams/17-master-architecture-map.md).

## Safety boundary

`LIVE_TRADING_ENABLED=false` is mandatory. AI is advisory only. Missing or stale evidence is unavailable, never silently bullish or bearish.
