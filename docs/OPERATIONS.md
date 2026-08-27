# Operations

## Canonical host paths

- Application checkout: `/srv/waterfallhunter/app`
- Host-owned environment: `/etc/waterfallhunter/waterfallhunter.env`
- Runtime/certification state: `/srv/waterfallhunter/runtime`
- Certified backups: `/srv/waterfallhunter/backups`

## Runtime

Docker Compose manages backend, frontend, watchdog, Prometheus, Grafana, and Alertmanager. Nginx is the host edge. `waterfallhunter.service` asserts the Compose stack after boot; a timer performs bounded health checks without infinite restart storms.

Useful commands:

```bash
systemctl status waterfallhunter.service
systemctl status waterfallhunter-healthcheck.timer
docker compose -f /srv/waterfallhunter/app/docker-compose.yml ps
journalctl -u waterfallhunter.service -n 200 --no-pager
```

## Health

Backend `/livez` is process liveness. `/api/health`/readiness verifies scanner/hunter/database/runtime progress. Frontend and monitoring services have container healthchecks.

## Safety

Do not use `docker compose down -v`. Persistent database state must survive runtime replacement. `LIVE_TRADING_ENABLED=false` must remain visible in runtime certification.
