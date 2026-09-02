# TWFH Agent Entry Contract

This repository is the canonical WaterfallHunter engineering repository `cavack/wfh` for the ChatGPT Project folder `TWFH`.

## Canonical resume intent

When the user says exactly `ادامه کار گروهی`, treat it as the TWFH active-mission resume intent governed by `wfh_mission_continuity_v1` and Council route `mission_continuity`.

Do not interpret it as “start a WaterfallHunter audit” and do not ask the user to restate previous work when durable mission state is available.

Before repository work:
1. Read `docs/chatgpt-project/00-WFH-CHATGPT-ROUTER-v2.md`.
2. Read `docs/mission-control/README.md` when present.
3. Run `python scripts/wfh_mission.py resume --phrase "ادامه کار گروهی" --json` when the mission-control CLI is available.
4. Reconcile any `RECONCILIATION_REQUIRED`, `DRIFT_DETECTED`, or `RESUME_BLOCKED` result before continuing.
5. Continue only from the exact `next_action` and required preconditions in the latest valid checkpoint.

## Persistent context

`AGENTS.md` is only the entry map. Durable mission state belongs to GitHub mission control and host mission artifacts, not to this file or the chat transcript.

## Safety

Preserve WaterfallHunter protected invariants and signal-only policy. `LIVE_TRADING_ENABLED=false`; no live order placement is authorized by Mission Control.
