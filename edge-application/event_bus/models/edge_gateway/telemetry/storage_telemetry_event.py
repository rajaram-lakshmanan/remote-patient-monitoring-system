#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: storage_telemetry_event.py
# Author: Rajaram Lakshmanan
# Description:  Event model for Edge gateway Storage (Root or External) telemetry.
# License: MIT (see LICENSE)
# -----------------------------------------------------------------------------

from typing import List, Optional
from datetime import datetime, timezone
import uuid

from pydantic import BaseModel, Field

class DeviceInfo(BaseModel):
    """Information about a single storage device (filesystem or block device)."""
    device_name: str
    size: str
    used: Optional[str] = None
    available: Optional[str] = None
    use_percent: Optional[str] = None
    mount_point: Optional[str] = None
    rm: bool
    ro: bool
    type: str  # 'filesystem' or 'block device'
    children: List[dict] = []  # List of partitions if applicable

class StorageTelemetryEvent(BaseModel):
    """Event model for storage telemetry (root and external storage)."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    storage_data: List[DeviceInfo]  # Unified storage time_series (filesystem and block devices)
    version: str = "1.0"  # Optional version attribute for backward compatibility
