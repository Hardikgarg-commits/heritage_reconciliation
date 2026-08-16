from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import timedelta
import json
from pathlib import Path
from threading import RLock
import time
from typing import Any

from .models import TelemetryEvent


IOU_THRESHOLD = 0.70


def iou(first: list[float], second: list[float]) -> float:
    """Intersection over union for [x1, y1, x2, y2] boxes."""
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


@dataclass
class ObjectState:
    object_id: str
    bbox: list[float]
    class_label: str
    confidence: float
    drone_id: str
    timestamp: str
    events: list[dict[str, Any]] = field(default_factory=list)
    class_history: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "bbox": self.bbox,
            "class": self.class_label,
            "confidence": self.confidence,
            "drone_id": self.drone_id,
            "timestamp": self.timestamp,
            "event_count": len(self.events),
            "class_history": self.class_history,
        }


class ReconciliationEngine:
    """Append-only event store with deterministic chronological reconstruction."""

    def __init__(self, storage_dir: str | Path | None = None, reliability: dict[str, float] | None = None, persist_interval_seconds: float = 1.0):
        self.storage_dir = Path(storage_dir) if storage_dir else None
        self.reliability = reliability or {}
        self.events: dict[str, dict[str, Any]] = {}
        self.state: list[ObjectState] = []
        self.audit: list[dict[str, Any]] = []
        self._last_order_key: tuple[str, str, str] | None = None
        self._lock = RLock()
        self.persist_interval_seconds = persist_interval_seconds
        self._last_persist_at = 0.0
        if self.storage_dir:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            self._load()

    def _load(self) -> None:
        event_path = self.storage_dir / "events.json"
        if event_path.exists():
            self.events = {event["event_key"]: event for event in json.loads(event_path.read_text(encoding="utf-8"))}
            self.rebuild()

    def _persist(self, force: bool = False) -> None:
        if not self.storage_dir:
            return
        now = time.monotonic()
        if not force and now - self._last_persist_at < self.persist_interval_seconds:
            return
        (self.storage_dir / "events.json").write_text(json.dumps(self.ordered_events(), indent=2), encoding="utf-8")
        (self.storage_dir / "audit.json").write_text(json.dumps(self.audit, indent=2), encoding="utf-8")
        (self.storage_dir / "state.json").write_text(json.dumps(self.current_state(), indent=2), encoding="utf-8")
        self._last_persist_at = now

    def flush(self) -> None:
        """Force durable local JSON snapshots, used during graceful shutdown."""
        with self._lock:
            self._persist(force=True)

    def ordered_events(self) -> list[dict[str, Any]]:
        return sorted(self.events.values(), key=self._order_key)

    @staticmethod
    def _order_key(item: dict[str, Any]) -> tuple[str, str, str]:
        return item["timestamp"], item["drone_id"], item["event_key"]

    def add_event(self, event: TelemetryEvent) -> bool:
        with self._lock:
            key = event.event_key()
            if key in self.events:
                return False
            record = event.model_dump(by_alias=True, mode="json")
            record["event_key"] = key
            self.events[key] = record
            if self._last_order_key is None or self._order_key(record) >= self._last_order_key:
                self._apply_event(record)
                self._last_order_key = self._order_key(record)
            else:
                self.rebuild()
            self._persist()
            return True

    def replay(self, events: list[TelemetryEvent], time_offset_seconds: float = 0) -> int:
        with self._lock:
            added = 0
            for event in events:
                shifted = event.model_copy(update={"timestamp": event.timestamp + timedelta(seconds=time_offset_seconds)})
                key = shifted.event_key()
                if key not in self.events:
                    record = shifted.model_dump(by_alias=True, mode="json")
                    record["event_key"] = key
                    self.events[key] = record
                    added += 1
            self.rebuild()
            self._persist(force=True)
            return added

    def _matching_object(self, bbox: list[float]) -> ObjectState | None:
        matches = [(iou(item.bbox, bbox), item) for item in self.state]
        eligible = [(score, item) for score, item in matches if score > IOU_THRESHOLD]
        return max(eligible, key=lambda pair: (pair[0], pair[1].object_id))[1] if eligible else None

    def _rank(self, event: dict[str, Any], history: list[str]) -> tuple[Any, ...]:
        # Ordered exactly as specified. Lexical fields make the final tie deterministic.
        return (
            float(event["confidence"]),
            event["timestamp"],
            float(self.reliability.get(event["drone_id"], 1.0)),
            history.count(event["class"]),
            event["class"],
            event["drone_id"],
            event["event_key"],
        )

    def rebuild(self) -> None:
        self.state, self.audit = [], []
        for event in self.ordered_events():
            self._apply_event(event)
        self._last_order_key = self._order_key(self.ordered_events()[-1]) if self.events else None

    def _apply_event(self, event: dict[str, Any]) -> None:
        matched = self._matching_object(event["bbox"])
        before = matched.as_dict() if matched else None
        if not matched:
            object_id = f"object-{len(self.state) + 1:04d}"
            new = ObjectState(object_id, event["bbox"], event["class"], event["confidence"], event["drone_id"], event["timestamp"], [event], [event["class"]])
            self.state.append(new)
            self.audit.append(self._audit(event, [], "new_object", new.class_label, before, new.as_dict()))
            return
        candidates = matched.events + [event]
        has_conflict = len({candidate["class"] for candidate in candidates}) > 1
        winner = max(candidates, key=lambda candidate: self._rank(candidate, matched.class_history))
        previous = matched.class_label
        matched.events.append(event)
        matched.class_history.append(event["class"])
        matched.class_label = winner["class"]
        matched.confidence = winner["confidence"]
        matched.drone_id = winner["drone_id"]
        matched.timestamp = winner["timestamp"]
        matched.bbox = winner["bbox"]
        rule = "no_conflict" if not has_conflict else self._applied_rule(candidates, winner, matched.class_history[:-1])
        if previous != matched.class_label and matched.class_label in matched.class_history[:-1]:
            rule += "+historical_reversion_detected"
        self.audit.append(self._audit(event, candidates, rule, matched.class_label, before, matched.as_dict()))

    def _applied_rule(self, candidates: list[dict[str, Any]], winner: dict[str, Any], history: list[str]) -> str:
        rank_names = ["higher_confidence", "newer_timestamp", "higher_drone_reliability", "higher_historical_frequency", "lexical_tiebreak"]
        ranks = [self._rank(candidate, history) for candidate in candidates]
        for index, name in enumerate(rank_names):
            values = {rank[index] for rank in ranks}
            if len(values) > 1:
                return name
        return "identical_event_tiebreak"

    def _audit(self, incoming: dict[str, Any], candidates: list[dict[str, Any]], rule: str, final: str, before: Any, after: Any) -> dict[str, Any]:
        return {
            "decision_id": f"decision-{len(self.audit) + 1:05d}",
            "decision_timestamp": incoming["timestamp"],
            "incoming_event": incoming,
            "input_events_considered": candidates,
            "resolution_rule": rule,
            "final_class": final,
            "state_before": before,
            "state_after": after,
        }

    def current_state(self) -> dict[str, Any]:
        with self._lock:
            return {"object_count": len(self.state), "objects": [item.as_dict() for item in self.state]}

    def audit_trail(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self.audit)
