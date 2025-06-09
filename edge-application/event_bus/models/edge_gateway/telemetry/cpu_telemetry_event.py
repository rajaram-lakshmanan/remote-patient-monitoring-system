#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: cpu_telemetry_event.py
# Author: Rajaram Lakshmanan
# Description:  Event model for Edge gateway CPU telemetry.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
import uuid

from pydantic import Field, BaseModel

class CpuTelemetryEvent(BaseModel):
    """Event model for Edge gateway CPU telemetry."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    temperature_celsius: float
    frequency_mhz: float
    version: str = "1.0"