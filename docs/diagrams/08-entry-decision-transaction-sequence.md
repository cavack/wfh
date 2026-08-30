# D08 — Entry Decision Transaction Sequence

Source baseline: `main@65c063ffea6209ecd84b224656bbc627ff811898`

## Purpose

Show the exact persistence-before-notification boundary for canonical entry decisions and the observational-only AI advisory path.

Authoritative references: `backend/src/waterfallhunter/core/entry_decision.py`, `backend/src/waterfallhunter/core/entry_decision_store.py`, migration `0006_entry_decisions.sql`, migration `0007_entry_decision_advisories.sql`.

```mermaid
sequenceDiagram
    participant Eval as Candidate evaluator
    participant Engine as EntryDecision engine
    participant Store as EntryDecisionStore
    participant DB as Managed SQLite transaction
    participant Outbox as entry_notification_outbox
    participant API as API / SSE
    participant Worker as DurableNotificationWorker
    participant TG as Telegram
    participant AI as Optional AI advisory

    Eval->>Engine: canonical evidence + lifecycle + clocks
    Engine-->>Eval: entry_decision_v1 packet
    Eval->>Store: append_if_changed(symbol, packet, lifecycle_id)
    Store->>DB: BEGIN IMMEDIATE + lifecycle CAS check
    DB->>DB: append immutable entry_decision_events row
    alt decision == ENTRY_READY
        DB->>Outbox: insert PENDING entry_ready_notification_v1 event
    end
    DB-->>Store: commit decision identity
    Store-->>Eval: decision_event_id
    Eval-->>API: committed canonical state becomes visible

    AI-->>Store: append observational advisory
    Note over AI,Store: advisory cannot mutate the canonical decision

    Outbox-->>Worker: lease eligible committed event
    Worker->>TG: send only after delivery gates pass
    TG-->>Worker: success / 429 / failure / uncertain outcome
    Worker->>Outbox: persist delivery state
```

## Transaction boundary

`EntryDecisionStore.append_if_changed()` opens `BEGIN IMMEDIATE`, validates the expected catalogue lifecycle, appends the immutable `entry_decision_events` row, and—only for `ENTRY_READY`—inserts the corresponding `entry_notification_outbox` row before the transaction completes. If the store returns no committed event identity, there is no canonical network notification material to send.

## Advisory boundary

AI advisory rows are persisted separately in `entry_decision_advisories`. The store requires `observational_only=true` and `decision_mutated=false`; an unavailable advisory can be materialized without blocking canonical delivery after the configured grace window.

## Safety boundary

Notification is downstream of committed decision state. Delivery success/failure cannot redefine `EntryDecision`, and there is no order-placement step in this sequence.
