# HeritageLens Reconciliation MVP

Local FastAPI + Streamlit system for reconciling asynchronous YOLOv11 telemetry from overlapping drones. It does not run training or drone control; it reconciles detector outputs.

## Design

Events are retained in an append-only local JSON event store. Every accepted event triggers a full chronological reconstruction sorted by `(timestamp, drone_id, event_key)`. This makes late arrivals deterministic and replayable. Detections associate when IoU is greater than 0.70.

For a shared object with different labels, the winner is selected in this exact order: highest confidence, newest timestamp, highest configured drone reliability, highest prior class frequency, then stable lexical fields. Every reconstruction emits decision records with candidates, rule, state before, and state after. JSON state, event, and audit files are written to `data/` by default.

Drone reliability is configured in `config/drone_reliability.json`; point `HERITAGE_RELIABILITY_CONFIG` to another local JSON mapping to override it.

To sustain live ingestion, JSON snapshots flush at most once per second and are forcibly flushed during a graceful API shutdown. This avoids rewriting the full append-only audit trail on every event.

## Setup and run

```powershell
cd heritage_reconciliation
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn heritage_reconciliation.api:app --reload
```

In another terminal:

```powershell
cd heritage_reconciliation
.\.venv\Scripts\Activate.ps1
streamlit run dashboard.py
pytest -q
```

## API

`POST /events` accepts the required single telemetry JSON event and returns `201`. Malformed requests return `400`; duplicate `drone_id + timestamp + bbox` events return `409` without changing state.

`POST /events/replay` accepts either one telemetry event or `{"events": [events...], "time_offset_seconds": 0}`. The batch is replayed chronologically after an optional offset and duplicates are skipped.

`GET /state` returns the current unified object state. `GET /audit` returns the chronological decision trace.

Example:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/events -ContentType application/json -Body '{"drone_id":"drone_001","timestamp":"2025-04-05T12:30:00Z","bbox":[100,100,200,200],"class":"archaeological_site","confidence":0.87,"metadata":{"lighting":"low"}}'
```

## Fixtures and audit outputs

`fixtures/interacting_edge_cases.json` provides six interacting inputs covering cross-drone labels, late arrival, timestamp tie-break, separate objects, and duplicate identity. Runtime audit outputs appear in `data/audit.json`; the dashboard exposes each full decision locally.

## Tests

The automated suite covers duplicate/idempotency behavior, cross-drone conflicts, temporal tie breaking, late event reconstruction, replay determinism, and independent-object state consistency.

## Simulated stream, YOLOv11, and throughput verification

With the API running, send the edge-case stream at 100 events/second:

```powershell
python scripts/simulate_telemetry.py --rate 100
python scripts/load_test.py --events 500
```

The load command exits non-zero unless every event is accepted and measured throughput is at least 100 events/sec.

To run actual local detector inference, provide imagery and a heritage-trained YOLOv11 weights file (the default `yolo11n.pt` can download automatically but has generic COCO labels):

```powershell
python scripts/yolo11_telemetry.py path\to\site.jpg --weights path\to\heritage_yolo11.pt --drone-id drone_001 --emit
```

The adapter writes newline-delimited detection telemetry to `data/yolo11_telemetry.jsonl` and, with `--emit`, posts each detection to the API.
