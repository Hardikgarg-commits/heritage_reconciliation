from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TelemetryEvent(BaseModel):
    drone_id: str = Field(min_length=1)
    timestamp: datetime
    bbox: list[float] = Field(min_length=4, max_length=4)
    class_label: str = Field(alias="class", min_length=1)
    confidence: float = Field(ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}

    @field_validator("timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("bbox")
    @classmethod
    def valid_bbox(cls, value: list[float]) -> list[float]:
        x1, y1, x2, y2 = value
        if x2 <= x1 or y2 <= y1:
            raise ValueError("bbox must be [x_min, y_min, x_max, y_max] with positive area")
        return [float(part) for part in value]

    def event_key(self) -> str:
        values = ",".join(f"{part:.6f}" for part in self.bbox)
        return f"{self.drone_id}|{self.timestamp.isoformat()}|{values}"


class ReplayRequest(BaseModel):
    events: list[TelemetryEvent] = Field(min_length=1)
    time_offset_seconds: float = 0
