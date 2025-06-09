#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: cpu_inventory_event.py
# Author: Rajaram Lakshmanan
# Description:  Event model for Edge gateway CPU inventory.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

class CpuInventoryEvent(BaseModel):
    """Event model for CPU inventory."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    pi_model: str
    revision: str
    serial: str
    cpu_cores: int
    cpu_model: str
    cpu_architecture: str
    version: str = "1.0"