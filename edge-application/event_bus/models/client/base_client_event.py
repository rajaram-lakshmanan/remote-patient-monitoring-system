#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: base_client_event.py
# Author: Rajaram Lakshmanan
# Description:  Event model for the BLE client.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
import uuid
from typing import List

from pydantic import BaseModel, Field

class BaseClientEvent(BaseModel):
    """Event model for the base client (generic)"""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    client_id: str
    client_type: str
    is_connected: bool
    sensors: List[str]
    message: str = "Unknown message"
    version: str = "1.0"