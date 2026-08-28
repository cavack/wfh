# Deployment

Production deploys only from protected `main`, only after required CI jobs pass, and only from an explicit `workflow_dispatch` with `deploy_production=true`. A normal push to `main` runs verification but never deploys; pull requests do not receive production credentials.

## Trusted chain

`main push -> successful exact-SHA CI -> release/backup/migration/rollback certification -> explicit CI workflow dispatch on main with deploy_production=true -> repeated required CI checks -> production environment -> exact SHA verification -> backup -> migration -> Compose replacement -> health/revision certification`.

The deployment script refuses a stale SHA, dirty checkout, missing host environment, invalid backup, failed migration preflight, unhealthy services, OCI revision mismatch, or `LIVE_TRADING_ENABLED` drift. If `/srv/waterfallhunter/runtime/production-volumes.override.yml` exists, deployment, systemd boot, and bounded recovery all compose it with the repository file; on a fresh host the override is optional. The privileged production verifier accepts only the canonical application, environment, health-state, and runtime-certificate locations; CLI path aliases cannot redirect Compose or its writes to arbitrary host paths.

## Production secrets

Secrets are host/GitHub Environment owned and never committed. The canonical host file is `/etc/waterfallhunter/waterfallhunter.env` with restrictive permissions. Release state lives under `/srv/waterfallhunter/runtime`; certified DB backups live under `/srv/waterfallhunter/backups`. The Git checkout contains neither secrets nor deployment state.

## Rollback

Rollback is permitted only when the previous runtime is schema-compatible with the current database. If compatibility cannot be proven, the application is quarantined and the certified backup/evidence is preserved.

## Operator rule

There is deliberately no unreviewed `make deploy` shortcut. After exact-SHA release certification, use the guarded GitHub `CI` workflow dispatch on protected `main` with `deploy_production=true`; do not rely on a push to trigger deployment.
