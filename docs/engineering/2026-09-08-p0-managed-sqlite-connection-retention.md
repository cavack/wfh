# P0 Managed SQLite Connection-Retention Decision Record

Target Production revision at diagnosis: `2828a59df4722fd8e34bc901261beeac1c631014`.

This incident was discovered during post-activation certification of PR #134. It is separate from the prior CCXT/WebSocket ownership defects and does not invalidate the Feature Replay primary-key frontier correction.

## Evidence classification

- `VERIFIED_FACT`: Production remained on exact revision `2828a59...`, backend health stayed available, `RestartCount=0`, `OOMKilled=false`, and the product remained `SIGNAL_ONLY` throughout diagnosis.
- `VERIFIED_FACT`: a synchronized 600-second sample showed private process memory dominating RSS/PSS while cgroup `memory.events:max` increased by `6347`; no OOM kill occurred.
- `VERIFIED_FACT`: total CCXT client ownership remained non-monotonic/bounded during the same investigation, so the old simple WebSocket-client leak does not explain this event.
- `REPRODUCED_DEFECT`: Production FD count reached `233`; a direct classification near the same pressure episode found `113` descriptors for `waterfall_registry.db`, `6` for its WAL and `1` for SHM, while sockets were only `39`.
- `VERIFIED_FACT`: across the 600-second sample, RSS correlated strongly with total FD count (`r≈0.843`) and with non-socket FD count used as a DB-FD proxy (`r≈0.830`).
- `VERIFIED_FACT`: at the existing periodic GC/heap-trim boundary, FD count fell `161 → 47`, heap RSS fell by about `127 MiB`, and process RSS fell about `269 MiB` in one sample interval.
- `REPRODUCED_DEFECT`: on the exact Production backend image, 100 ordinary `with connect_managed_sqlite(...)` operations left `69` SQLite connections/FDs live until explicit cyclic GC; 200 operations with GC disabled retained `200` main DB and `200` WAL descriptors.
- `REPRODUCED_DEFECT`: the regression `test_managed_connection_context_closes_immediately` fails on unmodified `main` because the connection remains usable after the `with` block.

## Root cause

`connect_managed_sqlite()` returns a native `sqlite3.Connection`. Python's SQLite connection context manager commits or rolls back but does **not** close the connection when leaving `with`. Many high-frequency WaterfallHunter stores use that factory directly as a context manager.

Those connection objects are cyclic-GC tracked. Between collection cycles they retain SQLite handles, database/WAL descriptors, page-cache/native allocations and Python/native heap state. The hunter's existing five-minute `gc.collect()` plus `malloc_trim(0)` periodically releases much of that retained working set, producing the observed sawtooth rather than deterministic per-operation reclamation. Under the 2 GiB cgroup, the high side of that sawtooth repeatedly forces reclaim and `memory.events:max` increments.

The mechanism is causal rather than inferred from code shape alone: Production shows the DB-FD/RSS correlation and synchronized release; the exact release image reproduces connection retention; and the same workload on corrected source retains zero DB/WAL FDs and flat RSS.

## Selected correction

Keep `connect_managed_sqlite()` API-compatible by returning a `sqlite3.Connection` subclass. Override only context-manager exit: preserve the native commit/rollback result, then always close in `finally`.

Direct callers that intentionally manage connection lifetime remain compatible because the returned object is still a `sqlite3.Connection`. Existing explicit `close()` paths remain valid. The separate `managed_connection()` wrapper remains supported; removing it would be unrelated cleanup.

This is preferred over periodic forced GC, shorter trim intervals, a higher memory limit, or broad store rewrites. Those alternatives either mask the lifetime bug or expand blast radius without repairing ownership.

## RED → GREEN evidence

RED on exact current source: `test_managed_connection_context_closes_immediately` fails because a connection can still execute SQL after leaving the context.

GREEN after the correction:

- managed-SQLite regression file: `6 passed`;
- managed-SQLite + runtime-memory + Feature Replay neighboring matrix in the exact backend image: `20 passed`;
- isolated 200-operation lifetime probe with GC disabled: `0` residual DB FDs, `0` residual WAL FDs, flat RSS, and explicit GC collected `0` related objects.

Full backend/repository/CI and Production soak evidence are still required before production certification.
