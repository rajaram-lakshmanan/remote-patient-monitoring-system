#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: sensor_trigger_event.py
# Author: Rajaram Lakshmanan
# Description:  Event model to send a trigger to the sensor to initiate the
# measurement.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
import uuid
from typing import Optional

from pydantic import Field, BaseModel


class SensorTriggerEvent(BaseModel):
    """Event for triggering to start a measurement on a sensor."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sensor_id: str
    trigger_source: str  # e.g., "web_ui", "scheduled", "automated", "cloud"
    request_id: Optional[str] = None  # Optional ID for tracking the request
    user_id: Optional[str] = None  # Optional user who initiated the trigger
    version: str = "1.0"