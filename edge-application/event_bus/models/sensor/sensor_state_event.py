#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: sensor_state_event.py
# Author: Rajaram Lakshmanan
# Description:  Event model for representing the state (active or inactive)
# of a sensor (State change acts as a trigger).
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
import uuid

from pydantic import BaseModel, Field

class SensorStateEvent(BaseModel):
    """Event model for representing the state (active or inactive) of a sensor."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sensor_id: str
    sensor_name: str
    sensor_type: str
    is_active: bool
    inactive_minutes: float
    version: str = "1.0"
