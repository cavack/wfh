---
name: safe-remote-compose-deployment
description: Use when deploying a Git revision from CI or GitHub to a long-lived remote host running Docker Compose, especially when the host has persistent state or rollback requirements.
---

# Safe Remote Compose Deployment

## Core rule

Treat deployment as a reversible state transition: verify source and host state first, prepare the new artifact without disturbing the running services, cut over only after read-only preflight succeeds, then prove health or restore the previous state.

## Required sequence

1. **Verify authority and source**
   - Deploy only an explicitly selected immutable revision.
   - Require upstream CI success for that exact revision.
   - Never deploy an arbitrary branch tip supplied by untrusted input.

2. **Protect credentials and transport**
   - Keep SSH keys, host, user, and known-host material in secret storage.
   - Require pinned host-key verification.
   - Never use `StrictHostKeyChecking=no`, print secrets, source untrusted env files, or interpolate unvalidated shell input.

3. **Capture rollback state before mutation**
   - Record the current Git revision and running image IDs.
   - Refuse dirty remote worktrees unless the operator explicitly resolves them first.
   - Preserve persistent data; do not treat application rollback as database rollback.

4. **Prepare before cutover**
   - Validate Compose configuration.
   - Build/pull the target artifact.
   - Run read-only schema/config compatibility checks against the target artifact.
   - Never hide migration inside deployment. A write migration needs its own explicit gate and rollback evidence.

5. **Bound the cutover**
   - Restart/update only the services in scope.
   - Use a finite health deadline.
   - Verify running image/revision identity, not just process existence.
   - Run at least one application-level smoke check.

6. **Rollback on any post-prepare failure**
   - Restore previous image tags/references and previous source revision.
   - Restart the previous application services if cutover occurred.
   - Re-check health after rollback.
   - Return failure even if rollback succeeds so CI records the failed deployment.

## Fail-closed conditions

Stop before cutover on source mismatch, dirty worktree, missing secrets/config, unsafe env state, schema incompatibility, build failure, or inability to identify rollback images.

Stop and roll back after cutover on health timeout, revision-label mismatch, or smoke-test failure.

## Common mistakes

- Rebuilding over the only tag without first remembering the old image IDs.
- Auto-applying migrations because the new application expects them.
- Checking only `docker ps` instead of container health and application smoke endpoints.
- Allowing deployment to continue after rollback evidence is incomplete.
- Assuming a successful deploy is authorization to enable unrelated runtime features.