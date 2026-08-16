from __future__ import annotations

import os
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .engine import ReconciliationEngine
from .models import ReplayRequest, TelemetryEvent


def create_app(storage_dir: str | Path | None = None) -> FastAPI:
    directory = storage_dir or os.getenv("HERITAGE_STORAGE_DIR", "data")
    reliability_path = Path(os.getenv("HERITAGE_RELIABILITY_CONFIG", "config/drone_reliability.json"))
    reliability = {"drone_001": 0.95, "drone_002": 0.90, "drone_003": 0.85}
    if reliability_path.exists():
        reliability = json.loads(reliability_path.read_text(encoding="utf-8"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.engine.flush()

    app = FastAPI(title="Heritage Reconciliation API", version="1.0.0", lifespan=lifespan)
    app.state.engine = ReconciliationEngine(directory, reliability=reliability)

    @app.exception_handler(RequestValidationError)
    async def malformed_event(_: Request, exc: RequestValidationError):
        return JSONResponse(status_code=400, content={"detail": "malformed telemetry event", "errors": exc.errors()})

    @app.post("/events", status_code=status.HTTP_201_CREATED)
    def ingest_event(event: TelemetryEvent):
        if not app.state.engine.add_event(event):
            raise HTTPException(status_code=409, detail="duplicate event: same drone_id, timestamp, and bbox")
        return {"accepted": True, "event_key": event.event_key(), "state": app.state.engine.current_state()}

    @app.post("/events/replay", status_code=status.HTTP_201_CREATED)
    def replay_events(request: ReplayRequest | TelemetryEvent):
        # A single telemetry body is accepted for stream-friendly replay; batches add offsets.
        events = request.events if isinstance(request, ReplayRequest) else [request]
        offset = request.time_offset_seconds if isinstance(request, ReplayRequest) else 0
        added = app.state.engine.replay(events, offset)
        return {"accepted": added, "duplicates_skipped": len(events) - added, "state": app.state.engine.current_state(), "audit": app.state.engine.audit_trail()}

    @app.get("/state")
    def get_state():
        return app.state.engine.current_state()

    @app.get("/audit")
    def get_audit():
        return {"decisions": app.state.engine.audit_trail()}

    return app


app = create_app()
