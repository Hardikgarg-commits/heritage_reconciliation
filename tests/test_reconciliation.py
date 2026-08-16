from fastapi.testclient import TestClient

from heritage_reconciliation.api import create_app
from heritage_reconciliation.engine import ReconciliationEngine
from heritage_reconciliation.models import TelemetryEvent


def event(drone="drone_001", timestamp="2025-04-05T12:30:00Z", label="archaeological_site", confidence=0.8, bbox=None):
    return {"drone_id": drone, "timestamp": timestamp, "bbox": bbox or [0, 0, 100, 100], "class": label, "confidence": confidence, "metadata": {}}


def test_duplicate_is_rejected_and_idempotent(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert client.post("/events", json=event()).status_code == 201
    assert client.post("/events", json=event()).status_code == 409
    assert client.get("/state").json()["object_count"] == 1


def test_malformed_event_returns_400(tmp_path):
    client = TestClient(create_app(tmp_path))
    invalid = event()
    invalid["bbox"] = [1, 2, 3]
    assert client.post("/events", json=invalid).status_code == 400


def test_conflicting_labels_choose_higher_confidence(tmp_path):
    client = TestClient(create_app(tmp_path))
    client.post("/events", json=event(label="temple_ruin", confidence=.70))
    client.post("/events", json=event("drone_002", "2025-04-05T12:30:01Z", "archaeological_site", .92, [2, 2, 102, 102]))
    result = client.get("/state").json()["objects"][0]
    assert result["class"] == "archaeological_site"
    assert client.get("/audit").json()["decisions"][-1]["resolution_rule"] == "higher_confidence"


def test_tied_confidence_uses_newer_timestamp(tmp_path):
    engine = ReconciliationEngine(tmp_path)
    engine.add_event(TelemetryEvent(**event(label="temple_ruin", confidence=.9)))
    engine.add_event(TelemetryEvent(**event("drone_002", "2025-04-05T12:30:05Z", "archaeological_site", .9, [1, 1, 101, 101])))
    assert engine.current_state()["objects"][0]["class"] == "archaeological_site"
    assert engine.audit_trail()[-1]["resolution_rule"] == "newer_timestamp"


def test_late_event_reconstructs_chronological_timeline(tmp_path):
    engine = ReconciliationEngine(tmp_path)
    engine.add_event(TelemetryEvent(**event(timestamp="2025-04-05T12:30:10Z", confidence=.8)))
    engine.add_event(TelemetryEvent(**event("drone_002", "2025-04-05T12:29:00Z", "temple_ruin", .95, [1, 1, 101, 101])))
    assert engine.audit_trail()[0]["decision_timestamp"] == "2025-04-05T12:29:00Z"
    assert engine.current_state()["objects"][0]["class"] == "temple_ruin"


def test_replay_is_deterministic_and_skips_duplicates(tmp_path):
    client = TestClient(create_app(tmp_path))
    payload = {"events": [event(), event("drone_002", "2025-04-05T12:30:01Z", "temple_ruin", .9, [1, 1, 101, 101])]}
    first = client.post("/events/replay", json=payload)
    state = client.get("/state").json()
    second = client.post("/events/replay", json=payload)
    assert first.json()["accepted"] == 2
    assert second.json()["accepted"] == 0
    assert client.get("/state").json() == state


def test_separate_boxes_remain_separate_objects(tmp_path):
    engine = ReconciliationEngine(tmp_path)
    engine.add_event(TelemetryEvent(**event()))
    engine.add_event(TelemetryEvent(**event("drone_002", "2025-04-05T12:30:01Z", "historic_wall", .8, [300, 300, 400, 400])))
    assert engine.current_state()["object_count"] == 2
