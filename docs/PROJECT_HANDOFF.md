# WaterfallHunter Project Handoff

## What this is

WaterfallHunter is a `SIGNAL_ONLY` SHORT signal system for linear USDT perpetual futures, focused on pre-trigger/early long-liquidation cascade conditions. It does not place orders.

## Source of truth

- Repository: `https://github.com/cavack/wfh`
- Production branch: `main`
- Runtime checkout: `/srv/waterfallhunter/app`
- Public dashboard edge: nginx -> `127.0.0.1:3000`
- Product invariant: `LIVE_TRADING_ENABLED=false`

Historical chat, ZIP files, old server copies, stale branches, or old repositories are not implementation authority when they conflict with current `main`.

## Decision contract

Only canonical `ENTRY_READY` is a proactive entry signal. `FORMING` is not ready; `ACTIVE` is an already-emitted setup in progress; lifecycle `TRIGGERED` alone is never an entry instruction. The user-facing score is `entry_readiness`.

## Runtime services

Canonical application/observability services are backend, frontend, watchdog, Prometheus, Grafana, and Alertmanager, fronted by host nginx. Docker Compose manages containers; systemd asserts/recoveries the stack after boot.

## Data

The production SQLite database is persistent evidence and must be preserved. Never substitute a fresh DB without an explicit data-loss decision. Use certified backup + migration rehearsal before schema/cutover/destructive cleanup.

## Notifications and AI

Telegram signal delivery is durable and release-cutover scoped. AI/Gemini is optional advisory only and cannot alter decisions. No Ollama/local-model runtime is required unless current main explicitly reintroduces and validates it.

## Start here for any new task

1. `git fetch origin && git checkout main && git pull --ff-only` (or create an isolated worktree from current main).
2. Read `docs/ARCHITECTURE.md`, `docs/MODEL.md`, and the domain-specific doc for your change.
3. Run `make validate` before and after meaningful changes.
4. For releases run `./scripts/validate_clean_install.sh` on a clean exact SHA.
5. For production, follow `docs/DEPLOYMENT.md` and `docs/BACKUP_RESTORE.md`.

## Operations quick reference

```bash
systemctl status waterfallhunter.service
systemctl status waterfallhunter-healthcheck.timer
cd /srv/waterfallhunter/app && docker compose ps
curl -fsS http://127.0.0.1:3000/dashboard/ >/dev/null
```

Secrets are host/GitHub Environment owned and are never included in this handoff.
