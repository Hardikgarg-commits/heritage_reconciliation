"""Replay fixture telemetry as a rate-controlled local drone stream."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def post_json(endpoint: str, payload: dict) -> tuple[int, dict]:
    request = Request(endpoint, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read() or b"{}")
    except HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send simulated multi-drone detections to the local API.")
    parser.add_argument("--fixture", default="fixtures/interacting_edge_cases.json")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/events")
    parser.add_argument("--rate", type=float, default=5, help="events per second")
    parser.add_argument("--loops", type=int, default=1)
    args = parser.parse_args()
    if args.rate <= 0 or args.loops <= 0:
        parser.error("--rate and --loops must be positive")
    events = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    interval = 1 / args.rate
    for loop in range(args.loops):
        for index, event in enumerate(events):
            payload = {key: value for key, value in event.items() if key != "name"}
            code, body = post_json(args.endpoint, payload)
            print(json.dumps({"loop": loop + 1, "event": index + 1, "status": code, "response": body}))
            time.sleep(interval)


if __name__ == "__main__":
    main()
