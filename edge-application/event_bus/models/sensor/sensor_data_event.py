#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: sensor_data_event.py
# Author: Rajaram Lakshmanan
# Description:  Event model for the sensor time_series (real-time).
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
from typing import Any, Dict
import uuid

from pydantic import BaseModel, Field

class SensorDataEvent(BaseModel):
    """Event model for sensor time_series"""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sensor_id: str
    patient_id: str
    sensor_name: str
    sensor_type: str
    data: Dict[str, Any]
    version: str = "1.0"