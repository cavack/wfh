# TWFH Resume Contract

Project: `TWFH`
Repository: `cavack/wfh`
Protocol: `wfh_mission_continuity_v1`
Council route: `mission_continuity`
Canonical phrase: `ادامه کار گروهی`

When this phrase is used in the TWFH ChatGPT Project, Chat, Work, Codex, or another authorized project-aware agent surface, resolve:

`TWFH -> cavack/wfh -> active mission -> latest certified checkpoint -> exact next action`

Required behavior:
1. Do not restart from zero.
2. Do not rely on transcript memory as the source of truth.
3. Resolve the active mission and latest checkpoint from durable mission control.
4. Verify checkpoint integrity, current repository/Production provenance, registered branch/head/worktree, and worktree cleanliness when the required capabilities are available.
5. If work stopped mid-step, return `RECONCILIATION_REQUIRED` and reconcile side effects before retrying.
6. If state drifted, return `DRIFT_DETECTED`; do not silently reuse stale evidence.
7. If a required capability/control source is unavailable, return `RESUME_BLOCKED` with the exact missing prerequisite.
8. If valid, return `RESUME_READY` and continue from the checkpoint's exact `next_action`.

Current initial active mission contract: `WFH-ME-V3-20260902` (`WaterfallHunter Model Excellence v3`). The active-mission pointer may later select a successor without changing the meaning of the resume phrase.

Mission Control never authorizes model/Production changes by itself. Existing WaterfallHunter skill ownership, scientific gates, release certification, `LIVE_TRADING_ENABLED=false`, and no-live-order policy remain authoritative.
