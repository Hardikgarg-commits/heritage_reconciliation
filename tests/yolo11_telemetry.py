"""Run a local YOLOv11 model and emit its detections in the API telemetry format."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen

from ultralytics import YOLO


def post_json(endpoint: str, payload: dict) -> int:
    request = Request(endpoint, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=10) as response:
        return response.status


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert local YOLOv11 detections into heritage telemetry.")
    parser.add_argument("source", help="Image/video path, camera index, or supported OpenCV source")
    parser.add_argument("--weights", default="yolo11n.pt", help="Use a heritage-trained YOLOv11 .pt file in production")
    parser.add_argument("--drone-id", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/events")
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--save-jsonl", default="data/yolo11_telemetry.jsonl")
    parser.add_argument("--emit", action="store_true", help="POST detections to the reconciliation API")
    args = parser.parse_args()

    model = YOLO(args.weights)
    output = Path(args.save_jsonl)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as stream:
        for result in model.predict(source=args.source, conf=args.confidence, stream=True, verbose=False):
            captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            names = result.names
            for box in result.boxes:
                class_id = int(box.cls.item())
                event = {
                    "drone_id": args.drone_id,
                    "timestamp": captured_at,
                    "bbox": [round(float(value), 3) for value in box.xyxy[0].tolist()],
                    "class": str(names[class_id]),
                    "confidence": round(float(box.conf.item()), 6),
                    "metadata": {"model": Path(args.weights).name, "source": str(args.source), "frame": int(result.path != "")},
                }
                stream.write(json.dumps(event) + "\n")
                stream.flush()
                status = post_json(args.endpoint, event) if args.emit else "saved"
                print(json.dumps({"status": status, "event": event}))


if __name__ == "__main__":
    main()
