"""Dependency-free local load harness for 100+ accepted telemetry events per second."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def make_event(index: int, start: datetime) -> dict:
    # Unique timestamp avoids deliberate duplicate rejection while boxes still associate.
    captured = start + timedelta(microseconds=index * 1_000)
    return {
        "drone_id": f"drone_load_{index % 4:02d}",
        "timestamp": captured.isoformat().replace("+00:00", "Z"),
        "bbox": [100 + (index % 3), 100, 200 + (index % 3), 200],
        "class": "archaeological_site" if index % 2 else "temple_ruin",
        "confidence": 0.7 + (index % 25) / 100,
        "metadata": {"load_test": True, "sequence": index},
    }


def send(endpoint: str, payload: dict) -> int:
    request = Request(endpoint, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=15) as response:
            return response.status
    except HTTPError as error:
        return error.code


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify local API throughput without external services.")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/events")
    parser.add_argument("--events", type=int, default=500)
    args = parser.parse_args()
    if args.events < 100:
        parser.error("use at least 100 events to verify the stated requirement")
    started = time.perf_counter()
    events = [make_event(index, datetime.now(timezone.utc)) for index in range(args.events)]
    # Sequential submission preserves capture order, which represents normal telemetry.
    # The API itself also serializes mutations to protect state consistency.
    statuses = [send(args.endpoint, payload) for payload in events]
    elapsed = time.perf_counter() - started
    successful = sum(status == 201 for status in statuses)
    report = {"submitted": args.events, "accepted": successful, "elapsed_seconds": round(elapsed, 3), "events_per_second": round(successful / elapsed, 2), "status_counts": {str(code): statuses.count(code) for code in sorted(set(statuses))}}
    print(json.dumps(report, indent=2))
    if successful != args.events or successful / elapsed < 100:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
