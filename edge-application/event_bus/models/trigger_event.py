#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: trigger_event.py
# Author: Rajaram Lakshmanan
# Description:  Event model for the trigger, this is generic trigger that can
# be used by sensor, edge, or the client.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
from typing import Optional
import uuid

from pydantic import BaseModel, Field

class TriggerEvent(BaseModel):
    """Event model for sending trigger"""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    command_name: str
    trigger_source: str  # e.g., "web_ui", "scheduled", "automated", "cloud"
    request_id: Optional[str] = None  # Optional ID for tracking the request
    user_id: Optional[str] = None  # Optional user who initiated the trigger
    reason: Optional[str] = None
    version: str = "1.0"