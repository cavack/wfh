# WaterfallHunter Runtime Schema Ownership Inventory

**Inventory baseline:** `feat/wave1b-migration-readiness-v1`, inherited from Wave 1A/Wave 0 and canonical `main` source. Refresh this search before Wave 1B2 cutover.

**Purpose:** identify runtime code that currently owns or mutates SQLite schema so the later migration-runner cutover does not silently omit a store.

## Search method

Repository-wide source search was performed for:

- `CREATE TABLE`
- `CREATE INDEX`
- `CREATE TRIGGER`
- `ALTER TABLE`
- `PRAGMA table_info`

B1 does not remove or rewrite these sites. B2 must reconcile each runtime source owner with versioned migrations and verify-only runtime behavior.

## Runtime/source mutation sites

| Source file | Current role | Mutation class | B2 disposition |
| --- | --- | --- | --- |
| `backend/src/waterfallhunter/core/db.py` | LBank catalog/event persistence | Business/operational schema; `CREATE TABLE`; migration-like `PRAGMA table_info` + `ALTER TABLE` | HIGH-priority cutover. Move catalog/event schema and legacy column evolution into migrations; constructor becomes verify/use only. |
| `backend/src/waterfallhunter/core/lbank_signal_ledger.py` | Immutable signal ledger | Canonical signal persistence schema; tables/indexes/triggers; migration-like `PRAGMA table_info` + `ALTER TABLE` | HIGH-priority cutover before W1-C. Preserve ledger immutability triggers and atomic signal/CAS semantics. |
| `backend/src/waterfallhunter/core/lbank_signal_outcome.py` | Immutable signal outcomes | Outcome schema/indexes/immutability triggers | Cut over to migrations; preserve FK and append-only semantics. |
| `backend/src/waterfallhunter/core/stage_lifecycle.py` | Lifecycle persistence | Lifecycle/observational schema | Cut over without changing current lifecycle semantics; Lifecycle V2 promotion is a later model workstream. |
| `backend/src/waterfallhunter/core/production_evidence.py` | Production evidence persistence | Evidence/replay schema; includes migration-like column evolution | HIGH-priority cutover; preserve historical evidence/provenance and never rewrite existing evidence rows. |
| `backend/src/waterfallhunter/core/feature_replay.py` | Feature replay persistence | Research/replay schema | Cut over; preserve replay determinism and hashes. |
| `backend/src/waterfallhunter/core/lbank_execution_store.py` | Current/history LBank execution observation | Observational execution schema/indexes; source search also finds `ALTER TABLE` patterns in this module family | Cut over; preserve read-only execution observation semantics. |
| `backend/src/waterfallhunter/core/lbank_execution_decision.py` | Execution decision/evidence persistence | Observational decision schema | Cut over; must remain non-trading and non-authoritative for signal eligibility unless separately designed. |
| `backend/src/waterfallhunter/core/historical_outcome_store.py` | Imported/historical outcome persistence | Research/historical schema | Cut over; preserve historical-vs-production provenance separation. |
| `backend/src/waterfallhunter/core/provider_registry.py` | Provider operational state | Operational schema | Cut over or explicitly retire only after current gateway/provider consumers are mapped. |

## Reviewed runtime files that are not schema owners

A fresh DDL search found no `CREATE TABLE`, `CREATE INDEX`, `CREATE TRIGGER`,
`ALTER TABLE`, or `PRAGMA table_info` ownership in these files. They are
therefore excluded from the B2 schema-owner queue unless later source changes
introduce explicit DDL:

- `backend/src/waterfallhunter/core/ws_streamer.py`
- `backend/src/waterfallhunter/core/lbank_execution.py`
- `backend/src/waterfallhunter/main.py`

## Script/test-only schema sites

These are not runtime schema owners but matter for parity and test methodology:

| Source file | Role | B2 treatment |
| --- | --- | --- |
| `scripts/historical_backtest.py` | Historical/backtest disposable schema | Keep isolated from Production migration ownership; ensure backtest schema is explicitly research-only. |
| `backend/tests/test_lbank_signal_ledger.py` and other tests | Test fixture schema/assertions | Update fixtures to migration-runner setup when B2 cuts over runtime constructors. |
| historical docs/plans under `docs/superpowers/` | Design examples containing SQL | Documentation only; not executable schema ownership. |

## Explicit `ALTER TABLE` / migration-like sites found

Repository search currently identifies runtime migration-like evolution in at least:

- `backend/src/waterfallhunter/core/db.py`
- `backend/src/waterfallhunter/core/lbank_signal_ledger.py`
- `backend/src/waterfallhunter/core/production_evidence.py`
- `backend/src/waterfallhunter/core/lbank_execution_store.py`

`PRAGMA table_info` checks currently appear in at least:

- `backend/src/waterfallhunter/core/db.py`
- `backend/src/waterfallhunter/core/lbank_signal_ledger.py`
- `backend/src/waterfallhunter/core/production_evidence.py`

These sites are the clearest evidence of schema evolution occurring implicitly at runtime and are mandatory B2 targets.

## B1 ownership boundary

Wave 1B1 introduces only two migration-runner-owned schema objects:

1. `schema_migrations` + its immutability triggers (runner bootstrap metadata)
2. `db_readiness_probe` (versioned migration `0001_db_readiness_probe.sql`)

B1 intentionally leaves every business/evidence/execution runtime constructor unchanged. This avoids mixing migration-framework correctness with a broad schema cutover.

## B2 exit criteria

Before W1-C starts, B2 must:

- refresh this inventory;
- extract all required existing runtime schema into ordered migrations or an explicitly validated baseline migration strategy;
- migrate legacy column evolution from constructor logic into migrations;
- change runtime stores from create/alter behavior to schema verification/use;
- prove clean-install behavior;
- prove upgrade behavior from representative legacy schemas;
- preserve immutable ledger/outcome/evidence triggers and FKs;
- preserve all existing tests/model semantics;
- fail closed on missing/incompatible schema rather than silently recreating it.

No Production migration is implied by completing B2 development work. Production execution remains gated by fresh verified backup/restore and separate `MIGRATION_APPROVAL`.
