## Summary

Describe the change and why it is needed.

## Safety

- [ ] `LIVE_TRADING_ENABLED=false` remains unchanged.
- [ ] No credentials, runtime databases, evidence packets, logs, backups, or generated datasets are committed.
- [ ] No strategy threshold or execution gate is promoted without documented validation.
- [ ] Only canonical `ENTRY_READY` remains proactively actionable; no parallel score/ranking is presented as an entry signal.

## Validation

- [ ] Backend tests pass.
- [ ] Frontend typecheck and production build pass.
- [ ] Dependency audits pass.
- [ ] Docker Compose validation/build passes when container files changed.
- [ ] Documentation/configuration are updated when behavior changes.
- [ ] `docs/PROJECT_HANDOFF.md` is updated when architecture, operations, deployment, data ownership, or decision semantics change.

## Operational impact

Document migrations, environment changes, deployment considerations, or state compatibility concerns. Use `None` when there is no operational impact.
