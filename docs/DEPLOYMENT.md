# Deployment

Production deploys only from protected `main`, only after required CI jobs pass, and only from an explicit `workflow_dispatch` with `deploy_production=true`. A normal push to `main` runs verification but never deploys; pull requests do not receive production credentials.

## Trusted chain

`main push -> successful exact-SHA CI -> release/backup/migration/rollback certification -> explicit CI workflow dispatch on main with deploy_production=true -> repeated required CI checks -> production environment -> exact SHA verification -> backup -> migration -> Compose replacement -> health/revision certification`.

The deployment script refuses a stale SHA, dirty checkout, missing host environment, invalid backup, failed migration preflight, unhealthy services, OCI revision mismatch, or `LIVE_TRADING_ENABLED` drift. If `/srv/waterfallhunter/runtime/production-volumes.override.yml` exists, deployment, systemd boot, and bounded recovery all compose it with the repository file; on a fresh host the override is optional. The privileged production verifier accepts only the canonical application, environment, health-state, and runtime-certificate locations; CLI path aliases cannot redirect Compose or its writes to arbitrary host paths.

## Production secrets

Secrets are host/GitHub Environment owned and never committed. The canonical host file is `/etc/waterfallhunter/waterfallhunter.env` with restrictive permissions. Release state lives under `/srv/waterfallhunter/runtime`; certified DB backups live under `/srv/waterfallhunter/backups`. The Git checkout contains neither secrets nor deployment state.

## GitHub and host trust paths

The two directions use separate credentials and responsibilities:

- **GitHub Actions → Production:** the GitHub `production` Environment owns `WFH_PROD_HOST`, `WFH_PROD_USER`, `WFH_PROD_SSH_KEY`, and `WFH_PROD_KNOWN_HOSTS`. The workflow pins the host identity and uses that SSH credential only for guarded deployment.
- **Production host → GitHub:** authenticated HTTPS through Git/`gh` is the normal read/write path. A repository-scoped read-only SSH deploy key provides a fallback fetch path and cannot push.

Do not reuse the Production deploy private key as a server-to-GitHub credential, and do not store either private key in the repository. Credential separation limits blast radius and keeps the deployment trust direction explicit.

## Rollback

Rollback is permitted only when the previous runtime is schema-compatible with the current database. If compatibility cannot be proven, the application is quarantined and the certified backup/evidence is preserved.

## Operator rule

There is deliberately no unreviewed `make deploy` shortcut. After exact-SHA release certification, use the guarded GitHub `CI` workflow dispatch on protected `main` with `deploy_production=true`; do not rely on a push to trigger deployment.

## Immutable Production image pinning

The deployer copies each exact CI-tested image to a release-specific `wfh-release-*:<sha>` tag and composes Production through `/srv/waterfallhunter/runtime/production-images.override.yml`. This prevents unrelated worktree builds from changing a mutable repository tag underneath an in-progress deploy or a later systemd restart. Before loading a target bundle, the currently running certified images are also pinned by immutable container image identity for bounded rollback. A release cannot be certified if the running OCI revisions differ from the dispatched SHA.
