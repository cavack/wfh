import assert from "node:assert/strict";
import { dashboardSnapshot } from "../lib/dashboard-contract";

const counts = { ENTRY_READY: 0, FORMING: 0, ACTIVE: 0, LATE: 0, INVALIDATED: 0, EXPIRED: 0, NO_TRADE: 1, UNAVAILABLE: 0 };
const snapshot = {
  contract_version: "dashboard_snapshot_v2", schema_version: "2.0", snapshot_version: 1,
  generated_at: 1, state: "READY", total: 1, candidates: { BAD: null },
  decision_terminal: {
    contract_version: "decision_terminal_v1", counts, entry_ready: [], forming: [], active: [], late: [],
    zero_entry_ready_diagnostics: { entry_ready_zero: true, evaluated_candidates: 1, top_reasons: [] },
    recent_changes: [],
  },
  final_ranking: {}, signal_funnel: {},
};
assert.equal(dashboardSnapshot(snapshot), undefined, "null candidate values must be rejected");
