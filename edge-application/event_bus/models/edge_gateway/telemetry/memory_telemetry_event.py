#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: memory_telemetry_event.py
# Author: Rajaram Lakshmanan
# Description:  Event model for Edge gateway Memory telemetry.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
import uuid

from pydantic import Field, BaseModel

class MemoryTelemetryEvent(BaseModel):
    """Event model for Edge gateway Memory telemetry (in MB)."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_memory: str
    free_memory: str
    available_memory: str
    swap_total_memory: str
    swap_free_memory: str
    version: str = "1.0"