CREATE TABLE entry_decision_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    event_at INTEGER NOT NULL,
    decision TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL,
    entry_readiness REAL NOT NULL,
    evidence_coverage_pct REAL NOT NULL,
    policy_version TEXT NOT NULL,
    packet_json TEXT NOT NULL,
    packet_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    CHECK(typeof(symbol) = 'text' AND length(symbol) > 0),
    CHECK(typeof(event_at) = 'integer' AND event_at >= 0),
    CHECK(decision IN ('NO_TRADE','FORMING','ENTRY_READY','ACTIVE','LATE','INVALIDATED','EXPIRED')),
    CHECK(typeof(entry_readiness) IN ('integer','real') AND entry_readiness >= 0 AND entry_readiness <= 100),
    CHECK(typeof(evidence_coverage_pct) IN ('integer','real') AND evidence_coverage_pct >= 0 AND evidence_coverage_pct <= 100),
    CHECK(json_valid(packet_json)),
    CHECK(length(packet_hash) = 64 AND packet_hash NOT GLOB '*[^0-9a-f]*'),
    CHECK(typeof(created_at) = 'integer' AND created_at >= 0)
);

CREATE INDEX idx_entry_decision_symbol_event
ON entry_decision_events(symbol, event_at, id);

CREATE INDEX idx_entry_decision_decision_event
ON entry_decision_events(decision, event_at);

CREATE TRIGGER entry_decision_events_no_update
BEFORE UPDATE ON entry_decision_events
BEGIN
    SELECT RAISE(ABORT, 'entry decision events are immutable');
END;

CREATE TRIGGER entry_decision_events_no_delete
BEFORE DELETE ON entry_decision_events
BEGIN
    SELECT RAISE(ABORT, 'entry decision events are immutable');
END;

PRAGMA user_version=6;
