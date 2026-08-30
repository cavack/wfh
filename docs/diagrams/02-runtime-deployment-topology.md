# D02 — Runtime Deployment Topology

Source baseline: `main@65c063ffea6209ecd84b224656bbc627ff811898`

Runtime reconciliation: read-only inspection of `srv8643113472` at implementation time.

## Purpose

Show the deployed host/container boundary, public edge, loopback/public surfaces, internal application services, persistent data, and bounded host recovery controls.

Authoritative references: `docs/OPERATIONS.md`, `docker-compose.yml`, production Compose labels and read-only runtime inspection.

```mermaid
flowchart LR
    Browser[Operator browser]

    subgraph Host[Ubuntu host: srv8643113472]
        Nginx[Host nginx\npublic reverse proxy]
        Systemd[systemd\ncanonical stack + bounded health recovery]

        subgraph Compose[Docker Compose: waterfallhunter]
            FE[waterfall-frontend\nNext.js :3000 loopback]
            BE[waterfall-backend\nFastAPI :8000 internal]
            WD[waterfall-watchdog]
            Prom[waterfall-prometheus\n:9090 internal]
            Grafana[waterfall-grafana\n:3001 loopback]
            AM[alertmanager\n:9093 internal]
        end

        Data[(persistent managed SQLite volume)]
        Env[/host-owned runtime configuration/]
    end

    Browser --> Nginx --> FE --> BE --> Data
    BE --> Prom
    WD --> BE
    Prom --> Grafana
    Prom --> AM
    Systemd -. bounded recovery / compose assertion .-> Compose
    Env -. configuration .-> Compose
```

## Runtime facts observed read-only

- Checkout: `/srv/waterfallhunter/app` at detached `65c063ffea6209ecd84b224656bbc627ff811898`.
- Backend, frontend, watchdog, Prometheus, Grafana, and Alertmanager were running; backend reported healthy.
- nginx was active on the host.
- `LIVE_TRADING_ENABLED=false`; `LBANK_EXECUTION_SHADOW_ENABLED=true`.
- The runtime uses `docker-compose.yml` plus the host-owned `/srv/waterfallhunter/runtime/production-volumes.override.yml` topology override.

## Operational notes

The persistent data volume survives ordinary runtime replacement. `docker compose down -v` is outside the supported recovery path because removing named volumes can destroy persistent database state.

## Safety boundary

This topology is `SIGNAL_ONLY`; no container or host service shown here is an exchange order executor.
