# Operations

## Canonical host paths

- Application checkout: `/srv/waterfallhunter/app`
- Host-owned environment: `/etc/waterfallhunter/waterfallhunter.env`
- Runtime/certification state: `/srv/waterfallhunter/runtime`
- Optional host-owned Compose topology override: `/srv/waterfallhunter/runtime/production-volumes.override.yml`
- Certified backups: `/srv/waterfallhunter/backups`

## Runtime

Docker Compose manages backend, frontend, watchdog, Prometheus, Grafana, and Alertmanager. Nginx is the host edge. `waterfallhunter.service` calls `scripts/production_compose.sh`, which always uses the canonical project name/environment and includes the host-owned topology override only when that file exists. This preserves adopted external volumes/networks on the current host without making the override mandatory for a fresh host. A timer performs bounded health checks without infinite restart storms.

Useful commands:

```bash
systemctl status waterfallhunter.service
systemctl status waterfallhunter-healthcheck.timer
/srv/waterfallhunter/app/scripts/production_compose.sh ps
journalctl -u waterfallhunter.service -n 200 --no-pager
```

## Health

Backend `/livez` is process liveness. `/api/health`/readiness verifies scanner/hunter/database/runtime progress. Frontend and monitoring services have container healthchecks.

## Operations diagrams

See [D02 Runtime Deployment Topology](diagrams/02-runtime-deployment-topology.md), [D14 Observability / Incident Flow](diagrams/14-observability-incident-flow.md), and [D15 CI / Release / Production Certification](diagrams/15-ci-release-production-certification.md).

## Safety

Do not use `docker compose down -v`. Persistent database state must survive runtime replacement. `LIVE_TRADING_ENABLED=false` must remain visible in runtime certification.
