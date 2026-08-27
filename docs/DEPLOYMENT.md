# Deployment

Production deploys only from protected `main` after required CI jobs pass. Pull requests do not receive production credentials.

## Trusted chain

`main push -> backend/frontend/dependency/container/repository checks -> production environment -> exact SHA verification -> backup -> migration -> Compose replacement -> health/revision certification`.

The deployment script refuses a stale SHA, dirty checkout, missing host environment, invalid backup, failed migration preflight, unhealthy services, OCI revision mismatch, or `LIVE_TRADING_ENABLED` drift.

## Production secrets

Secrets are host/GitHub Environment owned and never committed. The canonical host file is `/etc/waterfallhunter/waterfallhunter.env` with restrictive permissions. Release state lives under `/srv/waterfallhunter/runtime`; certified DB backups live under `/srv/waterfallhunter/backups`. The Git checkout contains neither secrets nor deployment state.

## Rollback

Rollback is permitted only when the previous runtime is schema-compatible with the current database. If compatibility cannot be proven, the application is quarantined and the certified backup/evidence is preserved.

## Operator rule

There is deliberately no unreviewed `make deploy` shortcut. Use the guarded GitHub/first-party deployment path.
