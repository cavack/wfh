import importlib.util
import json
import sqlite3
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("compiler", Path(__file__).parents[2] / "scripts/research/compile_normalized_dataset.py")
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)
ANALYZER_SPEC = importlib.util.spec_from_file_location(
    "analyzer", Path(__file__).parents[2] / "scripts/research/analyze_model_crosswalk.py"
)
analyzer = importlib.util.module_from_spec(ANALYZER_SPEC)
ANALYZER_SPEC.loader.exec_module(analyzer)


def db(tmp_path):
    p = tmp_path / "source.db"
    with sqlite3.connect(p) as c:
        c.executescript("""
        CREATE TABLE lbank_signal_ledger (id INTEGER PRIMARY KEY, symbol TEXT, triggered_at INTEGER, state_before TEXT, score REAL, entry_price REAL, position_setup_json TEXT);
        CREATE TABLE lbank_signal_outcomes (id INTEGER PRIMARY KEY, signal_id INTEGER, symbol TEXT, outcome_status TEXT, horizon_seconds INTEGER, observation_started_at INTEGER, min_price REAL, max_price REAL, observed_candles INTEGER, expected_candles INTEGER, details_json TEXT, price_source TEXT, resolved_at INTEGER, gross_realized_r REAL);
        CREATE TABLE production_evidence_snapshots (id INTEGER PRIMARY KEY, symbol TEXT, observed_at REAL, code_sha256_v5 TEXT, evidence_zlib BLOB, valid_candle_timeframes INTEGER, suggested_status TEXT);
        """)
        c.execute("INSERT INTO lbank_signal_ledger VALUES (1,'BTC',100,'TRIGGERED',80,10,'{}')")
        c.execute("INSERT INTO lbank_signal_ledger VALUES (2,'ETH',200,'ARMED',50,20,'{}')")
        c.execute("INSERT INTO lbank_signal_ledger VALUES (3,'XRP',300,'ARMED',50,20,'{}')")
        c.execute("INSERT INTO lbank_signal_ledger VALUES (4,'SOL',400,'ARMED',50,20,'{}')")
    return p


def test_compilation_is_deterministic_and_manifest_has_all_statuses(tmp_path):
    p = db(tmp_path)
    with sqlite3.connect(p) as c:
        c.execute("INSERT INTO lbank_signal_outcomes VALUES (1,1,'BTC','COMPLETE',60,101,9,12,3,3,'{\"gross_r\":1,\"fees\":0.1,\"slippage\":0.1,\"funding\":0,\"net_r\":0.8}','ohlcv',200,1)")
        c.execute("INSERT INTO lbank_signal_outcomes VALUES (2,2,'ETH','COMPLETE',60,201,9,12,2,3,'{}','ohlcv',300,1)")
        c.execute("INSERT INTO lbank_signal_outcomes VALUES (3,3,'XRP','COMPLETE',60,301,9,12,3,3,'{}','ohlcv',400,1)")
        c.execute("INSERT INTO lbank_signal_outcomes VALUES (4,3,'XRP','COMPLETE',60,301,9,12,3,3,'{}','ohlcv',400,1)")
        c.execute("INSERT INTO lbank_signal_outcomes VALUES (5,4,'SOL','COMPLETE',60,399,'nan',12,3,3,'{}','ohlcv',500,1)")
    a = compiler.compile_dataset(p, tmp_path / "a")
    b = compiler.compile_dataset(p, tmp_path / "b")
    assert a["jsonl_sha256"] == b["jsonl_sha256"]
    assert a["status_counts"] == {"PENDING": 0, "COMPLETE": 1, "INSUFFICIENT_WINDOW": 1, "MISSING_MARKET_DATA": 0, "INVALID_LEVELS": 1, "DUPLICATE_LINK": 1, "PROVENANCE_MISMATCH": 0}
    assert a["scientifically_eligible_count"] == 1
    assert (tmp_path / "a/manifest.json").read_bytes() == (tmp_path / "b/manifest.json").read_bytes()


def test_null_fields_have_explicit_reasons_and_provenance_mismatch(tmp_path):
    p = db(tmp_path)
    with sqlite3.connect(p) as c:
        c.execute("INSERT INTO lbank_signal_outcomes VALUES (1,1,'BTC','COMPLETE',60,101,9,12,3,3,'{}','ohlcv',200,1)")
        import zlib
        payload = json.dumps({"source_tree_sha256": "b" * 64}).encode()
        c.execute("INSERT INTO production_evidence_snapshots VALUES (1,'BTC',101,?, ?, 1, 'ARMED')", ("a" * 64, zlib.compress(payload)))
    m = compiler.compile_dataset(p, tmp_path / "out")
    row = json.loads((tmp_path / "out/normalized_research.jsonl").read_text().splitlines()[0])
    assert row["outcome"]["status"] == "PROVENANCE_MISMATCH"
    assert row["lifecycle_v2_shadow"] == {"value": None, "reason": "no_linked_shadow_event"}
    assert row["outcome"]["costs"]["fees"]["reason"] == "cost_not_recorded"


def test_missing_and_stale_outcomes_are_not_promoted(tmp_path):
    p = db(tmp_path)
    with sqlite3.connect(p) as c:
        c.execute(
            "INSERT INTO lbank_signal_outcomes VALUES "
            "(1,1,'BTC','COMPLETE',60,99,9,12,3,3,'{}','ohlcv',200,1)"
        )
    compiler.compile_dataset(p, tmp_path / "out")
    rows = [
        json.loads(line)
        for line in (tmp_path / "out/normalized_research.jsonl").read_text().splitlines()
    ]
    by_id = {row["signal_id"]: row for row in rows}
    assert by_id[1]["outcome"]["status"] == "INVALID_LEVELS"
    assert by_id[2]["outcome"]["status"] == "MISSING_MARKET_DATA"
    assert by_id[2]["outcome"]["reasons"] == ["outcome_row_unavailable"]


def test_p0d_outputs_explicit_not_run_without_runtime_outcomes(tmp_path):
    crosswalk, reuse = analyzer.run(tmp_path / "missing.jsonl", tmp_path / "artifacts")
    assert crosswalk["status"] == analyzer.NOT_RUN
    assert crosswalk["matched_packet_count"] == 0
    assert reuse["status"] == analyzer.NOT_RUN
    assert (tmp_path / "artifacts/MODEL_LAYER_CROSSWALK.json").exists()
    assert (tmp_path / "artifacts/EVIDENCE_REUSE_MATRIX.json").exists()


def test_p0d_reports_matched_transitions_blockers_and_deltas(tmp_path):
    row = {
        "packet_id": 1, "lifecycle_v1": {"value": "ARMED", "reason": None},
        "readiness": {"value": 70, "reason": None}, "coverage": {"value": 80, "reason": None},
        "availability": {"value": {"ohlcv": True}, "reason": None},
        "acquisition_path": {"value": {"source": "ws"}, "reason": None},
        "freshness": {"value": {"age": 1}, "reason": None},
        "components": {"value": {}, "reason": None}, "gates": {"value": {}, "reason": None},
        "trade_plan": {"value": {}, "reason": None},
        "outcome": {"status": "COMPLETE", "reasons": ["cost_not_recorded"],
                    "expected_candles": {"value": 10}, "observed_candles": {"value": 8}},
    }
    crosswalk, reuse = analyzer.analyze([row])
    assert crosswalk["matched_packet_count"] == 1
    assert crosswalk["decision_transitions"] == {"ARMED->70": 1}
    assert crosswalk["first_blockers"] == {"cost_not_recorded": 1}
    assert crosswalk["readiness_coverage_deltas"]["readiness_minus_coverage"]["mean"] == -10
    assert crosswalk["readiness_coverage_deltas"]["observed_minus_expected_candles"]["mean"] == -2
    assert reuse["families"][0]["rows"] == 1


def test_decision_event_is_primary_and_packet_is_canonical(tmp_path):
    p = db(tmp_path)
    with sqlite3.connect(p) as c:
        c.execute(
            "CREATE TABLE entry_decision_events (id INTEGER PRIMARY KEY, symbol TEXT, event_at INTEGER, decision TEXT, lifecycle_state TEXT, entry_readiness REAL, evidence_coverage_pct REAL, policy_version TEXT, packet_json TEXT, packet_hash TEXT, created_at INTEGER)"
        )
        packet = {"decision": "FORMING", "entry_readiness": 12.5, "evidence_coverage_pct": 33.0,
                  "lifecycle_state": "WATCH", "metrics": {}, "capture_limitations": {}}
        c.execute("INSERT INTO entry_decision_events VALUES (1,'BTC',100,'READY', 'WATCH',99,99,'v1',?,'hash',100)",
                  (json.dumps(packet),))
    compiler.compile_dataset(p, tmp_path / "out")
    row = json.loads((tmp_path / "out/normalized_research.jsonl").read_text().splitlines()[0])
    assert row["candidate_evaluation_id"] == 1
    assert row["decision"] == {"value": "FORMING", "reason": None}
    assert row["readiness"] == {"value": 12.5, "reason": None}
    assert row["coverage"] == {"value": 33.0, "reason": None}
    assert row["acquisition_path"] == {"value": None, "reason": "acquisition_path_unavailable_non_causal"}
