#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: service_inventory_event.py
# Author: Rajaram Lakshmanan
# Description:  Event model for Edge gateway Service(s) inventory.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from datetime import datetime, timezone
from typing import List
import uuid

from pydantic import BaseModel, Field

class ServiceInventoryEvent(BaseModel):
    """Event model for inventory of running services."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    running_services: List[str]
    running_count: int
    security_services: List[str]
    version: str = "1.0"