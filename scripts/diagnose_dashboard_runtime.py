#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from collections import Counter


def run(args: list[str], *, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("$ " + " ".join(args), flush=True)
    p = subprocess.run(args, input=input_text, text=True, capture_output=True)
    if p.stdout:
        print(p.stdout, end="")
    if p.stderr:
        print(p.stderr, end="")
    if check and p.returncode != 0:
        raise SystemExit(p.returncode)
    return p


def docker_exec_python(code: str) -> str:
    p = subprocess.run(
        ["docker", "exec", "-i", "waterfall-backend", "/opt/venv/bin/python", "-"],
        input=code,
        text=True,
        capture_output=True,
    )
    if p.stderr:
        print(p.stderr, end="")
    if p.returncode != 0:
        raise SystemExit(p.returncode)
    return p.stdout


print("=== DASHBOARD RUNTIME DIAGNOSTIC (READ ONLY) ===")

# 1) Container / volume identity
inspect = subprocess.run(
    [
        "docker", "inspect", "waterfall-backend",
        "--format", "{{.Config.Image}}|{{range .Mounts}}{{if eq .Destination \"/app/data\"}}{{.Name}}{{end}}{{end}}",
    ],
    text=True,
    capture_output=True,
    check=True,
).stdout.strip()
image, current_volume = inspect.split("|", 1)
print(f"BACKEND_IMAGE={image}")
print(f"CURRENT_DATA_VOLUME={current_volume}")

# 2) Fetch live backend payloads inside the container.
api_code = r'''
import json, urllib.request, urllib.error

def fetch(paths):
    for path in paths:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=10) as r:
                body = r.read().decode("utf-8")
                print(json.dumps({"path": path, "status": r.status, "payload": json.loads(body)}, separators=(",", ":")))
                return
        except Exception as exc:
            print(json.dumps({"path": path, "error": f"{type(exc).__name__}: {exc}"}, separators=(",", ":")))

fetch(["/api/candidates", "/dashboard/api/candidates"])
fetch(["/api/historical-outcomes", "/dashboard/api/historical-outcomes"])
'''
api_out = docker_exec_python(api_code)
records = []
for line in api_out.splitlines():
    try:
        records.append(json.loads(line))
    except Exception:
        print("API_RAW=" + line)

candidate_payload = None
historical_payload = None
for item in records:
    print("API_RESULT=" + json.dumps({k: v for k, v in item.items() if k != "payload"}, sort_keys=True))
    if item.get("status") == 200 and isinstance(item.get("payload"), dict):
        if "candidates" in item["payload"]:
            candidate_payload = item["payload"]
        if "operational" in item["payload"] and "summary" in item["payload"]:
            historical_payload = item["payload"]

# 3) Candidate state / trigger / leverage audit.
print("\n=== CANDIDATE PAYLOAD ===")
if not isinstance(candidate_payload, dict):
    print("CANDIDATE_PAYLOAD=UNAVAILABLE")
else:
    candidates = candidate_payload.get("candidates") or {}
    if not isinstance(candidates, dict):
        candidates = {}
    status_counts = Counter()
    signal_counts = Counter()
    combo_counts = Counter()
    data_counts = Counter()
    triggered = []
    leverage_present = []
    leverage_missing_on_ready = []

    for symbol, candidate in candidates.items():
        if not isinstance(candidate, dict):
            continue
        status = str(candidate.get("status") or "<missing>")
        signal_class = str(candidate.get("signal_class") or "<missing>")
        data_status = str(candidate.get("data_status") or "<missing>")
        status_counts[status] += 1
        signal_counts[signal_class] += 1
        combo_counts[(signal_class, status)] += 1
        data_counts[data_status] += 1

        metrics = candidate.get("metrics") if isinstance(candidate.get("metrics"), dict) else {}
        leverage = metrics.get("applied_leverage")
        ready = (
            metrics.get("score_version") == "score_v2"
            and metrics.get("trade_eligible") is True
            and isinstance(metrics.get("score"), (int, float))
        )
        row = {
            "symbol": symbol,
            "status": status,
            "signal_class": signal_class,
            "data_status": data_status,
            "score": candidate.get("score"),
            "metrics_score": metrics.get("score"),
            "trade_eligible": metrics.get("trade_eligible"),
            "applied_leverage": leverage,
            "analysis_status": candidate.get("analysis_status"),
            "persisted_state": candidate.get("persisted_state"),
            "fresh_analysis_state": candidate.get("fresh_analysis_state"),
        }
        if status == "TRIGGERED":
            triggered.append(row)
        if isinstance(leverage, (int, float)):
            leverage_present.append(row)
        if ready and not isinstance(leverage, (int, float)):
            leverage_missing_on_ready.append(row)

    print("CANDIDATE_TOTAL=" + str(len(candidates)))
    print("STATUS_COUNTS=" + json.dumps(dict(status_counts), sort_keys=True))
    print("SIGNAL_CLASS_COUNTS=" + json.dumps(dict(signal_counts), sort_keys=True))
    print("DATA_STATUS_COUNTS=" + json.dumps(dict(data_counts), sort_keys=True))
    print("SIGNAL_STATUS_COMBOS=" + json.dumps({f"{k[0]}|{k[1]}": v for k, v in combo_counts.items()}, sort_keys=True))
    print("TRIGGERED_COUNT=" + str(len(triggered)))
    print("STRICT_TRIGGERED_COUNT=" + str(sum(1 for r in triggered if r["signal_class"] == "STRICT")))
    print("TRIGGERED_ROWS=" + json.dumps(triggered[:20], sort_keys=True))
    print("LEVERAGE_PRESENT_COUNT=" + str(len(leverage_present)))
    print("LEVERAGE_ROWS=" + json.dumps(leverage_present[:20], sort_keys=True))
    print("READY_WITHOUT_LEVERAGE_COUNT=" + str(len(leverage_missing_on_ready)))
    print("READY_WITHOUT_LEVERAGE_ROWS=" + json.dumps(leverage_missing_on_ready[:20], sort_keys=True))

# 4) Historical API contract.
print("\n=== HISTORICAL OUTCOMES API ===")
if isinstance(historical_payload, dict):
    print("HISTORICAL_AVAILABLE=" + str(historical_payload.get("available")))
    print("HISTORICAL_DATASET=" + json.dumps(historical_payload.get("dataset"), sort_keys=True))
    print("HISTORICAL_SUMMARY=" + json.dumps(historical_payload.get("summary"), sort_keys=True))
else:
    print("HISTORICAL_API=UNAVAILABLE")

# 5) Compare all waterfall_data volumes read-only using the currently configured backend image.
print("\n=== SQLITE VOLUME COMPARISON ===")
volumes = subprocess.run(
    ["docker", "volume", "ls", "--format", "{{.Name}}"],
    text=True,
    capture_output=True,
    check=True,
).stdout.splitlines()
volumes = sorted(v for v in volumes if "waterfall_data" in v)
print("WATERFALL_VOLUMES=" + json.dumps(volumes))

volume_probe = r'''
import json, os, sqlite3
p = "/data/waterfall_registry.db"
out = {"exists": os.path.exists(p), "size": os.path.getsize(p) if os.path.exists(p) else None}
if not os.path.exists(p):
    print(json.dumps(out)); raise SystemExit(0)
con = sqlite3.connect("file:/data/waterfall_registry.db?mode=ro", uri=True)
out["user_version"] = con.execute("PRAGMA user_version").fetchone()[0]
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
interesting = [t for t in tables if any(x in t.lower() for x in ("histor", "outcome", "signal", "execution", "lifecycle", "candidate", "evaluation"))]
counts = {}
for t in interesting:
    try:
        counts[t] = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    except Exception as exc:
        counts[t] = f"ERROR:{type(exc).__name__}"
out["counts"] = counts
print(json.dumps(out, sort_keys=True))
'''

for volume in volumes:
    p = subprocess.run(
        [
            "docker", "run", "--rm", "--read-only",
            "--entrypoint", "/opt/venv/bin/python",
            "-v", f"{volume}:/data:ro",
            image, "-c", volume_probe,
        ],
        text=True,
        capture_output=True,
    )
    print(f"VOLUME={volume}")
    if p.stdout:
        print(p.stdout.strip())
    if p.stderr:
        print("VOLUME_STDERR=" + p.stderr.strip())
    print("VOLUME_PROBE_RC=" + str(p.returncode))

print("\nDIAGNOSTIC_STATUS=PASS")
print("READ_ONLY=YES")
print("NO_PRODUCTION_CHANGE=YES")
