#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: sensor_state_event.py
# Author: Rajaram Lakshmanan
# Description:  Event model for the sensor metadata (one-off event).
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
import uuid

from pydantic import BaseModel, Field

class SensorMetadataEvent(BaseModel):
    """Event model for sensor metadata"""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sensor_id: str
    is_enabled: bool
    patient_id: str
    sensor_name: str
    sensor_type: str
    manufacturer: str
    model: str
    firmware_version: str
    hardware_version: str
    description: str
    measurement_units: str
    location: str
    version: str = "1.0"